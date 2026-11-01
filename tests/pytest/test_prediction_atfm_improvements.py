from dataclasses import replace
from types import SimpleNamespace
import math
import pytest

from astra.utils.config import ASTRAConfig
from astra.interface.traffic_state import AircraftState, TrafficSnapshot
from astra.trajectory.route_engine import RouteAwareTrajectoryEngine
from astra.trajectory.procedure import advance_procedure
from astra.hotspot.procedure_box import compute_procedure_box
from astra.resolution.atfm import plan_measures
from astra.forecast.engine import ForecastEngine
from astra.forecast.horizon_series import build_series
from astra.pipeline import Pipeline
from tests.test_forecast import _track, _region


def ac(cs, lat=0, lon=0, heading=90, altitude=5000):
    return AircraftState(cs, lat, lon, altitude, 240, heading, 0, 'A320', 0)


def profile(direction='inbound'):
    return dict(flight_type='PROCEDURE', direction=direction,
                legs=[dict(fix='MERGE', target_altitude_ft=5000, nominal_speed_kt=240)])


def test_incremental_prediction_matches_direct_route_turn_and_vertical_profile():
    a = ac('A')
    route = [(0, .03), (.03, .03), (.06, .05)]
    p = dict(flight_type='PROCEDURE', direction='inbound', legs=[
        dict(target_altitude_ft=4500, nominal_speed_kt=220),
        dict(target_altitude_ft=4000, nominal_speed_kt=200),
        dict(target_altitude_ft=3500, nominal_speed_kt=180)])
    cfg = ASTRAConfig(airspace_profile='test_tma', prediction_horizons_min=[1, 2], max_prediction_horizon_min=2)
    result = RouteAwareTrajectoryEngine(cfg, lambda _: route, lambda _: p).predict(TrafficSnapshot(0, {'A': a}))
    for h in result.horizon_list():
        direct = advance_procedure(a, route, p, h * 60)
        predicted = result.at(h).get('A')
        if direct.completed:
            assert predicted is None
        else:
            assert predicted.lat == pytest.approx(direct.aircraft.lat, abs=1e-8)
            assert predicted.altitude_ft == pytest.approx(direct.aircraft.altitude_ft, abs=1e-6)
    assert len(route) == 3 and len(p['legs']) == 3


def test_dense_detection_finds_crossing_between_minute_samples():
    # Opposing traffic cross at 30 s and are separated at 0 and 60 s.
    cfg = ASTRAConfig(airspace_profile='test_tma', prediction_horizons_min=[1], max_prediction_horizon_min=1,
                      separation_horizontal_nm=1, conflict_horizontal_min_nm=.5,
                      hotspot_horizontal_buffer_nm=1, tracking_provisional_min_complexity=0)
    a, b = ac('A', lon=-.0333), ac('B', lon=.0333, heading=270)
    result = Pipeline(cfg).run_cycle(TrafficSnapshot(0, {'A': a, 'B': b}))
    assert not result.regions_by_horizon[0] and not result.regions_by_horizon[1]
    assert result.regions_by_horizon[.5]
    assert result.hotspot_boxes


def test_polygon_starts_at_encounter_and_stops_at_recovery():
    cfg = ASTRAConfig(prediction_horizons_min=[2], max_prediction_horizon_min=2,
                      conflict_horizontal_min_nm=1, hotspot_horizontal_buffer_nm=1.5,
                      hotspot_conflict_sample_step_s=1)
    a, b = ac('A', lon=-.05), ac('B', lon=.05, heading=270)
    snap = TrafficSnapshot(0, {'A': a, 'B': b})
    track = SimpleNamespace(arhac_id='T', member_aircraft={'A','B'}, peak_complexity=80)
    box = compute_procedure_box(track, snap, {}, {}, cfg)
    assert 25 < box.start_time_s < 40
    assert 50 < box.end_time_s < 65
    assert len(box.polygon) > 4
    assert max(lon for _, lon in box.polygon) < .02
    assert compute_procedure_box(track, replace(snap, aircraft={'A': a, 'B': replace(b, altitude_ft=8000)}), {}, {}, cfg) is None


def test_atfm_schedule_accounts_for_nonmember_traffic_and_flags_excess_delay():
    snap = TrafficSnapshot(0, {cs: ac(cs) for cs in ['A','B','C']})
    track = SimpleNamespace(status='PROVISIONAL', member_aircraft={'A','C'})
    cfg = ASTRAConfig(atfm_spacing_s=90, atfm_max_delay_s=120)
    measures = plan_measures(track, snap, lambda _: [(0,.1)], lambda _: profile(), cfg)
    c = next(m for m in measures if m.get('target_callsign') == 'C')
    assert c['delay_s'] == pytest.approx(180)
    assert c['status'] == 'CAPACITY_REVIEW_REQUIRED'
    assert c['planning_only']
    assert measures[-1]['target_rate_per_hour'] == 40
    assert plan_measures(track, snap, None, None, cfg) == []


def test_departure_timing_is_coordination_not_airborne_ground_hold():
    snap = TrafficSnapshot(0, {cs: ac(cs) for cs in ['A','B']})
    track = SimpleNamespace(status='CONFIRMED', member_aircraft={'A','B'})
    measures = plan_measures(track, snap, lambda _: [(0,.1)], lambda _: profile('outbound'), ASTRAConfig())
    assert measures[0]['measure_type'] == 'DEPARTURE_RELEASE_COORDINATION'
    assert 'cannot receive a ground hold' in measures[0]['rationale']


def test_forecast_idempotent_refreshes_peak_and_uses_disappearance():
    track = _track('CONFIRMED', 40)
    engine = ForecastEngine(ASTRAConfig())
    regions = {1: [_region(['A1','A2'], 80, 60, horizon_min=1)], 2: []}
    engine.forecast(track, regions)
    confidence = track.confidence
    assert track.predicted_onset_s < 60 < track.predicted_dissipation_s < 120
    assert track.peak_complexity == 40
    engine.forecast(track, regions)
    assert track.confidence == confidence
    later = {1: [], 2: [_region(['A1','A2'], 60, 120, horizon_min=2)]}
    engine.forecast(track, later)
    assert track.predicted_peak_time_s == 120
    assert track.predicted_peak_complexity == 60


def test_provisional_series_has_no_duplicate_anchor_or_current_critical_label():
    track = _track('PROVISIONAL', 80)
    anchor = _region(['A1','A2'], 80, 60, horizon_min=1)
    track.track = []
    track.provisional_track = [anchor]
    regions = {1: [anchor], 2: []}
    series, _, _ = build_series(track, regions, .5)
    assert series == [(0,0), (60,80), (120,0)]
    ForecastEngine(ASTRAConfig()).forecast(track, regions)
    assert not track.already_critical
    assert 0 < track.predicted_onset_s < 60


@pytest.mark.parametrize('field', ['terminal_prediction_step_s','atfm_spacing_s','atfm_max_delay_s','hotspot_polygon_padding_nm'])
def test_new_parameters_reject_nonfinite_and_nonpositive(field):
    for value in [0, -1, math.nan, math.inf]:
        with pytest.raises(ValueError):
            ASTRAConfig(**{field: value})
