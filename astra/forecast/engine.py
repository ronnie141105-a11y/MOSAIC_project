"""
4DARHAC forecast engine (Milestone 6).

``ForecastEngine`` estimates onset/peak/dissipation times and a composite
confidence for each open, confirmed-or-later ``FourDArhac`` track, using
this cycle's predicted-horizon ``ComplexityRegion``s already computed by
``ClusterEngine``/``ComplexityEngine`` but not previously consumed beyond
horizon 0. Stateless: unlike ``TrackerEngine``, it does not own tracks --
it is called once per track, per poll cycle, after
``TrackerEngine.update()`` has already run. See this module's own docstring above.
"""

import math
from typing import Dict, List

from astra.complexity.models import ComplexityRegion
from astra.forecast.horizon_series import build_series
from astra.forecast.projection import linear_crossing_time, predicted_peak
from astra.tracking.models import FourDArhac
from astra.utils.config import ASTRAConfig
from astra.utils.logger import get_logger

_LOG = get_logger(__name__)

#: Statuses eligible for forecasting. PROVISIONAL tracks *are* included
#: -- an onset time estimate for a hotspot that has not been observed at
#: all yet is the actual point (see astra.tracking.engine's module
#: docstring, "Provisional tracks"); they are just never resolvable
#: (astra.resolution.engine._RESOLVABLE_STATUSES excludes PROVISIONAL --
#: there is nothing concrete yet to issue a clearance against). CLOSED
#: tracks are no longer being observed, so there is nothing left to
#: associate predicted horizons against.
_FORECASTABLE_STATUSES = frozenset(
    {"PROVISIONAL", "CONFIRMED", "GROWING", "PEAK", "DISSIPATING"}
)


class ForecastEngine:
    """Estimates onset/peak/dissipation times and confidence for tracks.

    Stateless after construction; safe to share one instance across the
    whole ASTRA process.

    Example::

        tracks = tracker.update(regions_by_horizon)
        forecast_engine.forecast_many(tracks, regions_by_horizon)
        for t in tracks:
            print(t.predicted_onset_s, t.confidence)
    """

    def __init__(self, config: ASTRAConfig) -> None:
        """Initialise from shared config (thresholds, decay constant)."""
        self._config = config
        _LOG.debug(
            "ForecastEngine initialised. onset=%.1f dissipation=%.1f "
            "min_matched_horizons=%d decay_s=%.0f",
            config.forecast_onset_threshold,
            config.forecast_dissipation_threshold,
            config.forecast_min_matched_horizons,
            config.forecast_confidence_decay_s,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def forecast(
        self, track: FourDArhac, regions_by_horizon: Dict[int, List[ComplexityRegion]]
    ) -> FourDArhac:
        """Populate one track's forecast fields in place, this poll cycle.

        Args:
            track: An open track from ``TrackerEngine`` (any status).
                Mutated in place if forecastable; returned unchanged
                otherwise.
            regions_by_horizon: This cycle's fresh ``ComplexityRegion``s,
                keyed by ``horizon_min``, exactly as passed to
                ``TrackerEngine.update()``.

        Returns:
            The same ``track``, for convenient chaining.
        """
        if track.status not in _FORECASTABLE_STATUSES or not (
            track.track or track.provisional_track
        ):
            return track

        track.forecast_urgency_rank = None
        track.predicted_peak_complexity = None
        # Repeated forecasts must not compound the previous forecast decay.
        detections = len(track.track or track.provisional_track)
        detection_ramp = min(1.0, detections / self._config.tracking_confirm_cycles)
        if not track.track:
            detection_ramp *= self._config.tracking_provisional_confidence_multiplier
        series, matched_count, total_horizons = build_series(
            track, regions_by_horizon, self._config.tracking_jaccard_threshold
        )
        horizon_coverage = matched_count / total_horizons if total_horizons else 0.0

        # "Already critical" is a fact about the anchor's own current
        # (real-or-provisional) complexity_score, independent of whether
        # we have enough matched predicted horizons to forecast onset/
        # peak/dissipation -- so it's set here, before the insufficient-
        # data early return, not folded into the onset-crossing branch
        # further down. See `_assign_urgency_rank` and
        # `ResolutionEngine._eligible` for why this matters: a hotspot
        # already above `forecast_onset_threshold` has no future onset
        # left to predict (`predicted_onset_s` correctly stays `None`
        # below), but it must not be treated as *less* urgent than one
        # still approaching threshold -- see this field's docstring on
        # `FourDArhac`.
        _, current_score_now = series[0]
        track.already_critical = current_score_now >= self._config.forecast_onset_threshold

        if matched_count == 0 or len(series) - 1 < self._config.forecast_min_matched_horizons:
            track.predicted_onset_s = None
            track.predicted_dissipation_s = None
            track.predicted_peak_time_s = None
            track.confidence = detection_ramp * horizon_coverage
            return track

        anchor_time_s, current_score = series[0]

        track.predicted_onset_s = None
        if current_score < self._config.forecast_onset_threshold:
            track.predicted_onset_s = linear_crossing_time(
                series, self._config.forecast_onset_threshold, rising=True
            )

        track.predicted_dissipation_s = None
        if current_score >= self._config.forecast_dissipation_threshold or track.predicted_onset_s is not None:
            decay_series = [p for p in series if track.predicted_onset_s is None or p[0] >= track.predicted_onset_s]
            track.predicted_dissipation_s = linear_crossing_time(
                decay_series, self._config.forecast_dissipation_threshold, rising=False
            )

        future_points = series[1:]
        peak = predicted_peak(future_points, -1.0)
        track.predicted_peak_time_s = None
        if peak is not None:
            # Refresh the future estimate without rewriting the observed peak.
            if peak[1] > 0:
                track.predicted_peak_time_s = peak[0]
                track.predicted_peak_complexity = min(100.0, peak[1])

        lead_time_s = max(0.0, (track.predicted_onset_s or track.predicted_peak_time_s or anchor_time_s) - anchor_time_s)
        decay = 1.0 - math.exp(-lead_time_s / self._config.forecast_confidence_decay_s)
        track.confidence = detection_ramp * horizon_coverage * (1.0 - decay)

        _LOG.debug(
            "Forecast %s: onset=%s dissipation=%s peak_time=%s confidence=%.2f "
            "(matched=%d/%d)",
            track.arhac_id,
            track.predicted_onset_s,
            track.predicted_dissipation_s,
            track.predicted_peak_time_s,
            track.confidence,
            matched_count,
            total_horizons,
        )
        return track

    def forecast_many(
        self,
        tracks: List[FourDArhac],
        regions_by_horizon: Dict[int, List[ComplexityRegion]],
    ) -> List[FourDArhac]:
        """Forecast every track in a list, then rank by forecast urgency.

        Args:
            tracks: Tracks to forecast (any status; non-forecastable ones
                pass through unchanged -- see ``forecast()``).
            regions_by_horizon: This cycle's fresh ``ComplexityRegion``s,
                keyed by ``horizon_min``.

        Returns:
            The same ``tracks`` list, each entry mutated in place.
        """
        for track in tracks:
            self.forecast(track, regions_by_horizon)
        self._assign_urgency_rank(tracks)
        return tracks

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _current_score(track: FourDArhac) -> float:
        """The anchor's own latest complexity_score (real if observed, else provisional)."""
        if track.track:
            return track.track[-1].complexity_score
        if track.provisional_track:
            return track.provisional_track[-1].complexity_score
        return 0.0

    @classmethod
    def _assign_urgency_rank(cls, tracks: List[FourDArhac]) -> None:
        """Rank tracks by urgency (1 = most urgent).

        Two tiers, most urgent first:

        1. ``already_critical`` tracks -- already above
           ``forecast_onset_threshold`` right now, so there is no future
           onset time left to sort by (see ``forecast``'s docstring).
           These are ranked *first*, by descending current
           ``complexity_score`` (most severe first) -- NOT left unranked.
           Previously these tracks kept ``forecast_urgency_rank = None``
           exactly like a genuinely-not-yet-forecastable track (too new,
           insufficient matched horizons), which meant the single most
           urgent situation ASTRA can describe -- a hotspot already
           happening -- sorted as *least* urgent in every consumer that
           orders by ``forecast_urgency_rank`` (e.g.
           ``ResolutionEngine.resolve_many``'s processing order and the
           dashboard's alert table), and was also excluded from
           resolution entirely by ``ResolutionEngine._eligible``
           requiring ``predicted_onset_s``.
        2. Tracks with a genuine future ``predicted_onset_s``, ranked by
           soonest onset -- unchanged from the original design.

        Tracks with neither (still not forecastable at all -- too new,
        insufficient matched horizons) keep ``forecast_urgency_rank =
        None``, exactly as before.
        """
        for t in tracks:
            t.forecast_urgency_rank = None
        active = [t for t in tracks if t.status in _FORECASTABLE_STATUSES]
        critical = [t for t in active if t.already_critical]
        critical.sort(key=lambda t: -cls._current_score(t))
        due = [t for t in active if t.predicted_onset_s is not None and not t.already_critical]
        due.sort(key=lambda t: t.predicted_onset_s)
        for rank, track in enumerate(critical + due, start=1):
            track.forecast_urgency_rank = rank
