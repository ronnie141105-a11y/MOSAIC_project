"""Physical controls, combined gates, and origin dispatch integration."""
from copy import deepcopy
import json
import numpy as np
import pytest
from astra.studies.gate_flow import AIRPORTS,audit,programme,realize_rta,speed_spec,stretch_spec,level_cap_spec
from astra.studies.flow_routes import spec_trajectory
from astra.studies.workbook_cases import ROOT
from astra.utils.geodesy import haversine_distance_nm

@pytest.fixture(scope='module')
def nominal():
    return json.loads((ROOT/'workbook_low_20/manifest.json').read_text(encoding='utf-8'))

def test_signed_speed_rta_and_short_vector_keep_initial_state_and_rejoin(nominal):
    f=max((f for f in nominal['flights'] if f['direction']=='arrival' and not f.get('origin_pending')),key=lambda f:f['transfer_time_s'])
    spec=f['initial_airborne_spec'];base,gate=spec_trajectory(spec,1)
    for change,sign in ((-15,1),(10,-1)):
        controlled=speed_spec(spec,change);path,t=spec_trajectory(controlled,1)
        assert (t-gate)*sign>0
        assert path[0,1:5]==pytest.approx(base[0,1:5])
        assert haversine_distance_nm(*path[-1,1:3],*base[-1,1:3])<.2
    vector=stretch_spec(spec,12);p=vector['procedure_profile']
    assert 0<p['flow_vector_extra_nm']<=12.1 and p['flow_vector_offset_nm']<=8
    rejoin=p['flow_vector_rejoin'];legs=p['legs'];index=next(i for i,l in enumerate(legs) if l['fix']=='FLOW_VECTOR')
    assert legs[index+1]['fix']==rejoin
    assert vector['route_waypoints'][index+1:]==spec['route_waypoints'][index:]
    for delta in (-60,60):
        result=realize_rta(spec,delta)
        assert result is not None and abs(result['transfer_s']-gate-delta)<=15
        assert np.min(result['path'][:-1,4])>100  # final touchdown tick is ground
    assert realize_rta(spec,-100000) is None
    with pytest.raises(ValueError):speed_spec(spec,11)
    with pytest.raises(ValueError):stretch_spec(spec,13)

def test_level_cap_preserves_gate_terminal_path_and_route(nominal):
    f=next(f for f in nominal['flights'] if f.get('origin_pending') and f['adep']=='VVPK')
    spec=f['initial_airborne_spec'];capped=level_cap_spec(spec,18000)
    assert capped['route_waypoints']==spec['route_waypoints']
    gate=spec['procedure_profile']['approach_transfer_fix']
    original=spec['procedure_profile']['legs'];legs=capped['procedure_profile']['legs']
    split=next(i for i,l in enumerate(legs) if l['fix']==gate)
    assert max(l['target_altitude_ft'] for l in legs[:split])<=18000
    assert legs[split:]==original[split:]

def test_ac_and_baomy_share_minit_even_when_their_individual_streams_are_sparse():
    flights=[dict(callsign=cs,direction='arrival',route_family=family,adep='VVPK') for cs,family in [('A','W1_AC'),('B','PTH_BAOMY')]]
    paths={'A':np.array([[0,12,106,20000,300],[1000,13,106,20000,300]]),
           'B':np.array([[0,11,106,20000,300],[1000,12,106,20000,300]])}
    result=audit(flights,paths,{'A':dict(approach_handoff=200),'B':dict(approach_handoff=260)},programme(True))
    assert result['violating_pairs']==1
    assert {r['gate'] for r in result['events']}=={'AC','BAOMY'}
    assert result['violations'][0]['gap_s']==60

@pytest.mark.parametrize('case_id,total,regional', [('workbook_low_20',20,6),('workbook_peak_50',60,18)])
def test_native_case_dispatch_tracks_and_programme(case_id,total,regional):
    from astra.studies.vvts_cases import dataset_for_case
    manifest=json.loads((ROOT/case_id/'manifest.json').read_text(encoding='utf-8'));data=dataset_for_case(ROOT/case_id)
    assert manifest['counts']['total']==total and manifest['flow_audit']['violating_pairs']==0
    assert max(f['completed_s'] for f in manifest['flights'] if f['direction']=='departure')<=10800
    pending=[f for f in manifest['flights'] if f.get('origin_pending')]
    assert len(pending)==regional and {f['adep'] for f in pending}==set(AIRPORTS)-{'VVTS'}
    assert min(f['origin_requested_ctot_s'] for f in pending)==600
    assert max(f['origin_requested_ctot_s'] for f in pending)<=3000
    for f in pending:
        first=data.points[f['callsign']][0]
        start=__import__('datetime').datetime.fromisoformat(manifest['local_start']).timestamp()
        assert first.epoch_s-start==pytest.approx(f['origin_ctot_s'])
        assert f['origin_requested_ctot_s']<=f['origin_ctot_s']
        assert f['origin_name']==AIRPORTS[f['adep']]['name']
    for icao in set(AIRPORTS)-{'VVTS'}:
        times=[f['origin_ctot_s'] for f in sorted(pending,key=lambda f:f['origin_queue_rank']) if f['adep']==icao]
        assert all(b-a>=240 for a,b in zip(times,times[1:]))

def test_centre_board_and_builder_show_origin_schedules(tmp_path):
    from astra.airspace import configure_profile
    from astra.interface.state_reader import StateReader
    from astra.dashboard.legacy_flask_app import create_app
    from astra.dashboard.store import CycleStore
    from astra.utils.config import ASTRAConfig
    config=configure_profile(ASTRAConfig(),'tsn_tma');reader=StateReader.for_mock(config,sim_step_s=1);reader.connect()
    app=create_app(CycleStore(),config,reader,scenarios_dir=str(tmp_path/'builder'));client=app.test_client()
    assert client.post('/api/system-tests/load',json=dict(case_id='workbook_low_20')).status_code==200
    board=client.get('/api/centre/flow').json
    assert board['active'] and board['fixed_order']
    assert {g['id'] for g in board['gates']}=={'AC','BAOMY','PTH'}
    assert next(g for g in board['gates'] if g['id']=='PTH')['events']
    assert {a['icao'] for a in board['airports']}==set(AIRPORTS)
    for a in board['airports']:
        eligible=[r for r in a['departures'] if r['regional_surface_model'] or a['icao']=='VVTS']
        assert eligible
        assert all(r['tobt_s']<=r['ctot_s'] for r in eligible)
        if a['icao']!='VVTS':assert sum(r['regional_surface_model'] for r in eligible)==1
    plans=client.get('/scenario/state').json['flight_plans']
    assert len(plans)==20 and all(f['adep'] and f['origin_name'] for f in plans)
    assert len(board['arrival_events'])==14
    replay=reader._connector.case_replay
    assert replay.duration_s>0
    flight=next(f for f in replay.manifest['flights'] if f['direction']=='arrival')
    flight['flow_actions']=dict(rta_target_s=flight['transfer_time_s']+60,speed_change_pct=-2)
    updated=client.get('/api/centre/flow').json
    event=next(e for e in updated['arrival_events'] if e['callsign']==flight['callsign'])
    assert event['rta_s']==flight['transfer_time_s']+60 and event['actions']['speed_change_pct']==-2
    assert client.get('/case-scenarios/model-guide').status_code==200
    assert client.get('/case-scenarios/handout/summary').status_code==409
