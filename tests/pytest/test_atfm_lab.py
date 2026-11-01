from copy import deepcopy
import json
import math
import pytest
from astra.optimization.atfm import scenario,evaluate,heuristic,optimize,audit
from astra.optimization.replay import ATFMReplay
from astra.airspace import configure_profile
from astra.utils.config import ASTRAConfig
from astra.interface.state_reader import StateReader
from astra.pipeline import Pipeline
from astra.dashboard.store import CycleStore
from astra.dashboard.legacy_flask_app import create_app


def test_constraints_delay_accounting_and_full_tail():
    s=scenario()
    for p in ([0]*108,heuristic(s),heuristic(s,True)):
        m,rows=evaluate(s,p);assert audit(s,p,rows)
        assert m['completed']==54 and m['final_exit_min']>120
        for r in rows:
            assert 250<=r['upstream_ground_speed_kt']<=300
            assert r['ground_eligible'] or r['ground_delay_min']==0

@pytest.mark.parametrize('index,value',[(0,1),(54,5),(55,-1),(60,float('nan'))])
def test_invalid_plan_rejected(index,value):
    p=[0]*108;p[index]=value
    with pytest.raises(ValueError):evaluate(scenario(),p)


def test_reproducible_elitism_and_two_measures():
    s=scenario()
    for mode in ['ground','mixed']:
        p,h,_=optimize(s,mode,11,12,8);p2,h2,_=optimize(s,mode,11,12,8)
        assert p==p2 and h==h2
        assert all(b['objective']<=a['objective'] for a,b in zip(h,h[1:]))
        assert h[-1]['objective']<=evaluate(s,heuristic(s,mode=='mixed'))[0]['objective']
        if mode=='ground':assert not any(p[54:])


def test_low_demand_no_unnecessary_control():
    s=scenario();s['entry_capacity_15min']=[6]*8
    s['flights']=s['flights'][:6]
    for i,f in enumerate(s['flights']):
        f['eta_min']=10*i;f['travel_to_entry_min']=f['eta_min']-f['reference_takeoff_min']
    p,_,_=optimize(s,'mixed',11,12,8)
    assert evaluate(s,p)[0]['objective']==0


def test_speed_absorption_is_not_free_delay():
    s=scenario();p=[0]*108;p[54]=4
    m,rows=evaluate(s,p);r=next(r for r in rows if r['id']=='SYN001')
    assert r['speed_delay_min']==4 and r['upstream_ground_speed_kt']==250
    assert r['request_min']==pytest.approx(r['eta_min']+4)
    assert m['objective']==pytest.approx(m['ground_delay_min']+2*m['speed_delay_min']+4*m['airborne_holding_min']+.2*m['max_delay_min'])


def make_reader():
    cfg=configure_profile(ASTRAConfig(),'tsn_tma');reader=StateReader.for_mock(cfg,sim_step_s=60);reader.connect()
    return cfg,reader


def test_replay_real_connector_all_flights_and_reset():
    cfg,reader=make_reader();s=scenario();_,rows=evaluate(s,heuristic(s,True))
    adapter=ATFMReplay(reader);adapter.load('TEST',rows);reader.set_speed_multiplier(1)
    for _ in range(math.ceil(max(r['exit_min'] for r in rows))+1):
        reader._connector.poll();now=reader.simulation_time_s()/60
        expected={r['id'] for r in rows if r['entry_min']<=now<r['exit_min']}
        assert set(reader._connector.latest_snapshot().aircraft)==expected
        assert all(150<a.ground_speed_kt<300 for a in reader._connector.latest_snapshot().aircraft.values())
        assert adapter.status()['occupancy']==len(expected)
    assert adapter.status()['completed']==54 and not reader.is_simulation_running()
    reader.reset_simulation();assert not adapter.active and not reader.list_aircraft()


def test_flask_replay_to_actual_pipeline_and_csv(tmp_path,monkeypatch):
    s=scenario();p=heuristic(s,True);m,rows=evaluate(s,p)
    file=tmp_path/'result.json';file.write_text(json.dumps({'runs':{'TEST':{'metrics':m,'flights':rows,'plan':p}}}))
    monkeypatch.setenv('MOSAIC_ATFM_RESULTS',str(file))
    cfg,reader=make_reader();pipeline=Pipeline(cfg,route_provider=reader.get_route,profile_provider=reader.get_flight_profile);store=CycleStore()
    app=create_app(store,cfg,reader=reader,pipeline=pipeline);client=app.test_client()
    assert client.get('/atfm').status_code==200
    assert client.get('/atfm-formulation').status_code==200
    assert client.get('/dashboard/atfm_formulation.js').status_code==200
    assert client.get('/dashboard/atfm.js').status_code==200
    assert client.get('/dashboard/atfm.css').status_code==200
    assert b'/dashboard/atfm.js' in client.get('/atfm').data
    assert client.post('/api/atfm/run',json={'population':0}).status_code==400
    assert client.post('/api/atfm/run',json=[]).status_code==400
    assert client.post('/api/atfm/replay',json={'method':'absent'}).status_code==404
    assert client.post('/api/atfm/replay',json={'method':'TEST'}).status_code==200
    reader.set_speed_multiplier(1)
    for _ in range(10):reader._connector.poll()
    snapshot=reader._connector.latest_snapshot();assert snapshot.aircraft
    result=pipeline.run_cycle(snapshot);store.update(result)
    assert set(result.snapshot.aircraft)=={r['id'] for r in rows if r['entry_min']<=10<r['exit_min']}
    assert result.airspace_metrics['arrivals']==len(snapshot.aircraft)
    assert all(p['synthetic'] for p in result.flight_profiles.values())
    assert client.get('/state').status_code==200
    assert b'TEST' in client.get('/api/atfm/export.csv').data
    assert client.get('/api/atfm/status').json['replay']['entered']>0
    reader.reset_simulation();assert not client.get('/api/atfm/status').json['replay']['active']

def test_background_run_persists_results_and_rejects_duplicate(tmp_path,monkeypatch):
    import threading,time
    from astra.dashboard import atfm_routes
    started=threading.Event();release=threading.Event()
    def fake_experiment(**kwargs):
        started.set();assert release.wait(3);return {'runs':{},'settings':kwargs}
    monkeypatch.setattr(atfm_routes,'experiment',fake_experiment)
    file=tmp_path/'job.json';monkeypatch.setenv('MOSAIC_ATFM_RESULTS',str(file))
    cfg,reader=make_reader();app=create_app(CycleStore(),cfg,reader=reader);client=app.test_client()
    try:
        assert client.post('/api/atfm/run',json={'population':4,'generations':1}).status_code==202
        assert started.wait(1)
        assert client.post('/api/atfm/run',json={}).status_code==409
    finally:release.set()
    deadline=time.monotonic()+3
    while client.get('/api/atfm/status').json['status']=='running' and time.monotonic()<deadline:time.sleep(.02)
    assert client.get('/api/atfm/status').json['status']=='done'
    assert json.loads(file.read_text())['settings']['population']==4
    assert client.get('/api/atfm/results').status_code==200
