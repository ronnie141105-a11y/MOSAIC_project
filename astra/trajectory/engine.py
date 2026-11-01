"""
Trajectory prediction engine.

The engine implements a deterministic, constant-velocity kinematic model:

    Horizontal  great-circle dead-reckoning at the aircraft's current
                ground_speed_kt and heading_deg.  Uses
                ``astra.utils.geodesy.move_position``, the same function
                that ``MockConnector.poll()`` uses — so the predicted
                positions are exactly consistent with what the mock
                connector would produce if the simulation ran forward by
                the same amount of time without any clearances.

    Vertical    linear extrapolation at the aircraft's current
                vertical_speed_fpm (feet per minute).

    Constant    heading, ground speed, and vertical speed are treated as
                constant throughout the prediction horizon.

Why constant velocity?
----------------------
For en-route cruise phases — the dominant scenario in ASTRA — aircraft
maintain constant heading, speed, and altitude for long stretches.  A
constant-velocity model is therefore both accurate and the correct
starting baseline before more complex models (wind-corrected, intent-
based) are introduced.  The thesis documents this explicitly as a
simplifying assumption and identifies acceleration and turning as future
work.

This also matches exactly the kinematic propagation used in
``MockConnector``, which means simulation outputs are mathematically
reproducible and directly verifiable: one TrajectoryEngine.predict() call
at horizon H minutes produces the same position as H*60 / sim_step_s
MockConnector poll() calls.

Reuse
-----
All infrastructure from Phase 1 is reused without modification:
- ``astra.interface.traffic_state.AircraftState`` — input and output type
- ``astra.interface.traffic_state.TrafficSnapshot``  — input type
- ``astra.utils.geodesy.move_position``  — horizontal displacement
- ``astra.utils.config.ASTRAConfig``     — horizon configuration
- ``astra.utils.logger``                 — logging
"""

from typing import Dict, List

from astra.interface.traffic_state import AircraftState, TrafficSnapshot
from astra.trajectory.models import PredictedSnapshot, PredictionResult
from astra.utils.config import ASTRAConfig
from astra.utils.geodesy import move_position
from astra.utils.logger import get_logger

_LOG = get_logger(__name__)


def prediction_horizons(config):
    """Retain requested horizons and fill terminal gaps with short samples."""
    horizons = set(config.prediction_horizons_min)
    if 'tma' in config.airspace_profile.lower():
        step = config.terminal_prediction_step_s
        horizons.update(i * step / 60 for i in range(1, int(config.max_prediction_horizon_min * 60 / step) + 1))
    return sorted(horizons)


class TrajectoryEngine:
    """Deterministic constant-velocity trajectory predictor.

    Accepts a ``TrafficSnapshot`` and returns a ``PredictionResult``
    containing one ``PredictedSnapshot`` per configured horizon.

    Thread safety
    -------------
    ``TrajectoryEngine`` is stateless after construction — ``predict()``
    reads only the snapshot it receives and the config passed at init.
    It is therefore safe to call from multiple threads simultaneously,
    or to share a single instance across the whole ASTRA process.

    Example usage::

        engine = TrajectoryEngine(config)
        result = engine.predict(reader.current())
        at_15 = result.at(15)
        for ac in at_15:
            print(f"{ac.callsign}: ({ac.lat:.4f}, {ac.lon:.4f}) FL{ac.altitude_ft/100:.0f}")
    """

    def __init__(self, config: ASTRAConfig) -> None:
        """Initialise the engine from the shared configuration.

        Args:
            config: Shared ASTRA configuration. Reads
                ``prediction_horizons_min`` (default [5, 10, 15, 30, 60])
                to know which horizons to compute.
        """
        self._config = config
        self._horizons = prediction_horizons(config)
        _LOG.debug(
            "TrajectoryEngine initialised. Horizons: %s min", self._horizons
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def horizons_min(self) -> List[int]:
        """Sorted list of prediction horizons in minutes.

        Returns:
            A copy of the configured horizon list (sorted ascending).
        """
        return list(self._horizons)

    def predict(self, snapshot: TrafficSnapshot) -> PredictionResult:
        """Generate trajectory predictions for all configured horizons.

        Applies constant-velocity kinematics independently to every
        aircraft in ``snapshot``, producing one ``PredictedSnapshot``
        per horizon.

        If ``snapshot`` contains no aircraft, an empty ``PredictionResult``
        is returned — one ``PredictedSnapshot`` per horizon, each with an
        empty aircraft dict.

        Args:
            snapshot: Current observed traffic state from
                ``StateReader.current()`` or ``StateReader.poll()``.

        Returns:
            A ``PredictionResult`` containing one ``PredictedSnapshot``
            per configured horizon, ordered by ascending horizon value.
        """
        snapshots: Dict[int, PredictedSnapshot] = {}
        for h_min in self._horizons:
            snapshots[h_min] = self._predict_at_horizon(snapshot, h_min)

        result = PredictionResult(
            source_time_s=snapshot.timestamp_s,
            aircraft_count=len(snapshot),
            horizons_min=tuple(self._horizons),
            snapshots=snapshots,
        )
        _LOG.debug(
            "Prediction complete: %d aircraft × %d horizons from t=%.1f s",
            len(snapshot),
            len(self._horizons),
            snapshot.timestamp_s,
        )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _predict_at_horizon(
        self, snapshot: TrafficSnapshot, horizon_min: int
    ) -> PredictedSnapshot:
        """Predict all aircraft states at a single time horizon.

        Args:
            snapshot:    Source traffic state.
            horizon_min: Time horizon in minutes.

        Returns:
            A ``PredictedSnapshot`` containing one predicted
            ``AircraftState`` per aircraft in ``snapshot``.
        """
        dt_s = horizon_min * 60.0
        predicted_time_s = snapshot.timestamp_s + dt_s

        aircraft: Dict[str, AircraftState] = {}
        for ac in snapshot:
            predicted_ac = self._predict_aircraft(ac, dt_s, predicted_time_s)
            aircraft[predicted_ac.callsign] = predicted_ac

        return PredictedSnapshot(
            horizon_min=horizon_min,
            source_time_s=snapshot.timestamp_s,
            predicted_time_s=predicted_time_s,
            aircraft=aircraft,
        )

    def _predict_aircraft(
        self,
        ac: AircraftState,
        dt_s: float,
        predicted_time_s: float,
    ) -> AircraftState:
        """Apply constant-velocity kinematics to one aircraft.

        Thin wrapper around the module-level ``predict_constant_velocity``
        (kept as a method for backward-compatible call sites); see that
        function's docstring for the kinematics themselves.

        Args:
            ac:                Current observed aircraft state.
            dt_s:              Prediction horizon in seconds.
            predicted_time_s:  Simulation timestamp for the predicted state.

        Returns:
            A new ``AircraftState`` (frozen) representing the aircraft's
            predicted position and altitude at ``predicted_time_s``.
        """
        return predict_constant_velocity(ac, dt_s, predicted_time_s)


def predict_constant_velocity(
    ac: AircraftState, dt_s: float, predicted_time_s: float
) -> AircraftState:
    """Apply constant-velocity kinematics to one aircraft.

    Horizontal displacement uses great-circle dead-reckoning:
        distance_nm = ground_speed_kt x (dt_s / 3600)
        (lat, lon) = move_position(lat, lon, heading_deg, distance_nm)

    Vertical displacement uses linear extrapolation:
        delta_alt_ft = vertical_speed_fpm x (dt_s / 60)

    Bug fix (visual-spec update, 2026-07): a descending aircraft with no
    known route (this is the *only* model used for it in that case --
    ``RouteAwareTrajectoryEngine`` falls back to exactly this function
    whenever ``route_provider`` has no route for a given callsign) used
    to have its altitude clamped to 0 at the ground while its lat/lon
    kept advancing at full cruise ground speed for the *entire*
    ``dt_s``, regardless of how much of that time was actually still
    airborne. That produced a predicted position that had "landed" in
    altitude only -- still sliding forward in a straight line at
    (typically) 250+ kt indefinitely, which is exactly why a landing
    aircraft could look like it was never actually detected as landing
    on the time-scrubber: at a horizon past touchdown, its predicted
    marker sat wherever cruise speed had carried it since, not at (or
    near) the ground position it actually reached.

    This now finds the time it would actually take to reach 0 ft
    (``time_to_ground_s``, only when ``vertical_speed_fpm`` is
    descending) and caps horizontal motion there too: once grounded,
    the predicted position freezes at the point it actually reached the
    ground, altitude stays at 0, and both ``vertical_speed_fpm`` and
    ``ground_speed_kt`` report 0 (an aircraft sitting on the ground,
    not one still cruising through it). Still exactly the same output
    as before for the overwhelmingly common case this was originally
    documented against -- level or climbing aircraft, or a descent that
    doesn't reach 0 ft within the horizon -- only the previously-wrong
    "already below ground" case changes.

    All state fields not directly affected by kinematics (callsign,
    aircraft_type, heading_deg) are carried forward unchanged, reflecting
    the constant-velocity assumption.

    Module-level (not a method) so ``RouteAwareTrajectoryEngine`` can
    reuse this exact dead-reckoning fallback for aircraft it has no
    route for, without reaching into ``TrajectoryEngine`` internals --
    mirrors the same "shared pure function" pattern used for route
    following (``astra.trajectory.route_following.advance_along_route``).

    Args:
        ac:                Current observed aircraft state.
        dt_s:              Prediction horizon in seconds.
        predicted_time_s:  Simulation timestamp for the predicted state.

    Returns:
        A new ``AircraftState`` (frozen) representing the aircraft's
        predicted position and altitude at ``predicted_time_s``.
    """
    # Vertical: linear altitude extrapolation, but only for as long as
    # the aircraft would actually still be airborne. `time_to_ground_s`
    # is only meaningful (and only computed) while actually descending;
    # a level or climbing aircraft has nothing to cap.
    time_to_ground_s = None
    if ac.vertical_speed_fpm < 0.0:
        time_to_ground_s = ac.altitude_ft / (-ac.vertical_speed_fpm) * 60.0

    if time_to_ground_s is not None and time_to_ground_s <= dt_s:
        # Reaches the ground before this horizon -- freeze exactly
        # there: no further descent, no further horizontal travel past
        # the point it actually touched down at.
        effective_dt_s = max(0.0, time_to_ground_s)
        new_alt_ft = 0.0
        new_vs_fpm = 0.0
        new_gs_kt = 0.0
    else:
        effective_dt_s = dt_s
        new_alt_ft = max(0.0, ac.altitude_ft + ac.vertical_speed_fpm * (dt_s / 60.0))
        new_vs_fpm = ac.vertical_speed_fpm
        new_gs_kt = ac.ground_speed_kt

    # Horizontal: great-circle dead-reckoning, only for however long the
    # aircraft was actually still moving (see above).
    distance_nm = ac.ground_speed_kt * (effective_dt_s / 3600.0)
    new_lat, new_lon = move_position(ac.lat, ac.lon, ac.heading_deg, distance_nm)

    # Build predicted state (reuses AircraftState directly).
    return AircraftState(
        callsign=ac.callsign,
        lat=new_lat,
        lon=new_lon,
        altitude_ft=new_alt_ft,
        ground_speed_kt=new_gs_kt,
        heading_deg=ac.heading_deg,  # constant
        vertical_speed_fpm=new_vs_fpm,
        aircraft_type=ac.aircraft_type,
        timestamp_s=predicted_time_s,
    )
