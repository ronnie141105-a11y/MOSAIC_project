"""
Static hotspot spatial shape, anchored on predicted loss of separation
(dashboard visual-spec update, v3).

Defines ``HotspotBox`` and ``compute_hotspot_box``. Supersedes the v2
design (anchored on the track's own predicted/observed *peak
complexity* time). Per explicit follow-up feedback, the corridor is now
anchored on something concrete and checkable rather than the abstract
complexity score: an actual predicted loss of separation between a pair
of member aircraft, using the standard "either/or" separation rule --

    Two aircraft are properly separated if they have AT LEAST
    ``conflict_horizontal_min_nm`` laterally OR AT LEAST
    ``conflict_vertical_min_ft`` vertically. A genuine loss of
    separation is when NEITHER holds (closer than both at once).

For every pair of a track's member aircraft, this module walks their
predicted trajectories (routes when known, straight-line dead
reckoning otherwise) forward in time and asks: does this pair actually
come within both minima at some point? If so, the corridor's time
window is the *buffer* zone around that event -- from the predicted
time separation first drops to ``hotspot_horizontal_buffer_nm``
(a lateral early-warning margin) until it recovers back past that same
buffer -- not the bare instant of violation, so the shape reads as
"closing in" and "opening back up" rather than blinking in and out of
existence. A track with no pair that ever actually violates real
separation has no corridor to draw at all.

The shape itself traces the conflicting pair's own remaining route
(``CycleResult.routes``) or straight predicted trajectory, drawn
strictly *between* them (no outward lateral padding) -- see
``_route_window_polyline`` below, unchanged from the v2 design.

This module performs geometry only (composition over existing
``FourDArhac``/``TrafficSnapshot``/route data) -- it does not mutate any
of its inputs.
"""

import math
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional, Tuple

from astra.complexity.conflict import closest_point_of_approach
from astra.interface.traffic_state import AircraftState, TrafficSnapshot
from astra.tracking.models import FourDArhac
from astra.utils.config import ASTRAConfig
from astra.utils.geodesy import (
    haversine_distance_nm,
    latlon_from_tangent_plane_nm,
    local_tangent_plane_nm,
    move_position,
)

#: Safety cap mirroring `astra.trajectory.route_following.MAX_LEGS_PER_CALL`
#: -- a route with a pathological number of remaining waypoints can never
#: make this loop unboundedly.
_MAX_ROUTE_LEGS = 50

#: Minimum along-axis half-length (NM) used only for the degenerate case
#: of a single-instant window (start distance == end distance for every
#: member) -- a corridor needs *some* length to be a visible 2D shape at
#: all. Not lateral padding past the routes; purely a rendering floor
#: for an otherwise zero-length edge.
_MIN_DEGENERATE_HALF_LENGTH_NM = 1.0

#: Default half-width (NM) used when a track has exactly one member
#: aircraft, OR when its two "outer" aircraft turn out to be on
#: (near-)the same track -- in both cases there's no genuine second,
#: separated route to bound the corridor against, so a modest
#: representative width is drawn around the shared path instead.
_SINGLE_AIRCRAFT_HALF_WIDTH_NM = 4.0

#: Below this cross-track separation (NM) between the two "outer"
#: aircraft, they're treated as being on the same track (e.g. one
#: following the other toward a shared waypoint) -- the corridor is
#: still drawn *centered on* that shared track, at the same
#: `_SINGLE_AIRCRAFT_HALF_WIDTH_NM`, rather than as a literal
#: zero-width line.
_MIN_CORRIDOR_SEPARATION_NM = 2.0

#: Multiplier applied to the buffer thresholds when cheaply pre-filtering
#: a pair before the full per-sample scan (2026-07 performance fix; see
#: `_pairwise_conflict_window`'s own docstring). Generous on purpose:
#: the pre-filter uses a straight-line constant-velocity CPA, which
#: ignores route curvature, so this margin absorbs a reasonable amount
#: of "the route bends toward the other aircraft" slack that the exact
#: analytical straight-line answer wouldn't otherwise account for.
_PREFILTER_SAFETY_MARGIN = 2.0


@dataclass(frozen=True)
class HotspotBox:
    """A static spatial shape anchored on a predicted loss of separation.

    Attributes:
        arhac_id: The ``FourDArhac`` this shape was computed for.
        start_time_s: Predicted time the worst-affected pair's
            separation first drops to the buffer thresholds
            (``hotspot_horizontal_buffer_nm``/``hotspot_vertical_buffer_ft``)
            on its way toward an actual violation.
        end_time_s: Predicted time separation recovers back past those
            same buffer thresholds after the closest point of
            approach.
        polygon: The shape's ``(lat, lon)`` points, in order (draw a
            closed polygon by connecting consecutive points and
            wrapping back to the first). Traces ``left_callsign``'s own
            route/trajectory (in the direction of travel) as one edge
            and ``right_callsign``'s own route/trajectory (reversed) as
            the other -- no lateral padding past either one, so the
            shape's interior sits strictly inside the two outer routes.
        left_callsign: The member aircraft whose route/trajectory forms
            one lateral (outer) border of the shape.
        right_callsign: The member aircraft whose route/trajectory
            forms the other lateral (outer) border -- together with
            ``left_callsign``, the "two furthest outer routes" the
            shape is anchored on.
        member_callsigns: Every member aircraft enclosed by the shape
            (including ``left_callsign``/``right_callsign``).
        peak_complexity: The track's predicted peak complexity score --
            carried here purely for display (e.g. colour intensity),
            not used in the geometry itself.
    """

    arhac_id: str
    start_time_s: float
    end_time_s: float
    polygon: List[Tuple[float, float]]
    left_callsign: Optional[str]
    right_callsign: Optional[str]
    member_callsigns: FrozenSet[str]
    peak_complexity: float


def _circular_mean_bearing_deg(bearings_deg: List[float]) -> float:
    """Mean of a list of compass bearings, handling the 0/360 wraparound."""
    sin_sum = sum(math.sin(math.radians(b)) for b in bearings_deg)
    cos_sum = sum(math.cos(math.radians(b)) for b in bearings_deg)
    if abs(sin_sum) < 1e-9 and abs(cos_sum) < 1e-9:
        return 0.0
    return math.degrees(math.atan2(sin_sum, cos_sum)) % 360.0


def _build_route_vertices(
    lat: float, lon: float, route_waypoints: Optional[List[Tuple[float, float]]]
) -> List[Tuple[float, float, float]]:
    """Precompute ``[(cumulative_nm, lat, lon), ...]`` for one aircraft's
    route, starting from its current position (distance 0).

    Built once per aircraft and reused across every time sample and
    every pair it appears in -- see this module's own note (2026-07
    performance fix) on why rebuilding this per-sample was the
    dominant cost of the whole pipeline for anything but a trivial
    number of aircraft.
    """
    vertices: List[Tuple[float, float, float]] = [(0.0, lat, lon)]
    if route_waypoints:
        prev_lat, prev_lon = lat, lon
        cumulative_nm = 0.0
        for wp_lat, wp_lon in route_waypoints[:_MAX_ROUTE_LEGS]:
            cumulative_nm += haversine_distance_nm(prev_lat, prev_lon, wp_lat, wp_lon)
            vertices.append((cumulative_nm, wp_lat, wp_lon))
            prev_lat, prev_lon = wp_lat, wp_lon
    return vertices


def _point_at_distance(
    vertices: List[Tuple[float, float, float]], heading_deg: float, target_nm: float
) -> Tuple[float, float]:
    """Fast repeated-query counterpart of ``_route_window_polyline``'s
    single-point lookup, given vertices already built by
    ``_build_route_vertices`` -- O(route length) per call instead of
    O(route length) of *setup* plus the lookup, every single call.

    No route (``vertices`` has only the origin) short-circuits straight
    to a single ``move_position`` call -- the cheapest possible path
    for the overwhelmingly common "no known route" case, rather than
    walking a one-entry list to reach the same answer.
    """
    if len(vertices) == 1:
        _, lat0, lon0 = vertices[0]
        return move_position(lat0, lon0, heading_deg, target_nm)
    total_nm = vertices[-1][0]
    target_nm = max(0.0, min(total_nm, target_nm))
    for i in range(1, len(vertices)):
        d0, lat0, lon0 = vertices[i - 1]
        d1, lat1, lon1 = vertices[i]
        if target_nm <= d1 + 1e-9:
            if d1 - d0 < 1e-9:
                return lat1, lon1
            frac = (target_nm - d0) / (d1 - d0)
            return lat0 + (lat1 - lat0) * frac, lon0 + (lon1 - lon0) * frac
    return vertices[-1][1], vertices[-1][2]


def _pairwise_conflict_window(
    ac_a: AircraftState,
    vertices_a: List[Tuple[float, float, float]],
    ac_b: AircraftState,
    vertices_b: List[Tuple[float, float, float]],
    config: ASTRAConfig,
    max_horizon_s: float,
) -> Optional[Tuple[float, float]]:
    """The buffer-zone window (seconds from now) around a genuine predicted
    loss of separation between two aircraft, or ``None`` if they never
    actually violate both real separation minima at once within
    ``max_horizon_s``.

    Samples both aircraft's predicted horizontal/vertical separation
    every ``config.hotspot_conflict_sample_step_s`` out to
    ``max_horizon_s``, rather than solving for the closest point of
    approach analytically -- this is what lets it handle a route that
    turns (a non-constant-velocity path) the same way it handles
    straight-line dead reckoning. ``vertices_a``/``vertices_b`` must
    already be built (once per aircraft, see
    ``_build_route_vertices``) -- this function itself does no route
    parsing, only cheap distance queries against them.

    Returns:
        ``(t_start_s, t_end_s)`` -- both relative to now -- spanning
        from the first sample where both separations are within their
        buffer thresholds (``hotspot_horizontal_buffer_nm``/
        ``hotspot_vertical_buffer_ft``) through the last such sample in
        the same contiguous run that contains at least one genuine
        violation (below both real minima at once), or ``None`` if no
        sample ever violates both real minima simultaneously.
    """
    step_s = config.hotspot_conflict_sample_step_s

    # Fast pre-filter (2026-07 performance fix): before paying for a
    # few hundred samples, rule out the overwhelmingly common case --
    # a pair that never comes anywhere close -- with two cheap,
    # analytical O(1) checks. A genuine conflict needs BOTH the
    # horizontal AND vertical separation to close within their buffer
    # at the same time, so definitively ruling out *either* dimension
    # alone is enough to skip the pair entirely.
    #
    # Horizontal: `closest_point_of_approach` is the same
    # straight-line, constant-velocity CPA used for MTCA/LTCA
    # complexity scoring elsewhere (`astra.complexity.conflict`); it
    # finds the minimum distance over ALL future time (it already
    # clamps to `time_to_cpa >= 0`, i.e. never looks into the past),
    # which is a valid lower bound on the true minimum within our
    # finite `[0, max_horizon_s]` window regardless of whether the
    # unconstrained CPA time itself falls inside that window or beyond
    # it: restricting to a shorter window can only ever raise the
    # achieved minimum, never lower it. It also ignores route
    # curvature, so it's only used here as a generous (2x-buffered)
    # filter, never as the actual answer.
    origin_lat = (ac_a.lat + ac_b.lat) / 2.0
    origin_lon = (ac_a.lon + ac_b.lon) / 2.0
    cpa = closest_point_of_approach(origin_lat, origin_lon, ac_a, ac_b)
    if cpa.distance_nm > config.hotspot_horizontal_buffer_nm * _PREFILTER_SAFETY_MARGIN:
        return None  # Never gets close enough, even generously buffered.

    # Vertical: altitude vs. time is exactly linear for each aircraft
    # (constant `vertical_speed_fpm`), so their SIGNED difference
    # `d(t)` is linear too. If `d(t)` doesn't change sign across
    # `[0, max_horizon_s]`, `|d(t)|` is monotonic over that interval
    # and its minimum is at one of the two endpoints. If it DOES
    # change sign (one climbing through the other's level, e.g.), the
    # true minimum is 0 -- checking only the endpoints would wrongly
    # treat "starts far apart, ends far apart" as "never close",
    # missing that they actually cross paths vertically in between.
    d_now = ac_a.altitude_ft - ac_b.altitude_ft
    alt_a_end = ac_a.altitude_ft + ac_a.vertical_speed_fpm * max_horizon_s / 60.0
    alt_b_end = ac_b.altitude_ft + ac_b.vertical_speed_fpm * max_horizon_s / 60.0
    d_end = alt_a_end - alt_b_end
    if d_now == 0.0 or d_end == 0.0 or (d_now > 0) != (d_end > 0):
        min_alt_diff_ft = 0.0  # sign change (or exact touch) somewhere in the window
    else:
        min_alt_diff_ft = min(abs(d_now), abs(d_end))
    if min_alt_diff_ft > config.hotspot_vertical_buffer_ft * _PREFILTER_SAFETY_MARGIN:
        return None  # Vertical gap never closes enough either, at any time.

    n_steps = max(1, int(max_horizon_s // step_s))
    samples = []
    for i in range(n_steps + 1):
        t_s = i * step_s
        d_a_nm = ac_a.ground_speed_kt * t_s / 3600.0
        d_b_nm = ac_b.ground_speed_kt * t_s / 3600.0
        lat_a, lon_a = _point_at_distance(vertices_a, ac_a.heading_deg, d_a_nm)
        lat_b, lon_b = _point_at_distance(vertices_b, ac_b.heading_deg, d_b_nm)
        alt_a = max(0.0, ac_a.altitude_ft + ac_a.vertical_speed_fpm * t_s / 60.0)
        alt_b = max(0.0, ac_b.altitude_ft + ac_b.vertical_speed_fpm * t_s / 60.0)
        h_sep_nm = haversine_distance_nm(lat_a, lon_a, lat_b, lon_b)
        v_sep_ft = abs(alt_a - alt_b)
        samples.append((t_s, h_sep_nm, v_sep_ft))

    conflict_indices = [
        i
        for i, (_, h, v) in enumerate(samples)
        if h < config.conflict_horizontal_min_nm and v < config.conflict_vertical_min_ft
    ]
    if not conflict_indices:
        return None  # Never actually violates real separation minima.

    in_buffer = [
        h <= config.hotspot_horizontal_buffer_nm and v <= config.hotspot_vertical_buffer_ft
        for _, h, v in samples
    ]

    # Walk outward from the earliest/latest genuine violation while
    # still inside the buffer zone, to capture the full contiguous
    # "closing in ... opening back up" run rather than just the bare
    # violating instant(s).
    start_idx = conflict_indices[0]
    while start_idx > 0 and in_buffer[start_idx - 1]:
        start_idx -= 1
    end_idx = conflict_indices[-1]
    while end_idx < len(samples) - 1 and in_buffer[end_idx + 1]:
        end_idx += 1

    return samples[start_idx][0], samples[end_idx][0]


#: Hard cap on how many member aircraft take part in the full O(n^2)
#: pairwise conflict search (2026-07 performance fix). Pair count grows
#: quadratically with cluster size, so an unusually large single
#: cluster (a busy merge point with many aircraft converging from
#: different directions, say) could otherwise make one cycle's search
#: cost balloon far past what a handful of realistic hotspot-sized
#: clusters (2-8 aircraft) ever approach. Beyond this cap, only the
#: `_MAX_MEMBERS_FOR_PAIRWISE_SEARCH` aircraft closest to the group's
#: own centroid are searched -- a reasonable proxy for "most likely to
#: actually be involved in whatever's converging here" -- rather than
#: search silently growing unbounded with cluster size.
_MAX_MEMBERS_FOR_PAIRWISE_SEARCH = 12


def _overall_conflict_window(
    members_present: List[str],
    now_ac: Dict[str, AircraftState],
    routes: dict,
    config: ASTRAConfig,
) -> Optional[Tuple[float, float, str, str]]:
    """The union conflict window across every member pair, plus which
    pair defines it (used as a reasonable choice of the two "outer"
    aircraft when there are more than two members).

    Returns:
        ``(start_s, end_s, pair_a, pair_b)`` -- absolute
        (already offset from "now") start/end and the callsigns of
        whichever pair produced the union's own start -- or ``None`` if
        no member pair ever actually violates real separation minima.
    """
    if len(members_present) > _MAX_MEMBERS_FOR_PAIRWISE_SEARCH:
        centroid_lat = sum(now_ac[cs].lat for cs in members_present) / len(members_present)
        centroid_lon = sum(now_ac[cs].lon for cs in members_present) / len(members_present)
        members_present = sorted(
            members_present,
            key=lambda cs: haversine_distance_nm(centroid_lat, centroid_lon, now_ac[cs].lat, now_ac[cs].lon),
        )[:_MAX_MEMBERS_FOR_PAIRWISE_SEARCH]

    max_horizon_s = config.max_prediction_horizon_min * 60.0
    # Build each aircraft's route vertices exactly once, however many
    # pairs it appears in -- see `_build_route_vertices`'s own note on
    # why rebuilding this per-pair-per-sample used to dominate an
    # entire cycle's runtime.
    vertices_by_cs = {
        cs: _build_route_vertices(now_ac[cs].lat, now_ac[cs].lon, routes.get(cs)) for cs in members_present
    }
    best: Optional[Tuple[float, float, str, str]] = None
    for i in range(len(members_present)):
        for j in range(i + 1, len(members_present)):
            cs_a, cs_b = members_present[i], members_present[j]
            window = _pairwise_conflict_window(
                now_ac[cs_a],
                vertices_by_cs[cs_a],
                now_ac[cs_b],
                vertices_by_cs[cs_b],
                config,
                max_horizon_s,
            )
            if window is None:
                continue
            t_start_s, t_end_s = window
            if best is None or t_start_s < best[0]:
                best = (t_start_s, t_end_s, cs_a, cs_b)
            elif t_end_s > best[1]:
                best = (best[0], t_end_s, best[2], best[3])
    return best


def _route_window_polyline(
    lat: float,
    lon: float,
    heading_deg: float,
    route_waypoints: Optional[List[Tuple[float, float]]],
    d_start_nm: float,
    d_end_nm: float,
) -> List[Tuple[float, float]]:
    """The along-track segment of a route (or straight dead-reckoning line)
    lying between ``d_start_nm`` and ``d_end_nm`` from ``(lat, lon)``.

    Follows every waypoint the route actually passes through in that
    span (so a route that turns shows up as a bend here too), with
    interpolated endpoints exactly at ``d_start_nm``/``d_end_nm`` --
    this is what makes the drawn shape a real "along the route"
    corridor instead of a coarse straight-line approximation. Falls
    back to a single straight leg at ``heading_deg`` when no route is
    known, matching the same dead-reckoning assumption
    ``astra.trajectory.engine.predict_constant_velocity`` uses
    elsewhere.

    Args:
        lat, lon: Aircraft's current position.
        heading_deg: Current heading (used only without a route).
        route_waypoints: Ordered ``[(lat, lon), ...]`` remaining
            waypoints ahead of the aircraft (not including its current
            position), or ``None``/empty if no route is known.
        d_start_nm: Along-track distance from ``(lat, lon)`` to the
            window's start (clamped to ``>= 0``).
        d_end_nm: Along-track distance to the window's end (clamped to
            ``>= d_start_nm``).

    Returns:
        At least 2 ``(lat, lon)`` points, in direction-of-travel order.
    """
    d_start_nm = max(0.0, d_start_nm)
    d_end_nm = max(d_start_nm, d_end_nm)

    if not route_waypoints:
        # No route known: pure dead reckoning at a fixed heading. Each
        # boundary point is computed directly via the true great-circle
        # formula (`move_position`) rather than linearly interpolating
        # along one very long synthetic "leg" spanning the whole
        # window -- that would introduce real curvature error exactly
        # because there's no intermediate waypoint to keep each
        # interpolated segment short (unlike the real-route case below,
        # where individual legs are naturally bounded by real
        # waypoints, keeping this same approximation negligible).
        start_lat, start_lon = move_position(lat, lon, heading_deg, d_start_nm)
        end_lat, end_lon = move_position(lat, lon, heading_deg, d_end_nm)
        return [(start_lat, start_lon), (end_lat, end_lon)]

    # Cumulative-distance vertex list, starting from the current
    # position (distance 0) -- `route_waypoints` itself never includes
    # the current position (see `StateReader.get_route`'s own
    # docstring), so it's prepended here.
    vertices: List[Tuple[float, float, float]] = [(0.0, lat, lon)]
    prev_lat, prev_lon = lat, lon
    cumulative_nm = 0.0
    for wp_lat, wp_lon in route_waypoints[:_MAX_ROUTE_LEGS]:
        cumulative_nm += haversine_distance_nm(prev_lat, prev_lon, wp_lat, wp_lon)
        vertices.append((cumulative_nm, wp_lat, wp_lon))
        prev_lat, prev_lon = wp_lat, wp_lon

    total_nm = vertices[-1][0]
    d_start_nm = min(d_start_nm, total_nm)
    d_end_nm = min(d_end_nm, total_nm)

    def _point_at(target_nm: float) -> Tuple[float, float]:
        target_nm = max(0.0, min(total_nm, target_nm))
        for i in range(1, len(vertices)):
            d0, lat0, lon0 = vertices[i - 1]
            d1, lat1, lon1 = vertices[i]
            if target_nm <= d1 + 1e-9:
                if d1 - d0 < 1e-9:
                    return lat1, lon1
                frac = (target_nm - d0) / (d1 - d0)
                # Linear lat/lon interpolation: fine at the local
                # (single-leg) scale this is used at, same
                # approximation the rest of ASTRA's geometry already
                # makes (e.g. `move_position`'s own flat-Earth regime).
                return lat0 + (lat1 - lat0) * frac, lon0 + (lon1 - lon0) * frac
        return vertices[-1][1], vertices[-1][2]

    points = [_point_at(d_start_nm)]
    for cumulative_nm, wp_lat, wp_lon in vertices:
        if d_start_nm < cumulative_nm < d_end_nm:
            points.append((wp_lat, wp_lon))
    points.append(_point_at(d_end_nm))
    return points


def compute_hotspot_box(
    track: FourDArhac,
    snapshot: TrafficSnapshot,
    routes: dict,
    config: ASTRAConfig,
) -> Optional[HotspotBox]:
    """Compute one track's static hotspot shape, anchored on predicted loss of separation.

    Args:
        track: An open track (member aircraft are read from it; its
            own forecast fields -- complexity/peak/onset/dissipation --
            are not used for the geometry itself any more, only
            ``peak_complexity`` for display colour).
        snapshot: This cycle's observed ``TrafficSnapshot``.
        routes: ``CycleResult.routes`` -- ``{callsign: [(lat, lon), ...]}``
            each in-snapshot aircraft's own known remaining waypoints,
            or an empty dict if no route provider is configured.
        config: Shared configuration -- read for the separation minima/
            buffer thresholds and sampling resolution (see this
            module's own docstring above).

    Returns:
        A ``HotspotBox``, or ``None`` if the track has fewer than 2
        member aircraft present in the current snapshot, or no pair
        among them ever actually violates real separation minima
        within ``config.max_prediction_horizon_min``.
    """
    now_ac = {ac.callsign: ac for ac in snapshot.as_list()}
    members_present = sorted(cs for cs in track.member_aircraft if cs in now_ac)
    if len(members_present) < 2:
        return None  # Need a pair to even ask "will they lose separation?".

    conflict = _overall_conflict_window(members_present, now_ac, routes, config)
    if conflict is None:
        return None  # No pair is ever actually predicted to lose separation.
    t_start_s, t_end_s, left_cs, right_cs = conflict
    now_s = snapshot.timestamp_s
    start_s, end_s = now_s + t_start_s, now_s + t_end_s

    # Reference axis: the conflicting pair's own current headings.
    # Used only to (a) decide which of the two reads as "left"/"right"
    # for a consistent polygon winding order, evaluated at their
    # current position, and (b) pad a genuinely degenerate (zero-length
    # window) case, both below. Deliberately NOT used to project an
    # entire route's worth of points into one fixed rotated frame -- a
    # route that actually turns (e.g. joining a different airway) can
    # end up moving mostly *perpendicular* to this single fixed axis
    # after the turn, which would corrupt a whole-route projection
    # built against it. The normal-case polygon below uses each
    # route's own raw (lat, lon) points directly instead, sidestepping
    # that entirely.
    axis_bearing_deg = _circular_mean_bearing_deg([now_ac[left_cs].heading_deg, now_ac[right_cs].heading_deg])
    axis_rad = math.radians(axis_bearing_deg)
    forward = (math.sin(axis_rad), math.cos(axis_rad))  # (East, North) unit vector
    across = (math.cos(axis_rad), -math.sin(axis_rad))  # cross-track unit vector

    origin_lat = (now_ac[left_cs].lat + now_ac[right_cs].lat) / 2.0
    origin_lon = (now_ac[left_cs].lon + now_ac[right_cs].lon) / 2.0

    def project(lat: float, lon: float) -> Tuple[float, float]:
        x_nm, y_nm = local_tangent_plane_nm(origin_lat, origin_lon, lat, lon)
        return x_nm * forward[0] + y_nm * forward[1], x_nm * across[0] + y_nm * across[1]

    def unproject(along: float, cross: float) -> Tuple[float, float]:
        x_nm = along * forward[0] + cross * across[0]
        y_nm = along * forward[1] + cross * across[1]
        return latlon_from_tangent_plane_nm(origin_lat, origin_lon, x_nm, y_nm)

    # Order left/right by current cross-track sign, so the polygon
    # winds consistently (left forward, right backward) regardless of
    # which of the pair `_overall_conflict_window` happened to return
    # first.
    cross_a = project(now_ac[left_cs].lat, now_ac[left_cs].lon)[1]
    cross_b = project(now_ac[right_cs].lat, now_ac[right_cs].lon)[1]
    if cross_a > cross_b:
        left_cs, right_cs = right_cs, left_cs
        cross_a, cross_b = cross_b, cross_a
    same_track = abs(cross_b - cross_a) < _MIN_CORRIDOR_SEPARATION_NM

    if abs(end_s - start_s) < 1e-6:
        # Genuinely zero-length window (both bounds resolved to the
        # same sample -- the sampling step in `_pairwise_conflict_window`
        # can occasionally land the whole buffer run on a single
        # instant) -- there is no along-route extent to draw at all,
        # only a footprint at that instant. Build a small synthetic
        # rectangle around each aircraft's own position at that moment
        # instead (this is the one place projection onto the fixed
        # axis is safe: exactly one point per aircraft, so there is no
        # "route bends relative to the axis" concern).
        def _instant_position(cs: str) -> Tuple[float, float]:
            ac = now_ac[cs]
            d_nm = ac.ground_speed_kt * max(0.0, start_s - now_s) / 3600.0
            return _route_window_polyline(ac.lat, ac.lon, ac.heading_deg, routes.get(cs), d_nm, d_nm)[0]

        left_along, left_cross = project(*_instant_position(left_cs))
        right_along, right_cross = project(*_instant_position(right_cs))
        if same_track:
            center_cross = (left_cross + right_cross) / 2.0
            left_cross = center_cross - _SINGLE_AIRCRAFT_HALF_WIDTH_NM
            right_cross = center_cross + _SINGLE_AIRCRAFT_HALF_WIDTH_NM
        polygon = [
            unproject(left_along - _MIN_DEGENERATE_HALF_LENGTH_NM, left_cross),
            unproject(left_along + _MIN_DEGENERATE_HALF_LENGTH_NM, left_cross),
            unproject(right_along + _MIN_DEGENERATE_HALF_LENGTH_NM, right_cross),
            unproject(right_along - _MIN_DEGENERATE_HALF_LENGTH_NM, right_cross),
        ]
        return HotspotBox(
            arhac_id=track.arhac_id,
            start_time_s=start_s,
            end_time_s=end_s,
            polygon=polygon,
            left_callsign=left_cs,
            right_callsign=right_cs,
            member_callsigns=frozenset(members_present),
            peak_complexity=track.peak_complexity,
        )

    def _route_edge(cs: str) -> List[Tuple[float, float]]:
        """This aircraft's own route/trajectory polyline across the
        window, in raw ``(lat, lon)`` -- the actual shape to draw,
        with no projection round-trip and therefore no distortion from
        however sharply the route bends."""
        ac = now_ac[cs]
        d_start_nm = ac.ground_speed_kt * max(0.0, start_s - now_s) / 3600.0
        d_end_nm = ac.ground_speed_kt * max(0.0, end_s - now_s) / 3600.0
        return _route_window_polyline(ac.lat, ac.lon, ac.heading_deg, routes.get(cs), d_start_nm, d_end_nm)

    def _shift_cross(points: List[Tuple[float, float]], delta_nm: float) -> List[Tuple[float, float]]:
        """Offset a polyline perpendicular to the fixed axis by `delta_nm`
        (used only for the single-aircraft/same-track fallback corridor)."""
        shifted = []
        for lat, lon in points:
            along, cross = project(lat, lon)
            shifted.append(unproject(along, cross + delta_nm))
        return shifted

    left_edge = _route_edge(left_cs)
    if same_track:
        # The two conflicting aircraft turn out to be on (near-)the
        # same track (e.g. one following the other toward a shared
        # waypoint -- exactly the case explicitly flagged as worth
        # checking: two aircraft on the same track converging on a
        # shared point). There's no genuinely separated second route
        # to bound a corridor against -- draw a modest representative
        # corridor centered on the shared path instead of a literal
        # zero-width line.
        right_edge = _shift_cross(left_edge, _SINGLE_AIRCRAFT_HALF_WIDTH_NM)
        left_edge = _shift_cross(left_edge, -_SINGLE_AIRCRAFT_HALF_WIDTH_NM)
    else:
        right_edge = _route_edge(right_cs)

    # Ribbon polygon: left route forward, right route backward -- draws
    # exactly along however each outer route bends, strictly between
    # them (no padding past either).
    polygon = left_edge + list(reversed(right_edge))

    return HotspotBox(
        arhac_id=track.arhac_id,
        start_time_s=start_s,
        end_time_s=end_s,
        polygon=polygon,
        left_callsign=left_cs,
        right_callsign=right_cs,
        member_callsigns=frozenset(members_present),
        peak_complexity=track.peak_complexity,
    )
