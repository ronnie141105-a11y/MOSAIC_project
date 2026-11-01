"""Weather and reviewed ATFM actions must change shared simulation behavior."""
import pytest

from astra.airspace import configure_profile, procedure_aircraft
from astra.airport.aircraft import AircraftState
from astra.airport.weather import decode_metar, preset_weather
from astra.dashboard.legacy_flask_app import create_app
from astra.dashboard.store import CycleStore
from astra.interface.state_reader import StateReader
from astra.trajectory.procedure import advance_procedure


@pytest.fixture
def setup(config, tmp_path):
    config = configure_profile(config, 'tsn_tma')
    reader = StateReader.for_mock(config, sim_step_s=1)
    reader.connect()
    app = create_app(CycleStore(), config, reader=reader, scenarios_dir=str(tmp_path))
    return reader, app.airport_integration, app.test_client()


def apply(airport, kind, **kwargs):
    preview = airport.flow.review(dict(type=kind, reason='Test capacity coordination', duration_min=30,
                                       rate_per_hour=12, **kwargs))
    return airport.flow.apply(preview['token'])


def test_metar_decode_presets_and_bounds():
    for key in ('clear', 'rain', 'heavy_rain', 'thunderstorm', 'low_visibility', 'severe'):
        report = preset_weather(key, '070900Z')
        assert report['station'] == 'VVTS'
        assert report['source'] == 'SIMULATED'
        assert report['preset'] == key
    report = decode_metar('METAR VVTS 070930Z VRB03KT CAVOK M01/M03 Q1012=')
    assert report['visibility_m'] == 10000
    assert report['temperature_c'] == -1
    assert report['wind_direction_deg'] is None
    assert report['capacity_factor'] == 1
    report = decode_metar('VVTS 070900Z 24012MPS 2000 +RA BKN008 25/24 Q1006 RMK TS MOV E')
    assert report['preset'] == 'heavy_rain'
    assert report['ceiling_ft'] == 800
    assert report['wind_speed_kt'] == pytest.approx(23.3)
    for bad in ('VVNB 070000Z 25006KT CAVOK 30/24 Q1010', 'VVTS 079999Z 25006KT CAVOK 30/24 Q1010',
                'VVTS 070000Z 99906KT CAVOK 30/24 Q1010', 'VVTS 070000Z 25006KT 2SM 30/24 Q1010'):
        with pytest.raises(ValueError):
            decode_metar(bad)


def test_weather_capacity_and_taxi_motion(setup):
    reader, airport, client = setup
    positions = {}
    for key in ('clear', 'heavy_rain'):
        airport.load_study_scenario('vvts_departure_surge')
        airport.flow.set_weather(dict(preset=key))
        reader.step_simulation(10)
        ac = airport.sim.aircraft['DEP901']
        positions[key] = (ac.distance_svgu, ac.current_speed_mps)
    assert positions['heavy_rain'][0] < positions['clear'][0]
    assert positions['heavy_rain'][1] < positions['clear'][1]
    airport.load_study_scenario('vvts_weather_capacity')
    state = client.get('/api/operations/state').get_json()
    assert state['demand']['trigger'] == 'DEMAND_EXCEEDS_CAPACITY'
    assert state['capacity']['departures_per_hour'] == 24
    assert state['recommendation'] == 'departure_slots'


def test_ground_stop_overrides_clearance_and_expiry(setup):
    reader, airport, client = setup
    airport.load_study_scenario('vvts_departure_surge')
    review = client.post('/api/operations/review', json=dict(type='ground_stop', reason='Thunderstorm', duration_min=1))
    assert review.status_code == 200
    assert client.post('/api/operations/apply', json=dict(token=review.get_json()['token'])).status_code == 200
    reader.step_simulation(59)
    assert all(a.state == AircraftState.PARKED for a in airport.sim.aircraft.values())
    assert all(a.cleared_takeoff for a in airport.sim.aircraft.values())
    assert airport.flow.state()['metrics']['stand_hold_s'] == 59 * 5
    reader.step_simulation(2)
    assert airport.flow.program is None
    assert sum(a.state != AircraftState.PARKED for a in airport.sim.aircraft.values())==4
    reader.step_simulation(900)
    assert all('takeoff' in airport.milestones.get(a.callsign,{}) for a in airport.sim.aircraft.values())
    assert any(row['event'] == 'PROGRAM_EXPIRED' for row in airport.flow.history)


def test_stop_blocks_taxiing_departure_and_releases_on_cancel(setup):
    reader, airport, client = setup
    airport.load_study_scenario('vvts_departure_surge')
    reader.step_simulation(20)
    apply(airport, 'ground_stop')
    reader.step_simulation(300)
    assert not any('runway_entry' in m for m in airport.milestones.values())
    client.post('/api/operations/cancel', json={})
    reader.step_simulation(900)
    assert all('takeoff' in m for m in airport.milestones.values())


def test_ctot_stand_holds_and_enforced_interval(setup):
    reader, airport, client = setup
    airport.load_study_scenario('vvts_departure_surge')
    original = {cs: (ac.off_block_time_s, ac.ctot_s) for cs, ac in airport.sim.aircraft.items()}
    state = apply(airport, 'departure_slots')
    targets = [row['target_time_s'] for row in state['slots']]
    assert all(b - a >= 300 for a, b in zip(targets, targets[1:]))
    reader.step_simulation(30)
    assert sum(a.state == AircraftState.PARKED for a in airport.sim.aircraft.values()) >= 3
    reader.step_simulation(1700)
    entries = sorted(m['runway_entry'] for m in airport.milestones.values())
    assert len(entries) == 5
    assert all(b - a >= 300 for a, b in zip(entries, entries[1:]))
    airport.flow.cancel()
    assert all((ac.off_block_time_s, ac.ctot_s) == original[cs] for cs, ac in airport.sim.aircraft.items())
    assert all(ac.atfm_ctot_s == ac.atfm_off_block_s == 0 for ac in airport.sim.aircraft.values())


def test_minit_includes_new_departures(setup):
    reader, airport, client = setup
    airport.load_study_scenario('vvts_baseline')
    state = apply(airport, 'minit', minit_min=7)
    other_stand = next(n.id for n in airport.graph.stands() if n.id != airport.sim.aircraft['DEP901'].stand_id)
    airport.add_departure(callsign='NEW901', aircraft_type='A320', stand_id=other_stand,
                          sid='SAPEN2D', requested_fl=240, destination='VVNB')
    airport.clear_takeoff('NEW901')
    reader.step_simulation(900)
    entries = sorted(m['runway_entry'] for m in airport.milestones.values() if 'runway_entry' in m)
    assert len(entries) == 2
    assert entries[1] - entries[0] >= 420


def test_severe_weather_recovers_without_stopping_clock(setup):
    reader, airport, client = setup
    airport.load_study_scenario('vvts_weather_recovery')
    reader.step_simulation(299)
    assert reader.simulation_time_s() == 299
    assert all(a.state == AircraftState.PARKED for a in airport.sim.aircraft.values())
    reader.step_simulation(2)
    assert airport.flow.weather['preset'] == 'clear'
    assert sum(a.state == AircraftState.TAXIING for a in airport.sim.aircraft.values())==4
    assert sum(a.state == AircraftState.PARKED for a in airport.sim.aircraft.values())==1


def test_arrival_metering_moves_aircraft_and_is_reversible(setup):
    reader, airport, client = setup
    airport.connected_fir=False  # This test intentionally starts traffic inside the TMA.
    for cs in ('ARR101', 'ARR102', 'ARR103'):
        airport.add_arrival(callsign=cs, aircraft_type='A320', origin='VVNB', star='BITIS2H', requested_fl=240)
    state = apply(airport, 'arrival_metering')
    assert max(row['residual_delay_s'] for row in state['slots']) > 0
    factors = [reader.get_flight_profile(cs)['atfm_speed_factor'] for cs in ('ARR101', 'ARR102', 'ARR103')]
    assert min(factors) == .8
    before = {a['callsign']: (a['lat'], a['lon']) for a in reader.list_aircraft()}
    reader.step_simulation(15)
    after = {a['callsign']: a for a in reader.list_aircraft()}
    assert all((a['lat'], a['lon']) != before[cs] for cs, a in after.items())
    assert after['ARR101']['ground_speed_kt'] > after['ARR103']['ground_speed_kt'] >= 180
    airport.flow.cancel()
    assert all('atfm_speed_factor' not in reader.get_flight_profile(cs) for cs in after)
    reader.step_simulation(1)
    assert len({a['ground_speed_kt'] for a in reader.list_aircraft()}) == 1


def test_review_validation_and_stale_weather(setup):
    reader, airport, client = setup
    airport.load_study_scenario('vvts_baseline')
    assert client.post('/api/operations/apply', json={'token': 'missing'}).status_code == 400
    for payload in ([], {'type': 'unknown', 'reason': 'Test'}, {'type': 'ground_stop', 'reason': ''},
                    {'type': 'ground_stop', 'reason': 'Test', 'duration_min': True}):
        assert client.post('/api/operations/review', json=payload).status_code == 400
    before = airport.flow.weather.copy()
    assert client.post('/api/operations/weather', json={'preset': 'severe', 'duration_min': -1}).status_code == 400
    assert airport.flow.weather == before
    preview = airport.flow.review({'type': 'ground_stop', 'reason': 'Test'})
    airport.flow.set_weather({'preset': 'rain'})
    assert client.post('/api/operations/apply', json={'token': preview['token']}).status_code == 400


def test_shared_arrival_propagator_matches_expiry_and_leaves_approach_unchanged(setup):
    reader, airport, client = setup
    airport.add_arrival(callsign='ARR101', aircraft_type='A320', origin='VVNB', star='BITIS2H', requested_fl=240)
    snapshot = reader.poll()
    ac = snapshot.aircraft['ARR101']
    route = reader.get_route('ARR101')
    profile = reader.get_flight_profile('ARR101')
    profile.update(atfm_speed_factor=.8, atfm_until_s=5)
    combined = advance_procedure(ac, route, profile, 20)
    first = advance_procedure(ac, route, profile, 5)
    second = advance_procedure(first.aircraft, first.remaining_route, first.profile, 15)
    assert combined.aircraft.lat == pytest.approx(second.aircraft.lat)
    assert combined.aircraft.lon == pytest.approx(second.aircraft.lon)
    assert combined.aircraft.ground_speed_kt == second.aircraft.ground_speed_kt
    # Restrict the first leg to approach altitude; a flow factor must have no effect.
    profile['legs'][0]['target_altitude_ft'] = 2000
    profile['atfm_until_s'] = 100
    limited = advance_procedure(ac, route, profile, 1)
    profile.pop('atfm_speed_factor')
    original = advance_procedure(ac, route, profile, 1)
    assert limited.aircraft.ground_speed_kt == original.aircraft.ground_speed_kt


def test_weather_change_with_active_arrival_metering_handles_zero_capacity(setup):
    reader, airport, client = setup
    airport.add_arrival(callsign='ARR101', aircraft_type='A320', origin='VVNB', star='BITIS2H', requested_fl=240)
    apply(airport, 'arrival_metering')
    result = client.post('/api/operations/weather', json={'preset': 'severe'})
    assert result.status_code == 200
    assert result.json['program']['status'] == 'CAPACITY_REVIEW_REQUIRED'
    assert result.json['slots'][0]['residual_delay_s'] is None
    airport.flow.set_weather({'preset': 'clear'})
    assert airport.flow.program['status'] == 'ACTIVE'


def test_saved_weather_and_program_keep_simulation_time(setup):
    reader, airport, client = setup
    airport.load_study_scenario('vvts_weather_capacity')
    apply(airport, 'ground_stop')
    reader.step_simulation(40)
    assert client.post('/scenario/scenarios', json={'name': 'weather-program'}).status_code == 200
    airport.flow.cancel()
    airport.flow.set_weather({'preset': 'clear'})
    assert client.post('/scenario/scenarios/weather-program/load').status_code == 200
    assert reader.simulation_time_s() == airport.sim.time_s == 40
    assert airport.flow.weather['preset'] == 'heavy_rain'
    assert airport.flow.program['ends_at_s'] == 1800
    reader.step_simulation(30)
    assert all(a.state == AircraftState.PARKED for a in airport.sim.aircraft.values())
    reader.reset_simulation()
    assert airport.flow.weather['preset'] == 'clear'
    assert airport.flow.program is None


def test_controls_render_in_all_workspaces(setup):
    reader, airport, client = setup
    for url in ('/', '/airport', '/scenario'):
        response = client.get(url)
        assert response.status_code == 200
        assert b'id="operations-dialog"' in response.data
        assert b'operations.js' in response.data
        assert b'id="wx-metar"' in response.data
        assert b'Preview changes' in response.data
        assert b'Adjust rate &amp; reason' in response.data
    assert b'id="map-weather-canvas"' in client.get('/').data


def test_weather_changes_tma_arrival_and_departure_motion_and_eta(setup):
    reader, airport, client = setup
    airport.connected_fir=False  # Isolate local TMA weather rather than an upstream cruise leg.
    results = {}
    for key in ('clear', 'heavy_rain'):
        reader.reset_simulation()
        airport.add_arrival(callsign='ARR101', aircraft_type='A320', origin='VVNB', star='BITIS2H', requested_fl=240)
        reader.create_aircraft(**procedure_aircraft('tsn_tma', 'ANTRI2D', 'DEP101', start_index=1))
        airport.flow.set_weather({'preset': key})
        eta = airport.flow._arrival_rows()[0]['estimated_time_s']
        reader.step_simulation(30)
        results[key] = (eta, {a['callsign']:a for a in reader.list_aircraft()})
    assert results['heavy_rain'][0] > results['clear'][0]
    for cs in ('ARR101','DEP101'):
        nominal = results['clear'][1][cs]
        affected = results['heavy_rain'][1][cs]
        assert affected['ground_speed_kt'] != pytest.approx(nominal['ground_speed_kt'])
        assert (affected['lat'],affected['lon']) != (nominal['lat'],nominal['lon'])


def test_tma_weather_intent_reaches_new_flights_and_prediction(setup):
    reader, airport, client = setup
    airport.flow.set_weather({'preset':'thunderstorm','duration_min':1})
    airport.add_arrival(callsign='ARR101', aircraft_type='A320', origin='VVNB', star='BITIS2H', requested_fl=240)
    profile = reader.get_flight_profile('ARR101')
    assert profile['tma_weather']['preset'] == 'thunderstorm'
    snapshot = reader.poll()
    expected = advance_procedure(snapshot.aircraft['ARR101'],reader.get_route('ARR101'),profile,30)
    reader.step_simulation(30)
    actual = next(a for a in reader.list_aircraft() if a['callsign']=='ARR101')
    assert actual['lat'] == pytest.approx(expected.aircraft.lat, abs=.001)
    assert actual['lon'] == pytest.approx(expected.aircraft.lon, abs=.001)
    reader.step_simulation(31)
    assert reader.get_flight_profile('ARR101')['tma_weather']['preset'] == 'clear'
    assert client.get('/api/operations/state').json['tma_weather']['preset'] == 'clear'


def test_tma_weather_expiry_matches_split_propagation(setup):
    reader, airport, client = setup
    airport.add_arrival(callsign='ARR101', aircraft_type='A320', origin='VVNB', star='BITIS2H', requested_fl=240)
    airport.flow.set_weather({'preset':'strong_wind'})
    ac = reader.poll().aircraft['ARR101']
    route = reader.get_route('ARR101')
    profile = reader.get_flight_profile('ARR101')
    profile['tma_weather']['until_s'] = 5
    combined = advance_procedure(ac,route,profile,20)
    first = advance_procedure(ac,route,profile,5)
    second = advance_procedure(first.aircraft,first.remaining_route,first.profile,15)
    assert combined.aircraft.lat == pytest.approx(second.aircraft.lat)
    assert combined.aircraft.lon == pytest.approx(second.aircraft.lon)
    reader._connector.set_tma_weather(profile['tma_weather'])
    completion = advance_procedure(ac, route, profile, 86400)
    assert airport.flow._arrival_rows()[0]['estimated_time_s'] == pytest.approx(completion.elapsed_s)


def test_tma_thunderstorm_study_includes_airborne_traffic(setup):
    reader, airport, client = setup
    assert client.post('/scenario/presets/vvts_tma_weather/load').status_code == 200
    assert len(reader.list_aircraft()) == 3
    assert len(airport.sim.aircraft) == 2
    state = client.get('/api/operations/state').json
    assert state['weather']['preset'] == 'thunderstorm'
    assert state['tma_weather']['speed_factor'] == .85
    assert state['demand']['arrivals'] > 0
    assert state['recommendation'] == 'arrival_metering'
    baseline = reader.poll().aircraft['ARR901']
    expected = advance_procedure(baseline,reader.get_route('ARR901'),reader.get_flight_profile('ARR901'),1)
    regulated = apply(airport, 'arrival_metering')
    assert any(row['speed_factor'] < 1 for row in regulated['slots'])
    reader.step_simulation(1)
    actual = next(a for a in reader.list_aircraft() if a['callsign']=='ARR901')
    assert actual['ground_speed_kt'] < expected.aircraft.ground_speed_kt
