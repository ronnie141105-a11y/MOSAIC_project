"""Airport/TMA lifecycle tests with the real mock connector and AEON graph."""
import pytest

from astra.airspace import configure_profile
from astra.airspace import procedure_aircraft
from astra.airport.aircraft import Aircraft
from astra.airport.graph import KEY_NODES
from astra.airport.simulation import Simulation
from astra.airport.graph import AirportGraph
from astra.dashboard.legacy_flask_app import create_app
from astra.dashboard.store import CycleStore
from astra.interface.state_reader import StateReader
from astra.utils.config import ASTRAConfig


def test_converging_taxi_branches_clear_shared_intersection():
    import math
    from astra.airport.aircraft import AircraftState
    from astra.studies.operational_cases import airport_graph
    sim=Simulation(airport_graph());sim.running=True;sim.speed_factor=1
    routes={'DEP':['n220','n230','n253'],'ARR':['n155','n230','n235']}
    for cs,route in routes.items():
        ac=Aircraft(cs,'A320','dep' if cs=='DEP' else 'arr',route[0])
        sim.add_aircraft(ac);ac.route=route;ac.state=AircraftState.TAXIING
    minimum=float('inf')
    for _ in range(600):
        sim.tick(1)
        a,b=sim.aircraft.values()
        if not a.is_done() and not b.is_done():minimum=min(minimum,math.hypot(a.x-b.x,a.y-b.y))
        if sim.all_done():break
    assert sim.all_done(), 'Converging arrivals and departures must not mutually block the taxi junction'
    assert minimum>=29, 'The junction reservation must retain the taxi following buffer'


def test_ground_departure_handoff_and_reset():
    config = configure_profile(ASTRAConfig(), 'tsn_tma')
    reader = StateReader.for_mock(config, sim_step_s=1)
    reader.connect()
    app = create_app(CycleStore(), config, reader=reader)
    client = app.test_client()
    assert client.get('/airport').status_code == 200
    assert client.get('/airport/assets/tsn_labeled.svg').status_code == 200
    assert client.get('/dashboard/airport.js').status_code == 200
    layout = client.get('/airport/layout').get_json()
    assert layout['ok'] and layout['nodes'] and layout['paths']
    state = client.get('/airport/state').get_json()
    assert state['ok'] and state['stands'] and state['sids']
    stand = state['stands'][0]['id']
    sid = state['sids'][0]
    result = client.post('/airport/departures', json=dict(callsign='TST001', aircraft_type='A320',
        stand_id=stand, sid=sid, requested_fl=240, destination='VVNB', depart_route='SAPEN L637'))
    assert result.status_code == 200, result.get_json()
    assert result.get_json()['fpl']['requested_fl'] == 240
    assert not reader.list_aircraft()
    reader.step_simulation(800)
    ground = app.airport_integration.sim.aircraft['TST001']
    assert ground.state.name == 'HOLDING'
    assert client.post('/airport/clearance', json=dict(callsign='TST001', type='takeoff')).status_code == 200
    reader.step_simulation(300)
    assert any(a['callsign'] == 'TST001' for a in reader.list_aircraft())
    assert all(a['callsign'] != 'TST001' for a in client.get('/airport/state').get_json()['aircraft'])
    reader.reset_simulation()
    assert client.get('/airport/state').get_json()['aircraft'] == []


def test_parked_stand_aircraft_does_not_block_adjacent_taxi_lane():
    from astra.airport.aircraft import AircraftState as GroundState
    graph=AirportGraph('astra/airport/vvts_layout.json')
    sim=Simulation(graph)
    moving=Aircraft('TAXI1','A320','dep','n10')
    parked=Aircraft('STAND1','A320','dep','n11')
    sim.add_aircraft(moving);sim.add_aircraft(parked)
    assert sim.assign_departure_route('TAXI1')
    moving.state=GroundState.TAXIING
    next_node=graph.node(moving.route[1])
    dx,dy=next_node.x-moving.x,next_node.y-moving.y
    length=(dx*dx+dy*dy)**.5
    parked.x,parked.y=moving.x+dx/length*10,moving.y+dy/length*10
    assert not sim._should_hold(moving,moving.route[0],moving.route[1])
    parked.state=GroundState.TAXIING
    assert sim._should_hold(moving,moving.route[0],moving.route[1])


def test_tma_arrival_taxis_to_stand():
    config = configure_profile(ASTRAConfig(), 'tsn_tma')
    reader = StateReader.for_mock(config, sim_step_s=1)
    reader.connect()
    app = create_app(CycleStore(), config, reader=reader)
    spec = procedure_aircraft('tsn_tma', 'BITIS2H', 'ARR900', start_index=2)
    reader.create_aircraft(**spec)
    saw_approach = False
    for _ in range(1800):
        reader.step_simulation()
        state = app.airport_integration.state()
        saw_approach |= 'ARR900' in state['approaches']
        if 'ARR900' in app.airport_integration.sim.aircraft:
            break
    assert saw_approach
    assert 'ARR900' in app.airport_integration.sim.aircraft
    assert any(a['callsign'] == 'ARR900' for a in reader.list_aircraft())
    reader.step_simulation(10)
    ground_speed = app.airport_integration.sim.aircraft['ARR900'].current_speed_mps * 1.943844
    tma_speed = next(a['ground_speed_kt'] for a in reader.list_aircraft() if a['callsign'] == 'ARR900')
    assert tma_speed == pytest.approx(ground_speed, abs=0.1)
    assert 100 < tma_speed < 140
    reader.step_simulation(140)
    assert 'runway_exit' in app.airport_integration.milestones['ARR900']
    assert not any(a['callsign'] == 'ARR900' for a in reader.list_aircraft())
    reader.step_simulation(1200)
    arrival = app.airport_integration.sim.aircraft['ARR900']
    if arrival.state.name == 'HOLDING':
        app.airport_integration.clear_crossing('ARR900')
        reader.step_simulation(1200)
    assert arrival.state.name == 'ARRIVED'
    assert arrival.current_speed_mps == 0
    assert app.airport_integration.fpl['ARR900']['stand']


def test_linked_preset_and_ground_scenario_roundtrip(tmp_path):
    config = configure_profile(ASTRAConfig(), 'tsn_tma')
    reader = StateReader.for_mock(config, sim_step_s=1)
    reader.connect()
    app = create_app(CycleStore(), config, reader=reader, scenarios_dir=str(tmp_path))
    client = app.test_client()
    presets = client.get('/scenario/presets').get_json()['presets']
    assert {p['key'] for p in presets} == {
        'vvts_baseline', 'vvts_departure_surge', 'vvts_stand_metering',
        'vvts_ctot_sequence', 'vvts_mixed_flow',
        'vvts_weather_capacity', 'vvts_weather_recovery', 'vvts_tma_weather',
        'workbook_peak_50','workbook_low_20'}
    assert client.post('/scenario/presets/vvts_linked/load').status_code == 404
    assert client.post('/scenario/presets/vvts_baseline/load').status_code == 200
    before = client.get('/airport/state').get_json()
    assert before['fpl']['DEP901']['requested_fl'] == 240
    assert before['fpl']['ARR901']['origin'] == 'VVNB'
    assert before['fpl']['ARR901']['star'] == 'BITIS2H'
    assert any(a['callsign'] == 'DEP901' for a in before['aircraft'])
    assert any(a['callsign'] == 'ARR901' for a in reader.list_aircraft())
    assert client.post('/scenario/scenarios', json={'name': 'linked'}).status_code == 200
    assert client.post('/scenario/control', json={'action': 'reset'}).status_code == 200
    assert client.get('/airport/state').get_json()['aircraft'] == []
    assert client.post('/scenario/scenarios/linked/load').status_code == 200
    after = client.get('/airport/state').get_json()
    assert after['fpl']['DEP901'] == before['fpl']['DEP901']
    assert any(a['callsign'] == 'DEP901' for a in after['aircraft'])


def test_climb_remains_visible_and_arrival_appears_before_runway():
    config = configure_profile(ASTRAConfig(), 'tsn_tma')
    reader = StateReader.for_mock(config, sim_step_s=1)
    reader.connect()
    app = create_app(CycleStore(), config, reader=reader)
    airport = app.airport_integration
    airport.load_study_scenario('vvts_baseline')
    reader.step_simulation(110)
    state = airport.state()
    dep = next(a for a in state['aircraft'] if a['callsign'] == 'DEP901')
    assert dep['state'] == 'CLIMBING'
    assert 0 < dep['altitude_ft'] < 1500
    assert dep['x'] < airport.graph.node(KEY_NODES['RWY25L_END']).x
    reader.step_simulation(1190)
    state = airport.state()
    assert not any(a['callsign'] == 'DEP901' for a in state['aircraft'])
    assert state['milestones']['DEP901']['takeoff'] < state['milestones']['DEP901']['tma_handoff']
    assert state['milestones']['DEP901']['tma_handoff'] < state['milestones']['DEP901']['sid_exit']
    assert 0 < state['approaches']['ARR901']['distance_nm'] < 8
    reader.step_simulation(500)
    marks = airport.state()['milestones']['ARR901']
    assert marks['approach_visible'] < marks['touchdown'] < marks['runway_exit'] < marks['stand_arrival']


def test_new_study_scenarios_measure_metering_and_crossings():
    config = configure_profile(ASTRAConfig(), 'tsn_tma')
    reader = StateReader.for_mock(config, sim_step_s=1)
    reader.connect()
    app = create_app(CycleStore(), config, reader=reader)
    airport = app.airport_integration
    outcomes = {}
    for key in ('vvts_departure_surge', 'vvts_stand_metering'):
        airport.load_study_scenario(key)
        reader.step_simulation(850)
        marks = airport.milestones
        taxi_out = [m['takeoff'] - m['off_block'] for m in marks.values()]
        hold = sum(a.hold_s for a in airport.sim.aircraft.values())
        outcomes[key] = (sum(taxi_out) / len(taxi_out), hold, max(m['takeoff'] for m in marks.values()))
        assert len(taxi_out) == 5
    assert outcomes['vvts_stand_metering'][0] < outcomes['vvts_departure_surge'][0]
    assert outcomes['vvts_stand_metering'][1] < outcomes['vvts_departure_surge'][1]
    # The 120 s takeoff rule can dominate both release policies. Stand
    # metering may reduce taxi waiting without making the final takeoff later.
    assert outcomes['vvts_stand_metering'][2] >= outcomes['vvts_departure_surge'][2]

    airport.load_study_scenario('vvts_ctot_sequence')
    reader.step_simulation(850)
    for callsign, marks in airport.milestones.items():
        delta = marks['takeoff'] - airport.fpl[callsign]['ctot_s']
        assert 0 <= delta <= 5

    airport.load_study_scenario('vvts_mixed_flow')
    reader.step_simulation(2200)
    for callsign in ('ARR901', 'ARR902'):
        marks = airport.milestones[callsign]
        assert marks['touchdown'] < marks['runway_exit'] < marks['crossing_clearance']
        assert marks['crossing_clearance'] < marks['crossing_entry'] < marks['stand_arrival']
        assert airport.sim.aircraft[callsign].state.name == 'ARRIVED'


def test_airport_arrival_spawn_has_full_fpl():
    config = configure_profile(ASTRAConfig(), 'tsn_tma')
    reader = StateReader.for_mock(config, sim_step_s=1)
    reader.connect()
    app = create_app(CycleStore(), config, reader=reader)
    client = app.test_client()
    result = client.post('/airport/arrivals', json=dict(callsign='INB123', aircraft_type='A321',
        origin='VVNB', star='BITIS2H', requested_fl=220, arrival_route='L637 BITIS'))
    assert result.status_code == 200, result.get_json()
    assert result.get_json()['fpl']['requested_fl'] == 220
    assert any(a['callsign'] == 'INB123' for a in reader.list_aircraft())


def test_off_block_and_ctot_hold_departure():
    config = configure_profile(ASTRAConfig(), 'tsn_tma')
    reader = StateReader.for_mock(config, sim_step_s=1)
    reader.connect()
    app = create_app(CycleStore(), config, reader=reader)
    airport = app.airport_integration
    stand = min(airport.graph.stands(), key=lambda n:
        (n.x-airport.graph.node('n107').x)**2 + (n.y-airport.graph.node('n107').y)**2)
    airport.add_departure(callsign='SLOT1', aircraft_type='A320', stand_id=stand.id,
        sid='SAPEN2D', requested_fl=240, destination='VVNB',
        off_block_time_s=100, ctot_s=2000)
    airport.clear_takeoff('SLOT1')
    reader.step_simulation(90)
    assert airport.sim.aircraft['SLOT1'].state.name == 'PARKED'
    reader.step_simulation(700)
    assert airport.sim.aircraft['SLOT1'].state.name == 'LINING_UP'
    assert not airport.sim.aircraft['SLOT1'].takeoff_roll_started
    assert not reader.list_aircraft()
    reader.step_simulation(1450)
    assert any(a['callsign'] == 'SLOT1' for a in reader.list_aircraft()), (
        airport.sim.aircraft['SLOT1'].state, airport.departures['SLOT1'],
        airport.sim.aircraft['SLOT1'].seg_idx, airport.sim.aircraft['SLOT1'].route)


def test_arrival_requires_clearance_when_route_crosses_25l():
    graph = AirportGraph('astra/airport/vvts_layout.json')
    sim = Simulation(graph)
    sim.running = True
    sim.speed_factor = 1
    ac = Aircraft('CROSS1', 'A320', 'arr', 'n9')
    sim.add_aircraft(ac)
    ac.x, ac.y = graph.node(KEY_NODES['RWY25R_SPAWN']).x, graph.node(KEY_NODES['RWY25R_SPAWN']).y
    assert sim.assign_arrival_route('CROSS1', KEY_NODES['RWY25R_EXIT_P5'], 'n9')
    for _ in range(1200):
        sim.tick(1)
    assert ac.state.name == 'HOLDING'
    assert ac.route[ac.seg_idx + 1] in sim.rwy25l_nodes
    sim.grant_cross_clearance('CROSS1')
    for _ in range(1200):
        sim.tick(1)
    assert ac.state.name == 'ARRIVED'


def test_drag_reroute_stops_at_node_and_can_restore():
    config = configure_profile(ASTRAConfig(), 'tsn_tma')
    reader = StateReader.for_mock(config, sim_step_s=1)
    reader.connect()
    app = create_app(CycleStore(), config, reader=reader)
    client = app.test_client()
    airport = app.airport_integration
    stand = airport.graph.stands()[0]
    airport.add_departure(callsign='DRAG1', aircraft_type='A320', stand_id=stand.id,
        sid='SAPEN2D', requested_fl=240, destination='VVNB')
    original = airport.sim.aircraft['DRAG1'].route[:]
    target = original[1]
    response = client.post('/airport/reroute', json={'callsign': 'DRAG1', 'target_id': target})
    assert response.status_code == 200
    assert response.get_json()['route'][-1] == target
    reader.step_simulation(150)
    ac = airport.sim.aircraft['DRAG1']
    assert ac.state.name == 'HOLDING' and ac.route == []
    assert not reader.list_aircraft()
    assert client.post('/airport/restore-route', json={'callsign': 'DRAG1'}).status_code == 200
    assert ac.route[-1] == KEY_NODES['RWY25L_END']
    assert not ac.manual_route
