import csv
from datetime import datetime
import json
import numpy as np
import pytest
from astra.studies.workbook_cases import ROOT
from astra.studies.vvts_cases import dataset_for_case
from astra.studies.ground_replay import GroundReplay
from astra.centre import distance_nm

@pytest.mark.parametrize('case,count',[('workbook_low_20',3),('workbook_peak_50',4)])
def test_historical_departures_have_real_startup_positions_and_retained_times(case,count):
    m=json.loads((ROOT/case/'manifest.json').read_text(encoding='utf-8'));d=dataset_for_case(ROOT/case)
    start=datetime.fromisoformat(m['local_start']).timestamp()
    flights=[f for f in m['flights'] if f.get('startup_airborne_departure')]
    assert len(flights)==count
    ranges=[]
    for f in flights:
        assert f['ctot_s']<0 and f['tobt_s']<f['ctot_s']
        assert not f['ground_delay_eligible'] and f['origin_status_at_planning']=='ALREADY_AIRBORNE'
        points=d.points[f['callsign']];at=min(points,key=lambda p:abs(p.epoch_s-start)).state
        assert at.altitude_ft>1000 and at.ground_speed_kt>150
        ranges.append(distance_nm(at.lat,at.lon))
    assert min(ranges)<40<max(ranges)
    assert min(f['completed_s'] for f in flights)<120
    with (ROOT/case/'fpl.csv').open(encoding='utf-8') as stream:plans={r['callsign']:r for r in csv.DictReader(stream)}
    assert all(plans[f['callsign']]['tobt_utc'] and plans[f['callsign']]['ctot_utc'] for f in flights)
    g=GroundReplay(ROOT/case/'ground_tracks.json.gz')
    assert not {f['callsign'] for f in flights}&{a['callsign'] for a in g.frame_at(0,{})['aircraft']}

@pytest.mark.parametrize('case',['workbook_low_20','workbook_peak_50'])
def test_point_merge_startup_and_phu_quoc_routing(case):
    m=json.loads((ROOT/case/'manifest.json').read_text(encoding='utf-8'))
    approaching=[f for f in m['flights'] if f.get('startup_approach')]
    assert len(approaching)==2
    for f in approaching:
        p=f['initial_airborne_spec']['procedure_profile']
        assert p['startup_point_merge_pending'] and p['approach_transfer_complete']
        assert f['transfer_time_s']<0 and not f['speed_control_eligible']
        assert len(p['legs'])>5 and not p.get('study_terminal_direct')
    pqu=[f for f in m['flights'] if f['direction']=='arrival' and f['adep']=='VVPQ']
    assert pqu
    assert all(f['route_family']=='PQU_BITIS' and 'PQU → RG → TRN → BITIS' in f['centre_route'] for f in pqu)
    assert all('NIXIV' not in f['centre_route'] and 'VICAL' not in f['procedure'] for f in pqu)

def test_atfm_completes_only_after_departure_sector_exit_and_no_excess(tmp_path,monkeypatch):
    from astra.airspace import configure_profile
    from astra.interface.state_reader import StateReader
    from astra.dashboard.legacy_flask_app import create_app
    from astra.dashboard.store import CycleStore
    from astra.utils.config import ASTRAConfig
    config=configure_profile(ASTRAConfig(),'tsn_tma');reader=StateReader.for_mock(config,sim_step_s=1);reader.connect()
    client=create_app(CycleStore(),config,reader,scenarios_dir=str(tmp_path/'builder')).test_client()
    assert client.post('/api/system-tests/load',json=dict(case_id='workbook_peak_50')).status_code==200
    replay=reader._connector.case_replay;end=replay.departure_phase_end_s
    monkeypatch.setattr('astra.studies.study_sectors.current_counts',lambda aircraft:[dict(excess=0)])
    assert not replay.seek(end-1)['atfm_complete']
    monkeypatch.setattr('astra.studies.study_sectors.current_counts',lambda aircraft:[dict(excess=1)])
    assert not replay.seek(end+1)['atfm_complete']
    monkeypatch.setattr('astra.studies.study_sectors.current_counts',lambda aircraft:[dict(excess=0)])
    state=replay.seek(end+1)
    assert state['atfm_complete'] and not state['running'] and state['remaining_arrivals']>0
    assert state['completed']<state['total']
    assert not any(a['callsign'].startswith('D') for a in reader.list_aircraft())
    reader._connector.restore_clock(end+60);reader.send_command('OP');replay.tick()
    assert reader.is_simulation_running()  # optional arrival tail remains runnable
