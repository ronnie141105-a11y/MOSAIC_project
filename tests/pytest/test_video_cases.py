"""Exercise real video-derived packages on the shared TMA runtime."""
import csv
from dataclasses import replace
import json
from pathlib import Path

import pytest

from astra.dashboard.legacy_flask_app import create_app
from astra.dashboard.store import CycleStore
from astra.interface.state_reader import StateReader
from astra.studies.case_replay import CaseStudyReplay, DEFAULT_ROOT
from astra.utils.config import ASTRAConfig


@pytest.fixture
def runtime(tmp_path):
    config=replace(ASTRAConfig(),airspace_profile='tsn_tma')
    reader=StateReader.for_mock(config,sim_step_s=20)
    reader.connect()
    store=CycleStore()
    app=create_app(store,config,reader,scenarios_dir=str(tmp_path/'builder'))
    return reader,store,app.test_client(),reader._connector.case_replay


def test_catalog_excludes_october7_and_discloses_missing_arrivals(runtime):
    _,_,client,_=runtime
    cases=client.get('/api/case-scenarios').json['cases']
    assert {c['case_id'] for c in cases}=={'nominal','holiday_peak','workbook_peak_50','workbook_low_20'}
    assert next(c for c in cases if c['case_id']=='nominal')['coverage']['missing_arrival_recording']
    assert client.post('/api/case-scenarios/load',json={'case_id':'bad_weather'}).status_code==400
    assert client.get('/').status_code==200
    assert '/case-scenarios' not in client.get('/').text
    assert '/supervisor' in client.get('/').text
    assert client.get('/case-scenarios').status_code==200
    assert client.get('/scenario').status_code==200


def test_reviewed_aliases_and_duplicate_recording_are_not_extra_flights():
    evidence=json.loads((DEFAULT_ROOT/'evidence/video_observations.json').read_text(encoding='utf-8'))
    ids={f['display_callsign'] for f in evidence['flights']}
    assert not ids.intersection({'VN6411','VJ811','VJ8011','VN2441','VN4021'})
    assert {'VN641','VJ81','VJ801','SPQ821'}.issubset(ids)
    assert all(f['case_id']!='bad_weather' for f in evidence['flights'])
    inventory=json.loads((DEFAULT_ROOT/'evidence/archive_inventory.json').read_text())
    hashes={i['file']:i['sha256'] for i in inventory}
    assert hashes['VVTS_ARR_OCT82026.mp4']==hashes['VVTS_DEP_FEB22_2026.mp4']
    assert all('OCT7' not in name for name in hashes)


@pytest.mark.parametrize('case_id,total,arrivals,departures',[('nominal',55,23,32),('holiday_peak',80,37,43)])
def test_complete_replay_spawns_all_flights_and_finishes_without_overshoot(runtime,case_id,total,arrivals,departures):
    reader,_,client,replay=runtime
    result=client.post('/api/case-scenarios/load',json={'case_id':case_id})
    assert result.status_code==200,result.json
    assert result.json['replay']['total']==total
    assert not reader.is_simulation_running()
    assert len(reader.list_aircraft())<total
    assert replay.manifest['counts']['arrivals']==arrivals
    assert replay.manifest['counts']['departures']==departures
    seen=set()
    now=0
    while now<=replay.duration_s+20:
        reader._connector.restore_clock(now)
        replay.tick()
        aircraft=reader.list_aircraft()
        seen.update(ac['callsign'] for ac in aircraft)
        assert all(abs(ac['vertical_speed_fpm'])<=2000.1 for ac in aircraft)
        assert all(ac['direction'] in ('inbound','outbound') for ac in aircraft)
        now+=20
    assert seen==set(replay.metadata)
    assert reader.simulation_time_s()==replay.duration_s
    assert replay.status()['completed']==total
    assert not reader.is_simulation_running()
    assert not reader.list_aircraft()


def test_controls_and_seek_restore_past_trails_and_reset_other_case(runtime):
    reader,store,client,replay=runtime
    assert client.post('/api/case-scenarios/control',json={'action':'play'}).status_code==400
    client.post('/api/case-scenarios/load',json={'case_id':'holiday_peak'})
    client.post('/api/case-scenarios/control',json={'action':'speed','multiplier':5})
    client.post('/api/case-scenarios/control',json={'action':'play'})
    reader.poll()
    assert reader.simulation_time_s()==100
    client.post('/api/case-scenarios/control',json={'action':'pause'})
    reader.poll()
    assert reader.simulation_time_s()==100
    initial_generation=store.trail_generation
    result=client.post('/api/case-scenarios/control',json={'action':'seek','time_s':2400})
    assert result.status_code==200,result.json
    assert not reader.is_simulation_running()
    paths=store.trails()['paths']
    assert paths and any(len(path)>4 for path in paths.values())
    assert all(p['time_s']<=2400 for path in paths.values() for p in path)
    assert store.trail_generation>initial_generation
    client.post('/api/case-scenarios/control',json={'action':'seek','time_s':0})
    reader.poll()
    assert len(reader.history())==1 and reader.current().timestamp_s==0
    client.post('/api/case-scenarios/load',json={'case_id':'nominal'})
    assert replay.case_id=='nominal' and replay.status()['total']==55
    assert reader.simulation_time_s()==0
    assert set(reader._connector.airport_integration.fpl)==set(replay.metadata)
    result=client.post('/api/case-scenarios/control',json={'action':'stop'})
    assert result.status_code==200 and not result.json['replay']['active']
    assert reader.list_aircraft()==[]
    assert store.trails()['paths']=={}
    # The original independent procedure simulator remains usable after stop.
    result=client.post('/scenario/procedure-aircraft',json={'callsign':'TEST01','procedure_id':'BITIS2H','runway':'25R'})
    assert result.status_code==200,result.json
    reader.step_simulation()
    assert any(ac['callsign']=='TEST01' for ac in reader.list_aircraft())


def test_case_blocks_transient_edits_but_keeps_shared_radar_and_fpl(runtime):
    reader,_,client,replay=runtime
    client.post('/api/case-scenarios/load',json={'case_id':'holiday_peak'})
    client.post('/api/case-scenarios/control',json={'action':'seek','time_s':1200})
    for path in ('/airport/departures','/airport/point-merge/clearance','/scenario/clearance','/scenario/random-aircraft'):
        assert client.post(path,json={}).status_code==409
    payload=client.get('/airport/state').json
    assert payload['case_replay']['active']
    for ac in reader.list_aircraft():
        profile=reader._connector.get_flight_profile(ac['callsign'])
        assert profile['flight_type']=='CASE_STUDY_REPLAY'
        assert payload['fpl'][ac['callsign']]['runway']==profile['runway']
    assert not client.get('/api/operations/state').json['available']
    assert client.get('/api/operations/state').json['case_replay']['case_id']=='holiday_peak'
    client.post('/scenario/control',json={'action':'reset'})
    assert not replay.active
    assert client.get('/api/operations/state').json['available']


@pytest.mark.parametrize('body',[[],None,'invalid',{'action':'seek','time_s':float('inf')},{'action':'speed','multiplier':0}])
def test_bad_controls_do_not_corrupt_loaded_case(runtime,body):
    reader,_,client,replay=runtime
    client.post('/api/case-scenarios/load',json={'case_id':'nominal'})
    assert client.post('/api/case-scenarios/control',json=body).status_code==400
    assert replay.active and reader.simulation_time_s()==0


def test_runway_event_columns_do_not_claim_observed_times():
    for case_id in ('nominal','holiday_peak'):
        folder=DEFAULT_ROOT/case_id
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        with (folder/'flights.csv').open(encoding='utf-8-sig') as f:
            rows=list(csv.DictReader(f))
        assert len(rows)==manifest['counts']['total']
        assert all(not row['actual_takeoff_utc'] and not row['actual_landing_utc'] for row in rows)
        if case_id=='nominal':
            assert sum(flight['evidence']=='synthetic_missing_oct8_arrival_recording' for flight in manifest['flights'])==23
        summary=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
        assert summary['separation_audit']['arrival_arrival_under_10_nm']==0
        assert summary['separation_audit']['arrival_arrival_same_heading_under_20_nm']==0
