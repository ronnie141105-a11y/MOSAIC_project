"""Capacity, causal controls, complete paths and published full-route studies."""
from copy import deepcopy
import csv
import gzip
from datetime import datetime
from itertools import product
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import numpy as np
import pytest

from astra.optimization.full_route_cases import FullRouteEvaluator, saved_result, saved_folder, VERSION
from astra.optimization.teammate_ga import optimize
from astra.studies.workbook_cases import CASES, ROOT, json_bytes, csv_bytes
from astra.utils.geodesy import haversine_distance_nm


@pytest.fixture
def mini(tmp_path):
    case_id='workbook_low_20'
    folder=tmp_path/case_id
    folder.mkdir()
    manifest=json.loads((ROOT/case_id/'manifest.json').read_text(encoding='utf-8'))
    # Keep the legacy trajectory/domain regression fixture independent of the
    # new programme, which has its own fixed-order regional integration tests.
    manifest.pop('flow_programme',None)
    # A coincident arrival pair creates a conflict both outside and inside the
    # TMA. An independent departure keeps cross-type checks represented.
    arrival=next(f for f in manifest['flights'] if f['direction']=='arrival' and f.get('initial_stage',0)==0)
    departure=next(f for f in manifest['flights'] if f['direction']=='departure' and not f.get('startup_airborne_departure'))
    duplicate=deepcopy(arrival)
    duplicate.update(callsign='DUPARR',flight_id='mini:DUPARR')
    manifest['flights']=[arrival,duplicate,departure]
    manifest['counts']=dict(total=3,arrivals=2,departures=1)
    (folder/'manifest.json').write_bytes(json_bytes(manifest))
    for name in ('planning.csv','capacity.csv','fpl.csv'):
        shutil.copyfile(ROOT/case_id/name,folder/name)
    with (ROOT/case_id/'tracks.csv').open(encoding='utf-8',newline='') as stream:
        reader=csv.DictReader(stream)
        fields=reader.fieldnames
        tracks=[]
        for row in reader:
            if row['callsign'] in (arrival['callsign'],departure['callsign']):
                tracks.append(row)
                if row['callsign']==arrival['callsign']:
                    tracks.append(dict(row,callsign='DUPARR',flight_id='mini:DUPARR'))
    (folder/'tracks.csv').write_bytes(csv_bytes(fields,tracks))
    with gzip.open(ROOT/case_id/'ground_tracks.json.gz','rt') as stream:
        ground=json.load(stream)
    ground['milestones']['DUPARR']=deepcopy(ground['milestones'][arrival['callsign']])
    (folder/'ground_tracks.json.gz').write_bytes(gzip.compress(json.dumps(ground).encode(),mtime=0))
    return case_id,tmp_path,FullRouteEvaluator(case_id,tmp_path)


def test_case_design_has_shared_sector_limits_and_safe_native_baselines():
    excess={}
    settings=[]
    for case_id in CASES:
        manifest=json.loads((ROOT/case_id/'manifest.json').read_text(encoding='utf-8'))
        settings.append(manifest['study_settings'])
        with (ROOT/case_id/'capacity.csv').open(encoding='utf-8') as stream:
            capacity=list(csv.DictReader(stream))
        with (ROOT/case_id/'demand.csv').open(encoding='utf-8') as stream:
            demand=list(csv.DictReader(stream))
        total=len(demand)
        assert {c['basis'] for c in capacity}=={'simultaneous_airborne_in_sector'}
        assert {c['sector_id']:int(c['capacity_aircraft']) for c in capacity}=={s['id']:s['capacity'] for s in manifest['study_settings']['sectors']}
        assert total==manifest['counts']['total']
        excess[manifest['study_role']]=manifest['sector_occupancy']['total_excess_aircraft_seconds']
        assert manifest['separation_audit']['violating_pairs']==0
        assert manifest['surface_audit']['violating_pairs']==0
        assert all((datetime.fromisoformat(f['origin_takeoff_utc']) > datetime.fromisoformat(manifest['planning_utc']))
                   ==((f['direction']=='departure' and not f.get('startup_airborne_departure')) or f.get('origin_pending',False)) for f in manifest['flights'])
    assert settings[0]==settings[1]
    assert excess['nominal']==0 < excess['over_capacity']
    overload=json.loads((ROOT/'workbook_peak_50/manifest.json').read_text(encoding='utf-8'))
    assert overload['flow_audit']['violating_pairs']==0
    assert overload['counts']==dict(total=60,arrivals=42,departures=18)


def test_speed_control_changes_upstream_motion_and_not_origin_departure(mini):
    _,_,e=mini
    codes=[0]*e.n
    i=0
    speed=e.options.index((2,15))
    base=e.paths[i][0]
    slowed=e.paths[i][speed]
    assert slowed[0,0]==base[0,0]
    assert slowed[-1,0]>base[-1,0]+30
    assert np.min(slowed[:,6])>=-3500.001 and np.max(slowed[:,6])<=2000.001
    # The search propagates at 5 s and native airport execution at 1 s.
    # Both terminate at the same modelled threshold within one search tick.
    assert haversine_distance_nm(*slowed[-1,1:3],*base[-1,1:3])<140*5/3600
    now=base[0,0]+120
    location=lambda p:[np.interp(now,p[:,0],p[:,k]) for k in (1,2)]
    assert haversine_distance_nm(*location(base),*location(slowed))>1
    # After transfer, both trajectories follow the same terminal path shifted
    # by the additional travel time. No terminal speed reduction is applied.
    for relative_time in (120,300,600):
        b=e.transfers[i,0]+relative_time
        s=e.transfers[i,speed]+relative_time
        assert np.interp(b,base[:,0],base[:,4])==pytest.approx(np.interp(s,slowed[:,0],slowed[:,4]),abs=1)
    codes[i]=speed
    _,rows,_=e.evaluate(e.decode(codes))
    assert rows[i]['adjusted_origin_takeoff_utc']==e.metadata[i]['origin_takeoff_utc']
    assert rows[i]['speed_delay_min']>0 and rows[i]['ground_delay_min']==0


def test_gdp_moves_departure_and_admission_but_preserves_route(mini):
    _,_,e=mini
    code=e.options.index((1,40))
    a,b=e.paths[2][0],e.paths[2][code]
    assert np.allclose(a[:,1:],b[:,1:])
    assert np.allclose(b[:,0]-a[:,0],2400)
    plan=e.decode([0,0,code])
    _,rows,_=e.evaluate(plan)
    assert datetime.fromisoformat(rows[2]['adjusted_origin_takeoff_utc']).timestamp()-datetime.fromisoformat(e.metadata[2]['origin_takeoff_utc']).timestamp()==2400
    requested=datetime.fromisoformat(e.metadata[2]['requested_event_utc']).timestamp()
    assert rows[2]['ground_delay_min']==pytest.approx((e.start+e.events[2,code]-requested)/60)
    with pytest.raises(ValueError,match='unavailable'):e.encode([[1,5],[0,0],[0,0]])


def test_complete_path_conflicts_match_independent_spherical_distance(mini):
    _,_,e=mini
    assert e.base_pairs[0]  # coincident arrivals, including their Centre path
    plan=[[0,0]]*e.n
    metrics,_,audit=e.evaluate(plan,sample_s=1)
    assert metrics['centre_conflict_pairs']>0
    assert metrics['new_conflict_pairs']==0
    # Independent direct distance checks on the search grid for the first pair.
    a,b=e.paths[0][0],e.paths[1][0]
    times=np.arange(e.minimum,e.maximum+e.sample_s,e.sample_s)
    violations=[]
    for t in times:
        if not max(a[0,0],b[0,0])<=t<=min(a[-1,0],b[-1,0]):
            continue
        x,y=[[np.interp(t,p[:,0],p[:,k]) for k in (1,2,3)] for p in (a,b)]
        violations.append(haversine_distance_nm(x[0],x[1],y[0],y[1])<10 and abs(x[2]-y[2])<1000)
    assert e.tables[0,0,0]==any(violations)
    assert audit['scope'].startswith('Complete Centre')


def test_capacity_counts_only_the_occupied_sector_at_each_time(mini):
    _,_,e=mini
    e.occupancy_masks[:]=False
    e.s['sectors'][0]['capacity']=1
    e.s['sectors'][1]['capacity']=1
    e.occupancy_masks[0,0,:,0]=True
    e.occupancy_masks[0,1,:,0]=True
    e.occupancy_masks[1,2,:,0]=True
    state=e.state([0]*e.n)
    assert state['capacity_excess']==1
    assert state['occupancy_penalty']==pytest.approx(e.sample_s/60)
    # Same aircraft visible concurrently in different sectors do not combine.
    e.occupancy_masks[0,1,:,0]=False
    e.occupancy_masks[2,1,:,0]=True
    assert e.state([0]*e.n)['capacity_excess']==0


def test_runway_predictor_uses_6nm_at_roll_start_not_at_wheel_off(mini):
    _,_,e=mini
    e.runway_starts[:2,:]=250;e.runway_ends[:2,:]=312
    e.landing_releases[:2,:]=312;e.arrival_protection_starts[:2,:]=100
    e.runway_starts[2,:]=90;e.runway_ends[2,:]=145
    mixed=~e.arrival_pair & ~e.departure_pair
    assert not e.state([0]*e.n)['runway'][mixed].any()
    e.runway_starts[2,:]=100
    assert e.state([0]*e.n)['runway'][mixed].all()
    e.runway_starts[2,:]=90;e.runway_ends[2,:]=225
    assert e.state([0]*e.n)['runway'][mixed].all()
    e.runway_starts[2,:]=312;e.runway_ends[2,:]=367
    assert not e.state([0]*e.n)['runway'][mixed].any()


def test_mixed_terminal_spacing_matches_native_and_preserves_centre_rules(mini):
    from astra.centre import centre_point
    from astra.utils.geodesy import move_position
    from astra.studies.operational_cases import path_conflict
    from astra.studies.system_tests import pair_audit
    _,_,e=mini
    e.s['terminal_mixed_horizontal_nm']=5
    for outside,separation,conflict in [(False,5.5,False),(False,4.5,True),(True,5.5,True)]:
        origin=move_position(*centre_point(),0,50) if outside else centre_point()
        other=move_position(*origin,90,separation)
        paths=[np.asarray([[t,*point,1000,200,249,0] for t in (0,60)],dtype=float) for point in (origin,other)]
        assert path_conflict(*paths,terminal_mixed=True)==conflict
        assert bool(pair_audit(*paths,terminal_mixed=True)['violations'])==conflict
        a=e.sample([paths[0]],20,0,[0]);b=e.sample([paths[1]],20,2,[0])
        assert bool(e.conflicts(a,b)[0][0,0])==conflict
        # Same-direction traffic retains the original thresholds in Terminal.
        assert path_conflict(*paths)


def test_dynamic_action_domain_enumeration_bound_and_budgets(mini):
    _,_,e=mini
    assert (1,60) in e.options
    domains=[tuple(c for c in d if e.options[c][0]!=2) for d in e.domains]
    exact=min(e.objective(c) for c in product(*domains))
    plan,history,search=optimize(e,'ground',seed=11,population=40,generations=80,max_evaluations=6000)
    value=e.objective(e.encode(plan))
    # A stochastic heuristic need not find the enumerated global optimum.
    # It must return the scored incumbent, respect the lower bound and solve
    # this small instance's constraints without exceeding the stated budget.
    assert exact<=value<=e.objective([0]*e.n)
    assert value==history[-1]['objective']
    # Both duplicate arrivals are already airborne at the same location at t=0;
    # a departure ground hold cannot remove this unavoidable initial conflict.
    assert not e.evaluate(plan)[0]['feasible_sampled']
    assert search['total_evaluations']<=6000
    assert all(a['objective']>=b['objective'] for a,b in zip(history,history[1:]))
    with pytest.raises(ValueError,match='unavailable'):
        e.encode([[0,0],[0,0],[2,15]])
    with pytest.raises(ValueError,match='integers'):
        e.encode([[True,0],[0,0],[0,0]])


def test_already_airborne_origin_cannot_receive_gdp(mini):
    case_id,root,e=mini
    manifest=e.manifest
    manifest['flights'][0]['origin_takeoff_utc']='2026-10-20T20:00:00+00:00'
    (root/case_id/'manifest.json').write_bytes(json_bytes(manifest))
    changed=FullRouteEvaluator(case_id,root)
    assert all(changed.options[c][0]!=1 for c in changed.domains[0])
    with pytest.raises(ValueError,match='unavailable'):
        changed.encode([[1,5],[0,0],[0,0]])


def test_expanded_controls_and_relative_departure_checks_match_direct_grid(mini):
    case_id,root,_=mini
    e=FullRouteEvaluator(case_id,root,expanded=True)
    assert (1,1) in e.options and (1,59) in e.options and (2,1) in e.options
    speed=e.options.index((2,1))
    assert np.max(np.diff(e.paths[0][speed][:,0]))<=1.000001
    # Check both positive and negative relative shifts against the original
    # full comparison, using a departure path as both independent operands.
    i=2;e.domains[i]=tuple(e.options.index(g) for g in ((0,0),(1,1),(1,2),(1,5),(1,20),(1,60)))
    sample=e.sample([e.paths[i][c] for c in e.domains[i]],e.sample_s,i,e.domains[i])
    direct=e.conflicts(sample,sample)[0]
    assert np.array_equal(e.departure_shift_table(i,i),direct)


def test_parked_departure_can_advance_to_fixed_ready_clock(mini):
    case_id,root,e=mini
    manifest=e.manifest
    f=manifest['flights'][2]
    f['origin_status_at_planning']='PARKED'
    from datetime import timedelta
    f['requested_event_utc']=(datetime.fromisoformat(f['planned_event_utc'])-timedelta(seconds=137)).isoformat()
    (root/case_id/'manifest.json').write_bytes(json_bytes(manifest))
    changed=FullRouteEvaluator(case_id,root,expanded=True)
    code=changed.options.index((1,0))
    assert changed.events[2,code]==changed.events[2,0]-137
    assert changed.delays[2,code]==0
    assert changed.delays[2,0]==pytest.approx(137/60)
    assert np.allclose(changed.paths[2][code][:,1:],changed.paths[2][0][:,1:])
    # Non-minute, negative translations must match the global screening grid.
    changed.domains[2]=tuple(changed.options.index(g) for g in ((0,0),(1,0),(1,1),(1,5),(1,20)))
    sample=changed.sample([changed.paths[2][c] for c in changed.domains[2]],changed.sample_s,2,changed.domains[2])
    assert np.array_equal(changed.departure_shift_table(2,2),changed.conflicts(sample,sample)[0])


def test_saved_study_rejects_input_changes_and_escaping_run_pointer(mini):
    case_id,root,e=mini
    run_id='20261029T120000Z-1234abcd'
    folder=saved_folder(case_id,root,run_id)
    folder.mkdir(parents=True)
    (folder/'results.json').write_bytes(json_bytes(dict(version=VERSION,case_id=case_id,input_sha256=e.input_sha256)))
    (folder.parent/'latest.json').write_bytes(json_bytes(dict(run_id=run_id)))
    assert saved_result(case_id,root)['input_sha256']==e.input_sha256
    with (root/case_id/'capacity.csv').open('a') as stream:
        stream.write('\n')
    with pytest.raises(ValueError,match='Scenario changed'):
        saved_result(case_id,root)
    (folder.parent/'latest.json').write_bytes(json_bytes(dict(run_id='../../outside')))
    with pytest.raises(ValueError,match='identifier'):
        saved_folder(case_id,root)


def test_full_route_job_dispatch_uses_new_evaluator(tmp_path,monkeypatch):
    from flask import Blueprint,Flask
    from astra.dashboard import teammate_ga_routes as routes
    import astra.optimization.full_route_cases as full
    class Immediate:
        def __init__(self,target,**kwargs):self.target=target
        def start(self):self.target()
    calls=[]
    monkeypatch.setattr(routes,'Thread',Immediate)
    monkeypatch.setattr(routes,'WORKBOOK_ROOT',tmp_path)
    monkeypatch.setattr(full,'experiment',lambda **kwargs:calls.append(kwargs))
    monkeypatch.setattr(routes,'experiment',lambda **kwargs:pytest.fail('terminal optimizer dispatched'))
    bp=Blueprint('full_test',__name__)
    routes.register_teammate_routes(bp,SimpleNamespace(root=tmp_path/'video'))
    app=Flask(__name__);app.register_blueprint(bp)
    client=app.test_client()
    assert client.post('/api/case-scenarios/optimizer/run',json={'case_id':'workbook_low_20','seeds':[11]}).status_code==202
    assert calls[0]['root']==tmp_path
    assert 'compare_legacy' not in calls[0]
    assert client.get('/api/case-scenarios/optimizer/status').json['status']=='done'


@pytest.mark.parametrize('case_id',CASES)
def test_published_full_route_plans_load_finish_and_preserve_fine_validation(case_id,tmp_path):
    from astra.airspace import configure_profile
    from astra.dashboard.legacy_flask_app import create_app
    from astra.dashboard.store import CycleStore
    from astra.interface.state_reader import StateReader
    from astra.studies.system_tests import pair_audit
    from astra.utils.config import ASTRAConfig
    result=saved_result(case_id)
    assert len(result['settings']['seeds'])>=1
    assert result['settings']['fixed_departure_order']
    for name,run in result['runs'].items():
        if name.startswith('TEAM_'):
            assert run['search']['total_evaluations']<=result['settings']['max_evaluations']
            assert run['history'][-1]['objective']==run['search'].get('projected_incumbent_objective',run['metrics']['objective'])
            if run['search'].get('selection_basis')=='native_execution':
                assert 1<=run['search']['native_checks']<=result['settings']['native_check_budget_per_seed']
    config=configure_profile(ASTRAConfig(),'tsn_tma')
    reader=StateReader.for_mock(config,sim_step_s=20);reader.connect()
    client=create_app(CycleStore(),config,reader,scenarios_dir=str(tmp_path/'builder')).test_client()
    response=client.get('/api/case-scenarios/optimizer/results?case_id='+case_id)
    assert response.status_code==200 and response.json['version']==VERSION
    replay=reader._connector.case_replay
    assert len(result['native_trials'])==2+len(result['best_methods'])*len(result['settings']['seeds'])
    benchmarks=result['fcfs_benchmarks']
    assert {r['method'] for r in benchmarks}=={'FCFS_FINE','FCFS_COARSE'}
    assert next(r['metrics']['objective'] for r in result['native_trials'] if r['method']=='FCFS')==min(r['metrics']['objective'] for r in benchmarks)
    for row in result['native_summary']:
        trials=[r['metrics'] for r in result['native_trials'] if r['method']==row['method']]
        assert row['mean_total_delay_min']==pytest.approx(sum(m['total_delay_min'] for m in trials)/len(trials))
        assert row['safe_runs']==row['runs']
        assert row['mean_gate_flow_violations']==0
    for method in ('FCFS',*result['best_methods']):
        response=client.post('/api/system-tests/load',json=dict(case_id=case_id,method=method,run_id=result['run_id']))
        assert response.status_code==200,response.json
        checked=result['post_validation']['checks'][method]['native_execution_metrics']
        assert response.json['replay']['optimization_metrics']==checked
        executed=list(replay.metadata.values())
        settings=replay.manifest['study_settings']
        for f in executed:
            if f.get('atfm_measure')==1:assert f['atfm_level'] in settings['ground_levels_min']
            if f.get('atfm_measure')==2:assert f['atfm_level'] in settings['speed_levels_pct']
        assert checked['speed_flights']==sum(f.get('atfm_measure',0)==2 for f in executed)
        assert checked['ground_flights']==sum(f.get('atfm_measure',0)==1 for f in executed)
        baseline=json.loads((ROOT/case_id/'manifest.json').read_text(encoding='utf-8'))
        initial={f['callsign']:f['initial_airborne_spec'] for f in baseline['flights'] if f['direction']=='arrival'}
        for f in executed:
            if f['direction']=='arrival':
                spec=f['initial_airborne_spec']
                assert all(spec[key]==initial[f['callsign']][key] for key in ('lat','lon','altitude_ft'))
                assert spec['procedure_profile']['sequencing_circuits']==0
        folder=saved_folder(case_id,run_id=result['run_id'])/method.lower()
        # Independently audit the exported replay, not the evaluator's cached
        # search paths. This also checks rounded CSV timestamps and coordinates.
        paths={cs:[] for cs in replay.metadata}
        with (folder/'tracks.csv').open(encoding='utf-8',newline='') as stream:
            for row in csv.DictReader(stream):
                paths[row['callsign']].append([datetime.fromisoformat(row['time_utc']).timestamp()-datetime.fromisoformat(replay.manifest['local_start']).timestamp(),
                    *[float(row[k]) for k in ('lat','lon','altitude_ft','ground_speed_kt','heading_deg','vertical_speed_fpm')]])
        paths=[np.asarray(p) for p in paths.values()]
        directions=[f['direction'] for f in replay.metadata.values()]
        violating=sum(bool(pair_audit(a,b,terminal_mixed=directions[i]!=directions[j])['violations'])
            for i,a in enumerate(paths) for j,b in enumerate(paths[i+1:],i+1))
        assert violating==checked['separation_conflict_pairs']==0
        seen=set()
        for now in range(0,int(replay.duration_s)+21,20):
            reader._connector.restore_clock(now);replay.tick()
            seen.update(a['callsign'] for a in reader.list_aircraft())
        assert seen==set(replay.metadata)
        assert replay.status()['completed']==result['case_counts']['total']
        assert not reader.list_aircraft() and not reader.is_simulation_running()
        ground=client.get('/airport/state').json['aircraft']
        assert len(ground)==result['case_counts']['arrivals']
        assert all(a['state']=='ARRIVED' for a in ground)
    response=client.post('/scenario/presets/'+case_id+'/load',json=dict(method='FCFS',run_id=result['run_id']))
    assert response.status_code==200 and response.json['case_replay']['method']=='FCFS'
