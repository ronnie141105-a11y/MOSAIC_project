"""Shared identity, route continuity and deterministic display handoff."""
from dataclasses import replace
import hashlib
import json
import pytest

from astra.airspace import configure_profile, procedure_aircraft
from astra.centre import connect_procedure, control_area, centre_point, distance_nm
from astra.dashboard.legacy_flask_app import create_app
from astra.dashboard.store import CycleStore
from astra.interface.state_reader import StateReader
from astra.trajectory.procedure import advance_procedure
from astra.interface.traffic_state import AircraftState
from astra.utils.config import ASTRAConfig
from astra.utils.geodesy import move_position, haversine_distance_nm
from astra.studies.case_replay import DEFAULT_ROOT


def runtime(tmp_path, step=20):
    config=configure_profile(ASTRAConfig(),'tsn_tma')
    reader=StateReader.for_mock(config,sim_step_s=step);reader.connect()
    app=create_app(CycleStore(),config,reader,scenarios_dir=str(tmp_path/'builder'))
    return reader,app,app.test_client()


def test_single_owner_and_outgoing_shadow_are_symmetric():
    for direction in ('inbound','outbound'):
        for d in (35,38,39.9,40.1,42,45,150):
            area=control_area(*move_position(*centre_point(),90,d),direction)
            assert area['owner']==('APPROACH' if d<40 else 'CENTRE')
            assert 0<=area['centre_opacity']<=1 and 0<=area['approach_opacity']<=1
            if direction=='inbound' and d<36:assert area['centre_opacity']==0
            if direction=='outbound' and d>44:assert area['approach_opacity']==0
    assert control_area(*centre_point(),'inbound','OVERFLIGHT')['owner']=='CENTRE'


@pytest.mark.parametrize('procedure',['BITIS2H','VICAL3H','DALAP2H','SAPEN2D','XOBAV2D','ANTRI2D'])
def test_connected_routes_preserve_terminal_legs_and_continue_to_fir(procedure):
    base=procedure_aircraft('tsn_tma',procedure,'LINK01')
    linked=connect_procedure(base,300,220)
    legs=linked['procedure_profile']['legs']
    assert len(legs)==len(linked['route_waypoints'])
    inbound=base['procedure_profile']['direction']=='inbound'
    if inbound:
        assert legs[-len(base['procedure_profile']['legs']):]==base['procedure_profile']['legs']
        assert distance_nm(linked['lat'],linked['lon'])>150
    else:
        assert legs[:len(base['procedure_profile']['legs'])]==base['procedure_profile']['legs']
        assert distance_nm(*linked['route_waypoints'][-1])>150
        assert linked['procedure_profile']['endpoint_behavior']=='fir_exit'
    ac=AircraftState('LINK01',linked['lat'],linked['lon'],linked['altitude_ft'],linked['speed_kt'],linked['heading_deg'],0,'A320',0)
    route=linked['route_waypoints'];profile=linked['procedure_profile'];owners=set()
    for _ in range(500):
        old=ac
        result=advance_procedure(ac,route,profile,20)
        ac,route,profile=result.aircraft,result.remaining_route,result.profile
        owners.add(control_area(ac.lat,ac.lon,profile['direction'])['owner'])
        assert abs(ac.altitude_ft-old.altitude_ft)<=2000*20/60+.01
        assert haversine_distance_nm(ac.lat,ac.lon,old.lat,old.lon)<=430*20/3600+.01
        if result.completed:break
    assert owners=={'CENTRE','APPROACH'}
    assert result.completed


def test_centre_pages_share_runtime_and_demo_has_both_directions(tmp_path):
    reader,app,client=runtime(tmp_path)
    for path in ('/centre','/','/airport','/control-room'):
        response=client.get(path);assert response.status_code==200,response.text
    centre=client.get('/centre').text
    assert 'Ho Chi Minh Centre' in centre and 'MOSAIC_CONTROL_VIEW = "centre"' in centre
    manifest=client.get('/centre/geo/manifest.json').json
    assert any(l['id']=='vvts_handoff' for l in manifest['layers'])
    assert not any(l['id']=='point_merge_arcs' for l in manifest['layers'])
    assert any(l['id']=='arrival_feeders' for l in manifest['layers'])
    assert any(l['id']=='transfer_waypoints' for l in manifest['layers'])
    assert any(l['id'].startswith('procedure_') for l in manifest['layers'])
    assert next(l for l in manifest['layers'] if l['id']=='airways')['style']['dash']==[5,5]
    assert client.post('/api/centre/demo').status_code==200
    aircraft=reader.list_aircraft()
    assert {a['callsign'] for a in aircraft}=={'CTR101','CTR102'}
    assert min(distance_nm(a['lat'],a['lon']) for a in aircraft)==pytest.approx(49,abs=.1)
    assert 'DEP101' in app.airport_integration.sim.aircraft
    reader.step_simulation(200)
    assert len({a['callsign'] for a in reader.list_aircraft()})==len(reader.list_aircraft())


def test_extended_replay_keeps_original_tracks_and_ga_data(tmp_path):
    reader,app,client=runtime(tmp_path)
    source=DEFAULT_ROOT/'nominal/tracks.csv'
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    response=client.post('/api/case-scenarios/load',json={'case_id':'nominal','enroute':True})
    assert response.status_code==200,response.json
    status=response.json['replay'];assert status['enroute'] and 0<status['study_offset_s']<=3600
    replay=reader._connector.case_replay
    assert status['total']==55 and len(replay.replay.dataset.points)==55
    assert any(control_area(a['lat'],a['lon'])['owner']=='CENTRE' for a in reader.list_aircraft())
    assert client.post('/api/centre/demo').status_code==409
    for cs,points in replay.replay.dataset.points.items():
        assert all(a.epoch_s<b.epoch_s for a,b in zip(points,points[1:]))
        assert all(abs(p.state.vertical_speed_fpm)<=2000.1 for p in points if p.state)
    replay.seek(4800)
    payload=client.get('/airport/state').json
    assert payload['replay_read_only'] and payload['sim_time_s']==4800
    assert hashlib.sha256(source.read_bytes()).hexdigest()==digest
    replay.seek(0)
    assert replay.status()['time_s']==0 and not reader.is_simulation_running()
    assert client.post('/api/case-scenarios/load',json={'case_id':'nominal','enroute':'yes'}).status_code==400
    assert client.post('/api/case-scenarios/load',json={'case_id':'nominal'}).json['replay']['study_offset_s']==0


def test_departure_keeps_one_live_record_after_crossing_40nm(tmp_path):
    reader,app,client=runtime(tmp_path)
    assert client.post('/api/centre/demo').status_code==200
    reader.set_speed_multiplier(1)
    identity=None;seen=set();previous=None
    for _ in range(250):
        reader.step_simulation()
        aircraft={a['callsign']:a for a in reader.list_aircraft()}
        if 'DEP101' not in aircraft:continue
        ac=aircraft['DEP101']
        record=reader._connector._aircraft['DEP101']
        if identity is None:identity=id(record)
        assert id(record)==identity
        if previous:assert haversine_distance_nm(ac['lat'],ac['lon'],previous['lat'],previous['lon'])<=430*20/3600+.1
        previous=ac
        seen.add(control_area(ac['lat'],ac['lon'],'outbound')['owner'])
        if distance_nm(ac['lat'],ac['lon'])>80:break
    assert seen=={'CENTRE','APPROACH'}
    milestones=app.airport_integration.milestones['DEP101']
    assert milestones['tma_handoff']<milestones['centre_handoff']
    assert 'sid_exit' in milestones
