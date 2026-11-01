"""The test fixtures must satisfy separation and two-minute arrival transfers."""
import csv
import json

import numpy as np
import pytest

from astra.centre import centre_point, control_area
from astra.studies.system_tests import ROOT,CASES,START,pair_audit
from astra.utils.geodesy import move_position
from tests.pytest.test_centre_connection import runtime


@pytest.mark.parametrize('altitude,visible',[(6999,False),(7000,True),(10000,True)])
def test_centre_retains_gray_tracks_inside_circle_until_below_7000(altitude,visible):
    area=control_area(*move_position(*centre_point(),90,20),'inbound',altitude_ft=altitude)
    assert area['owner']=='APPROACH'
    assert (area['centre_opacity']>0)==visible
    assert control_area(*move_position(*centre_point(),90,45),'inbound',altitude_ft=5000)['centre_opacity']==1


@pytest.mark.parametrize('case_id',CASES)
def test_saved_scenarios_recompute_separation_and_transfers(case_id):
    folder=ROOT/case_id
    m=json.loads((folder/'manifest.json').read_text())
    assert m['synthetic'] and m['separation_audit']['sample_s']==1
    with (folder/'tracks.csv').open() as stream:rows=list(csv.DictReader(stream))
    from datetime import datetime
    paths=[]
    for f in m['flights']:
        track=[r for r in rows if r['callsign']==f['callsign']]
        path=np.asarray([[(datetime.fromisoformat(r['time_utc'])-START).total_seconds(),
            float(r['lat']),float(r['lon']),float(r['altitude_ft']),float(r['ground_speed_kt']),
            float(r['heading_deg']),float(r['vertical_speed_fpm'])] for r in track])
        assert np.all(np.diff(path[:,0])>0)
        assert np.max(np.abs(path[:,6]))<=2000.01
        paths.append(path)
    for i,path in enumerate(paths):
        for other in paths[i+1:]:assert pair_audit(path,other)['violations']==0
    transfers=sorted(t['time_s'] for t in m['separation_audit']['transfer_events'] if t['direction']=='arrival')
    assert all(b-a>=120 for a,b in zip(transfers,transfers[1:]))
    assert len(paths)==m['counts']['total']


def test_supervisor_menu_layers_and_every_test_loads_and_finishes(tmp_path):
    reader,app,client=runtime(tmp_path,step=20)
    for route in ('/supervisor','/control-room'):
        assert '<title>MOSAIC · Supervisor</title>' in client.get(route).text
    centre=client.get('/centre').text
    for removed in ('AirNav case study','Lưu trữ ca VVTS','Kịch bản từ video AirNav','ATFM Lab','Tối ưu ATFM','control-boundary-caption'):
        assert removed not in centre
    assert 'data-panel="panel-alerts"' in centre and 'data-panel="panel-event"' in centre
    assert len(client.get('/api/system-tests').json['scenarios'])==len(CASES)+2
    for body in (None,[],{'case_id':'../bad'},{'case_id':[]}):
        assert client.post('/api/system-tests/load',json=body).status_code==400
    for case in CASES:
        response=client.post('/api/system-tests/load',json={'case_id':case})
        assert response.status_code==200,response.json
        state=response.json['replay'];assert state['system_test'] and not state['running']
        assert state['study_offset_s']==0 and state['enroute']
        replay=reader._connector.case_replay
        seen=set()
        for now in range(0,int(replay.duration_s)+40,20):
            reader._connector.restore_clock(now);replay.tick()
            seen.update(a['callsign'] for a in reader.list_aircraft())
            airport=client.get('/airport/state').json
            assert airport['sim_time_s']==reader.simulation_time_s()
        assert seen==set(replay.metadata)
        assert replay.status()['completed']==state['total']


def test_full_cycle_includes_every_ground_and_airborne_stage_and_rewind(tmp_path):
    reader,app,client=runtime(tmp_path)
    manifest=json.loads((ROOT/'test_full_cycle/manifest.json').read_text())
    assert manifest['counts']==dict(total=20,arrivals=10,departures=10)
    assert len({f['stand_id'] for f in manifest['flights'] if f['direction']=='departure'})==10
    assert client.post('/api/system-tests/load',json={'case_id':'test_full_cycle'}).status_code==200
    replay=reader._connector.case_replay
    assert replay.status()['ground_tracks']
    initial=client.get('/airport/state').json
    assert len(initial['aircraft'])==10
    assert all(a['state']=='PARKED' and a['speed_kt']==0 for a in initial['aircraft'])
    for f in manifest['flights']:
        cs=f['callsign'];marks=manifest['lifecycle_events'][cs]
        if f['direction']=='departure':
            phases=['off_block','runway_entry','takeoff','tma_handoff','centre_handoff','fir_route_exit']
            assert marks['tma_handoff']<marks['sid_exit']<marks['fir_route_exit']
            replay.seek(marks['off_block']+5)
            ac=next(a for a in client.get('/airport/state').json['aircraft'] if a['callsign']==cs)
            assert ac['state']=='TAXIING'
            assert 20<=ac['speed_kt']<=25
            assert cs not in {a['callsign'] for a in reader.list_aircraft()}
            replay.seek(marks['tma_handoff'])
            assert cs in {a['callsign'] for a in reader.list_aircraft()}
            assert cs not in {a['callsign'] for a in client.get('/airport/state').json['aircraft']}
        else:
            phases=['approach_handoff','approach_visible','touchdown','runway_exit','stand_arrival']
            replay.seek(marks['touchdown'])
            state=client.get('/airport/state').json
            assert cs in {a['callsign'] for a in state['aircraft']}
            assert cs not in state['approaches']
            replay.seek(marks['stand_arrival'])
            ac=next(a for a in client.get('/airport/state').json['aircraft'] if a['callsign']==cs)
            assert ac['state']=='ARRIVED' and ac['speed_kt']==0
            assert state['fpl'][cs]['stand']
        assert all(marks[b]>marks[a] for a,b in zip(phases,phases[1:]))
        assert f['completed_s']==marks[phases[-1]]
    replay.seek(replay.duration_s)
    final=client.get('/airport/state').json
    assert replay.status()['completed']==20
    assert len(final['aircraft'])==10 and all(a['state']=='ARRIVED' for a in final['aircraft'])
    assert not reader.list_aircraft()
    replay.seek(0)
    assert client.get('/airport/state').json['aircraft']==initial['aircraft']
    assert replay.status()['completed']==0
