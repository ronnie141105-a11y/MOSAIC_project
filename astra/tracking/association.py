"""
Track association heuristics (Milestone 5).

Pure functions, no engine state -- mirrors ``astra.hotspot.distance``'s
pattern of a small, independently-testable pure-math module feeding the
stateful engine (``astra.tracking.engine.TrackerEngine``). See
this module's own docstring above for the matching-strategy rationale.
"""

from typing import Dict, FrozenSet, List, Optional, Tuple

from astra.hotspot.models import Cluster
from astra.tracking.models import FourDArhac
from astra.utils.geodesy import haversine_distance_nm

#: Cost assigned to a candidate region/track pair that clears neither
#: the primary Jaccard threshold nor the centroid/extent-overlap
#: fallback -- large enough that the Hungarian solver in
#: ``optimal_track_assignment`` never prefers it over leaving either
#: side unmatched, but finite (not ``inf``) so ``scipy``'s dense solver
#: (which requires a finite-cost matrix) stays well-defined even when
#: every candidate for some region is ineligible.
_INELIGIBLE_COST = 1e6


def jaccard_similarity(a: FrozenSet[str], b: FrozenSet[str]) -> float:
    """Jaccard similarity (|intersection| / |union|) of two callsign sets.

    Args:
        a: First set of callsigns.
        b: Second set of callsigns.

    Returns:
        A value in ``[0, 1]``; ``0.0`` if both sets are empty (no
        meaningful overlap to claim) or disjoint.
    """
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def centroid_extent_overlap(cluster_a: Cluster, cluster_b: Cluster) -> bool:
    """True if two clusters' centroid+extent circles intersect.

    Fallback matching signal for cases -- e.g. longer-horizon predictions
    or several elapsed poll cycles -- where member-callsign overlap has
    drifted below the primary Jaccard threshold but the physical area of
    high complexity plausibly coincides.

    Args:
        cluster_a: First cluster.
        cluster_b: Second cluster.

    Returns:
        ``True`` if the great-circle distance between centroids is no
        greater than the sum of both clusters' ``horizontal_extent_nm``.
    """
    distance_nm = haversine_distance_nm(
        cluster_a.centroid_lat,
        cluster_a.centroid_lon,
        cluster_b.centroid_lat,
        cluster_b.centroid_lon,
    )
    return distance_nm <= (
        cluster_a.horizontal_extent_nm + cluster_b.horizontal_extent_nm
    )


def best_cluster_match(
    reference_cluster: Cluster,
    candidate_clusters: List[Cluster],
    jaccard_threshold: float,
) -> Optional[Cluster]:
    """Find the best-matching cluster in ``candidate_clusters`` for ``reference_cluster``.

    Orientation-agnostic core of the association heuristic.
    ``best_track_match`` (Milestone 5) builds on this to match a newly
    detected cluster against open tracks. ``astra.forecast.horizon_series``
    (Milestone 6) builds on it the other way round, to match one track's
    most recent cluster against a horizon's candidate predicted regions.
    See astra/tracking/engine.py's and astra/forecast/horizon_series.py's
    module docstrings.

    Primary signal: Jaccard similarity of ``member_callsigns``; a
    candidate must meet ``jaccard_threshold`` to be eligible. Among
    candidates that clear the threshold, the highest Jaccard similarity
    wins (ties broken by smaller centroid distance).

    Fallback: if no candidate clears the Jaccard threshold, centroid/
    extent circle overlap is used instead (smallest centroid distance
    wins among overlapping candidates).

    Args:
        reference_cluster: The cluster to find a match for.
        candidate_clusters: Clusters eligible for matching.
        jaccard_threshold: Minimum Jaccard similarity to accept a
            primary match (``ASTRAConfig.tracking_jaccard_threshold``).

    Returns:
        The best-matching ``Cluster``, or ``None`` if no candidate
        clears either the primary or fallback signal.
    """
    scored: List[Tuple[Cluster, float, float, bool]] = []
    for candidate in candidate_clusters:
        jaccard = jaccard_similarity(
            reference_cluster.member_callsigns, candidate.member_callsigns
        )
        distance_nm = haversine_distance_nm(
            reference_cluster.centroid_lat,
            reference_cluster.centroid_lon,
            candidate.centroid_lat,
            candidate.centroid_lon,
        )
        overlaps = centroid_extent_overlap(reference_cluster, candidate)
        scored.append((candidate, jaccard, distance_nm, overlaps))

    primary = [entry for entry in scored if entry[1] >= jaccard_threshold]
    if primary:
        primary.sort(key=lambda entry: (-entry[1], entry[2]))
        return primary[0][0]

    fallback = [entry for entry in scored if entry[3]]
    if fallback:
        fallback.sort(key=lambda entry: entry[2])
        return fallback[0][0]

    return None


def best_track_match(
    new_cluster: Cluster,
    candidate_tracks: List[FourDArhac],
    jaccard_threshold: float,
) -> Optional[FourDArhac]:
    """Find the best-matching open track for a newly detected cluster.

    Thin wrapper around ``best_cluster_match``: extracts each candidate
    track's most recent cluster, matches, and maps the winning cluster
    back to its owning track.

    Args:
        new_cluster: The freshly detected ``Cluster`` to associate.
        candidate_tracks: Open tracks eligible for matching this cycle
            (callers should already exclude tracks claimed earlier in
            the same cycle, to keep matching one-to-one per cycle).
            A track with an empty ``track`` (i.e. still ``PROVISIONAL``
            -- see ``astra.tracking.engine``'s module docstring) is
            matched against its ``provisional_track``'s last entry
            instead; a track with neither (should not normally occur)
            is skipped.
        jaccard_threshold: Minimum Jaccard similarity to accept a
            primary match (``ASTRAConfig.tracking_jaccard_threshold``).

    Returns:
        The best-matching ``FourDArhac``, or ``None`` if no candidate
        clears either the primary or fallback signal.
    """
    track_by_last_cluster = {}
    candidate_clusters: List[Cluster] = []
    for track in candidate_tracks:
        if track.track:
            last_cluster = track.track[-1].cluster
        elif track.provisional_track:
            last_cluster = track.provisional_track[-1].cluster
        else:
            continue
        candidate_clusters.append(last_cluster)
        track_by_last_cluster[last_cluster] = track

    matched_cluster = best_cluster_match(new_cluster, candidate_clusters, jaccard_threshold)
    if matched_cluster is None:
        return None
    return track_by_last_cluster[matched_cluster]


def _pair_cost(reference_cluster: Cluster, candidate: Cluster, jaccard_threshold: float) -> float:
    """Cost of matching ``reference_cluster`` to ``candidate`` (lower is better).

    Mirrors ``best_cluster_match``'s own eligibility rule (primary
    Jaccard threshold, centroid/extent-overlap fallback) but returns a
    continuous cost instead of a boolean/ranked pick, so several
    region/track pairs can be compared and solved jointly by
    ``optimal_track_assignment``. An eligible pair's cost is
    ``1 - jaccard`` (so higher similarity always costs less, matching
    ``best_cluster_match``'s own primary tie-break), nudged by a tiny
    distance-based term to preserve its secondary "closer centroid wins
    a Jaccard tie" tie-break; an eligible-only-via-fallback pair costs
    slightly more than any primary-eligible pair, ranked by centroid
    distance alone, matching ``best_cluster_match``'s fallback tier
    exactly. An ineligible pair costs ``_INELIGIBLE_COST`` regardless of
    distance, so the solver only ever picks it when literally nothing
    else is available for that region or track (row/column count
    mismatch), never in preference to a real match elsewhere.
    """
    jaccard = jaccard_similarity(reference_cluster.member_callsigns, candidate.member_callsigns)
    distance_nm = haversine_distance_nm(
        reference_cluster.centroid_lat,
        reference_cluster.centroid_lon,
        candidate.centroid_lat,
        candidate.centroid_lon,
    )
    # Distance nudge kept far smaller than the smallest possible Jaccard
    # gap (1 / max union size in practice) so it only ever breaks ties,
    # never overrides a genuine similarity difference.
    distance_nudge = min(distance_nm, 1000.0) * 1e-6
    if jaccard >= jaccard_threshold:
        return (1.0 - jaccard) + distance_nudge
    if centroid_extent_overlap(reference_cluster, candidate):
        # Strictly worse than every primary-eligible pair (whose cost is
        # always < 1.0 + nudge), ranked by distance alone -- same
        # fallback-tier behaviour as best_cluster_match.
        return 1.0 + distance_nudge
    return _INELIGIBLE_COST


def optimal_track_assignment(
    regions: List[Cluster],
    candidate_tracks: List[FourDArhac],
    jaccard_threshold: float,
) -> Dict[int, FourDArhac]:
    """Globally-optimal one-to-one matching of several regions to several tracks.

    Unlike calling ``best_track_match`` once per region in a loop (which
    matches greedily, in whatever order the caller iterates regions --
    an early region can claim a track that would have been an even
    better match for a *later* region, with no way to reconsider once
    claimed -- see ``ASTRAConfig.tracking_use_optimal_assignment``'s
    docstring), this solves the whole cycle's region-to-track
    association as one assignment problem: build an
    ``len(regions) x len(candidate_tracks)`` cost matrix from
    ``_pair_cost`` and solve it with the Hungarian algorithm
    (``scipy.optimize.linear_sum_assignment``), which finds the
    assignment minimising *total* cost across every region at once --
    the textbook-optimal solution to this exact problem, not an
    approximation.

    A track with an empty ``track`` (still ``PROVISIONAL``) is matched
    against its ``provisional_track``'s last entry instead, exactly like
    ``best_track_match``; a track with neither is skipped (never
    offered as a candidate).

    Args:
        regions: This cycle's freshly detected ``Cluster``s (from each
            region's ``ComplexityRegion.cluster``), in the order the
            caller wants ``0..len(regions)-1`` keys assigned.
        candidate_tracks: Open tracks eligible for matching this cycle.
        jaccard_threshold: Minimum Jaccard similarity to accept a
            primary association match (``ASTRAConfig.tracking_jaccard_threshold``).

    Returns:
        ``{region_index: matched_track}`` for every region that found an
        eligible match (primary or fallback) at a cost strictly less
        than ``_INELIGIBLE_COST`` -- a region index missing from the
        returned dict found no eligible track and should open a new
        track, exactly as a ``None`` return from ``best_track_match``
        would signal. Never assigns two regions to the same track, and
        never assigns one region to two tracks.
    """
    if not regions or not candidate_tracks:
        return {}

    track_clusters: List[Tuple[FourDArhac, Cluster]] = []
    for track in candidate_tracks:
        if track.track:
            track_clusters.append((track, track.track[-1].cluster))
        elif track.provisional_track:
            track_clusters.append((track, track.provisional_track[-1].cluster))
        # else: skipped, mirrors best_track_match's "neither" case.

    if not track_clusters:
        return {}

    # Imported lazily (rather than at module scope) so a scipy-less
    # environment only fails if this specific function is actually
    # called -- every other function in this module has no scipy
    # dependency at all.
    from scipy.optimize import linear_sum_assignment

    import numpy as np

    cost_matrix = np.array(
        [
            [_pair_cost(region, cluster, jaccard_threshold) for _, cluster in track_clusters]
            for region in regions
        ]
    )
    row_indices, col_indices = linear_sum_assignment(cost_matrix)

    result: Dict[int, FourDArhac] = {}
    for row, col in zip(row_indices, col_indices):
        if cost_matrix[row, col] >= _INELIGIBLE_COST:
            continue
        result[int(row)] = track_clusters[int(col)][0]
    return result
