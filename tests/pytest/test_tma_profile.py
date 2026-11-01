"""VVTS integration and shared procedure model regressions.

The assertions compare motion/geometry and API effects, not merely file counts.
"""
from dataclasses import replace
import json
import math
from types import SimpleNamespace

import pytest

from astra.airspace import configure_profile, load_profile, procedure_aircraft, profile_presets, geo_asset
from astra.utils.config import ASTRAConfig, SectorDefinition
from astra.interface.state_reader import StateReader
from astra.interface.traffic_state import AircraftState, TrafficSnapshot
from astra.pipeline import Pipeline
from astra.trajectory.procedure import advance_procedure
from astra.trajectory.route_engine import RouteAwareTrajectoryEngine
from astra.hotspot.procedure_box import compute_procedure_box
from astra.utils.geodesy import haversine_distance_nm


@pytest.fixture
def tma_config():
    return configure_profile(ASTRAConfig(),'tsn_tma')


def reader_for(config,step=1):
    reader=StateReader.for_mock(config,sim_step_s=step);reader.connect()
    return reader


def state_from_spec(ac):
    return AircraftState(ac['callsign'],ac['lat'],ac['lon'],ac['altitude_ft'],ac['speed_kt'],ac['heading_deg'],0,ac['aircraft_type'],0)


def test_profile_coordinates_volume_and_legacy_defaults(tma_config):
    data=load_profile('tsn_tma')
    assert len(data['waypoint_data'])>149
    assert {'TSH','BAOMY','DONXO','TS426','TS424'} <= set(data['waypoint_data'])
    assert len(data['procedure_data'])==26
    assert data['waypoint_data']['SAPEN']['lat']==pytest.approx(11.02)
    assert data['waypoint_data']['SAPEN']['lon']==pytest.approx(106+11/60)
    assert tma_config.assessment_volume.radius_nm==40
    assert tma_config.assessment_volume.lower_altitude_ft==pytest.approx(600/.3048)
    default=ASTRAConfig()
    assert configure_profile(default,'hcm_fir') is default
    assert default.assessment_volume is None
    assert default.prediction_horizons_min==[5,10,15,20,30,40,50,60]


@pytest.mark.parametrize('procedure',list(load_profile('tsn_tma')['procedure_data']))
@pytest.mark.parametrize('runway',['25L','25R'])
def test_all_procedures_progress_continuously_and_handoff(tma_config,procedure,runway):
    required = '25L' if load_profile('tsn_tma')['procedure_data'][procedure]['kind'] == 'sid' else '25R'
    if runway != required:
        with pytest.raises(ValueError, match='requires 25L'):
            procedure_aircraft('tsn_tma',procedure,'CHECK',runway)
        return
    ac=procedure_aircraft('tsn_tma',procedure,'CHECK',runway)
    state=state_from_spec(ac);route=ac['route_waypoints'];profile=ac['procedure_profile']
    end=route[-1];end_alt=profile['legs'][-1]['target_altitude_ft']
    completed=False
    for _ in range(720):
        before=state
        step=advance_procedure(state,route,profile,10)
        state,route,profile=step.aircraft,step.remaining_route,step.profile
        assert 0<=state.altitude_ft<=20000
        # A waypoint may select a new nominal ground speed during this step.
        assert haversine_distance_nm(before.lat,before.lon,state.lat,state.lon)<=max(before.ground_speed_kt,state.ground_speed_kt)/360+1e-6
        # These are continuous paths, not instantaneous flight-level jumps.
        assert abs(state.altitude_ft-before.altitude_ft)<1000
        if step.completed:
            completed=True;break
    assert completed
    assert (state.lat,state.lon)==pytest.approx(end)
    assert state.altitude_ft==pytest.approx(end_alt)
    assert state.ground_speed_kt==0
    if profile['endpoint_behavior']=='landing':
        assert state.altitude_ft==pytest.approx(10/.3048)
    elif profile['direction']=='inbound':
        assert state.altitude_ft>2000


def test_shared_initial_segment_preserves_runway_and_arrival_direction():
    left=procedure_aircraft('tsn_tma','ANTRI2D','A','25L')
    with pytest.raises(ValueError, match='requires 25L'):
        procedure_aircraft('tsn_tma','ANTRI2D','B','25R')
    assert left['procedure_profile']['legs'][0]['fix']=='TS612'
    sid=procedure_aircraft('tsn_tma','SAPEN2D','C')
    star=procedure_aircraft('tsn_tma','SAPEN2H','D','25R')
    assert sid['procedure_profile']['direction']=='outbound'
    assert star['procedure_profile']['direction']=='inbound'
    assert star['procedure_profile']['legs'][-1]['fix']=='TD25R'
    assert sid['procedure_profile']['legs'][-1]['fix']=='SAPEN'
    assert len(star['route_waypoints'])>len(sid['route_waypoints'])


@pytest.mark.parametrize('procedure',['SAPEN2D','ANTRI2D','SAPEN2H','DALAP2H','DALAP2J','ANTRI2F','KADUM2G','BITIS2J'])
def test_predictor_agrees_with_actual_mock_over_many_ticks(tma_config,procedure):
    reader=reader_for(tma_config)
    reader.create_aircraft(**procedure_aircraft('tsn_tma',procedure,'PRED'))
    snapshot=reader.poll()
    predicted=RouteAwareTrajectoryEngine(tma_config,reader.get_route,reader.get_flight_profile).predict(snapshot)
    reader.step_simulation(180)
    actual=reader.poll().get('PRED');future=predicted.at(3).get('PRED')
    assert actual is not None and future is not None
    assert haversine_distance_nm(actual.lat,actual.lon,future.lat,future.lon)<1e-6
    assert actual.altitude_ft==pytest.approx(future.altitude_ft,abs=1e-5)


def test_terminal_handoff_does_not_create_stationary_future_aircraft(tma_config):
    reader=reader_for(tma_config)
    ac=procedure_aircraft('tsn_tma','SAPEN2D','END',start_index=1)
    ac['lat'],ac['lon']=ac['route_waypoints'][-1]
    ac['lon']-=.0001
    ac['altitude_ft']=ac['procedure_profile']['legs'][-1]['target_altitude_ft']
    reader.create_aircraft(**ac)
    snapshot=reader.poll()
    prediction=RouteAwareTrajectoryEngine(tma_config,reader.get_route,reader.get_flight_profile).predict(snapshot)
    assert all(p.get('END') is None for p in prediction.snapshots.values())
    reader.step_simulation(10)
    assert reader.list_aircraft()==[]


def synthetic_pair(config,altitude_gap):
    center=config.assessment_volume
    a=AircraftState('A',center.center_lat,center.center_lon,8000,180,90,0,'A320',0)
    b=replace(a,callsign='B',altitude_ft=8000+altitude_gap)
    route=[(a.lat,a.lon+.3)]
    profiles={ac.callsign:dict(flight_type='PROCEDURE',direction='outbound' if ac.callsign=='A' else 'inbound',
              legs=[dict(target_altitude_ft=ac.altitude_ft,max_ias_kt=None)]) for ac in [a,b]}
    snap=TrafficSnapshot(0,{'A':a,'B':b})
    track=SimpleNamespace(arhac_id='overlap',member_aircraft=frozenset(['A','B']),peak_complexity=75)
    return snap,track,{'A':route,'B':route},profiles


def test_sid_star_geographic_overlap_is_not_itself_a_conflict(tma_config):
    snap,track,routes,profiles=synthetic_pair(tma_config,2000)
    assert compute_procedure_box(track,snap,routes,profiles,tma_config) is None
    snap,track,routes,profiles=synthetic_pair(tma_config,0)
    box=compute_procedure_box(track,snap,routes,profiles,tma_config)
    assert box is not None and box.start_time_s==0
    assert box.member_callsigns==frozenset(['A','B'])


def test_volume_excludes_external_and_low_aircraft_but_retains_prediction(tma_config):
    reader=reader_for(tma_config)
    reader.create_aircraft(**procedure_aircraft('tsn_tma','ELSAS2H','OUT1'))
    reader.create_aircraft(**procedure_aircraft('tsn_tma','ELSAS2H','OUT2'))
    reader.create_aircraft(**procedure_aircraft('tsn_tma','SAPEN2D','LOW'))
    result=Pipeline(tma_config,reader.get_route,reader.get_flight_profile).run_cycle(reader.poll())
    assert result.airspace_metrics['simulated_aircraft']==3
    assert result.airspace_metrics['assessed_aircraft']==0
    assert result.regions_by_horizon[0]==[]
    assert result.prediction.at(1).get('OUT1') is not None
    assert any(result.regions_by_horizon[h] for h in [10,15])
    assert all(not rs.candidates and (rs.atfm_measures or rs.manual_intervention_required) for rs in result.resolution_sets)


def test_profile_geo_has_real_boundary_and_separate_routes():
    ring=geo_asset('tsn_tma','boundary.json')['features'][0]['geometry']['coordinates'][0]
    data=load_profile('tsn_tma');c=data['center']
    for lon,lat in ring:
        assert haversine_distance_nm(c['lat'],c['lon'],lat,lon)==pytest.approx(40,abs=1e-8)
    assert ring[0]==pytest.approx(ring[-1])
    assert len(geo_asset('tsn_tma','sids.json')['features'])==17
    assert len(geo_asset('tsn_tma','stars.json')['features'])==9


def test_dashboard_procedure_spawn_presets_and_save_roundtrip(tma_config,tmp_path):
    from astra.dashboard.legacy_flask_app import create_app
    from astra.dashboard.store import CycleStore
    reader=reader_for(tma_config)
    pipeline=Pipeline(tma_config,reader.get_route,reader.get_flight_profile)
    app=create_app(CycleStore(),tma_config,reader,str(tmp_path),pipeline)
    client=app.test_client()
    html = client.get('/').get_data(as_text=True)
    assert '/airspace/geo/manifest.json' in html
    assert 'Overall TMA' in html and 'max="15"' in html
    assert 'ASTRA_MAX_HORIZON_MIN = 15' in html
    assert 'sb-procedure-form' in client.get('/scenario').get_data(as_text=True)
    assert client.get('/airspace').json['id']=='tsn_tma'
    assert len(client.get('/scenario/presets').json['presets'])==8
    assert client.get('/airspace/geo/manifest.json').status_code==200
    assert client.get('/airspace/geo/missing.json').status_code==404
    airway=next(a for a in client.get('/scenario/airways').json['airways'] if a['designator']=='L637')
    assert 'ANHOA' in airway['waypoint_names'] and 'BITIS' in airway['waypoint_names']
    centre_body=dict(callsign='CENTRE',aircraft_type='A320',altitude_ft=18000,speed_kt=250,
                     airway_designator='L637',flight_type='OVERFLIGHT')
    assert client.post('/scenario/aircraft',json=centre_body).status_code==200
    assert reader.get_route('CENTRE')
    assert client.post('/scenario/aircraft',json={**centre_body,'callsign':'BADLAND','flight_type':'LANDING'}).status_code==409
    body=dict(callsign='NEW1',procedure_id='SAPEN2H',runway='25R')
    assert client.post('/scenario/procedure-aircraft',json=body).status_code==200
    assert client.post('/scenario/procedure-aircraft',json=body).status_code==409
    assert client.post('/scenario/procedure-aircraft',json={**body,'callsign':'OTHER','procedure_id':'bad'}).status_code==400
    reader.step_simulation(80)
    expected=reader.get_flight_profile('NEW1')
    assert client.post('/scenario/scenarios',json={'name':'roundtrip'}).status_code==200
    assert client.post('/scenario/control',json={'action':'reset'}).status_code==200
    assert client.post('/scenario/scenarios/roundtrip/load').status_code==200
    assert reader.get_flight_profile('NEW1')==expected
    saved_path=tmp_path/'roundtrip.json'
    saved=json.loads(saved_path.read_text())
    next(ac for ac in saved['aircraft'] if ac['callsign']=='NEW1')['procedure_profile']['runway']='25L'
    saved_path.write_text(json.dumps(saved))
    before=reader.list_aircraft()
    assert client.post('/scenario/scenarios/roundtrip/load').status_code==409
    assert reader.list_aircraft()==before

    assert client.patch('/scenario/aircraft/NEW1',json={'altitude_ft':0}).status_code==409
    assert client.post('/scenario/clearance',json={'callsign':'NEW1','clearance_type':'HEADING','value':90}).status_code==409
    for key in ('vvts_baseline','vvts_departure_surge','vvts_stand_metering',
                'vvts_ctot_sequence','vvts_mixed_flow'):
        assert client.post(f'/scenario/presets/{key}/load').status_code==200
        result=pipeline.run_cycle(reader.poll())
        assert result.airspace_metrics['profile']=='tsn_tma'


@pytest.mark.parametrize('preset',['vvts_mixed','vvts_arrivals','vvts_departures','vvts_centre_entry'])
def test_mixed_pipeline_runs_to_handoff_without_nonfinite_outputs(tma_config,preset):
    from astra.dashboard.serializers import serialize_cycle_result
    reader=reader_for(tma_config,60)
    for ac in profile_presets('tsn_tma')[preset]['aircraft']:reader.create_aircraft(**ac)
    pipeline=Pipeline(tma_config,reader.get_route,reader.get_flight_profile)
    reader.send_command('OP')
    counts=[]
    for i in range(60):
        snapshot=reader.poll();result=pipeline.run_cycle(snapshot)
        payload = serialize_cycle_result(result,tma_config)
        json.dumps(payload,allow_nan=False)
        assert all(t['sector_label'] in ('VVTS-40NM',None) for t in payload['tracks'])
        counts.append(len(snapshot))
        if not snapshot.aircraft:break
    assert counts[0]>0 and counts[-1]==0


def test_unknown_profile_and_runway_fail_explicitly(tma_config):
    with pytest.raises(ValueError):configure_profile(tma_config,'wrong')
    with pytest.raises(ValueError):procedure_aircraft('tsn_tma','SAPEN2D','X','07L')
    with pytest.raises(ValueError):procedure_aircraft('tsn_tma','SAPEN2D','X',start_index=-1)


def test_tma_websocket_publishes_procedure_profiles(tma_config,tmp_path):
    from fastapi.testclient import TestClient
    from astra.dashboard.server import create_realtime_app
    reader=reader_for(tma_config)
    for ac in profile_presets('tsn_tma')['vvts_mixed']['aircraft']:
        reader.create_aircraft(**ac)
    reader.send_command('OP')
    app=create_realtime_app(tma_config,reader=reader,hz=5.0,scenarios_dir=str(tmp_path))
    with TestClient(app) as client:
        with client.websocket_connect('/ws/telemetry') as ws:
            frame=ws.receive_json()
            if not frame['has_data']:frame=ws.receive_json()
            assert frame['has_data']
            assert frame['airspace_profile']=='tsn_tma'
            assert frame['cycle']['prediction']['horizons_min']==[i / 4 for i in range(1,61)]
            assert len(frame['cycle']['flight_profiles'])==5
            assert frame['cycle']['airspace_metrics']['profile']=='tsn_tma'
