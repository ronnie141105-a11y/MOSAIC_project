"""Full airport journeys, shared runway protection and real-map sector ownership."""
from datetime import datetime
import csv
import gzip
import json

import numpy as np
import pytest

from astra.airspace import configure_profile,procedure_aircraft
from astra.airport.aircraft import Aircraft
from astra.airport.graph import KEY_NODES
from astra.dashboard.legacy_flask_app import create_app
from astra.dashboard.store import CycleStore
from astra.interface.state_reader import StateReader
from astra.studies.ground_replay import GroundReplay
from astra.studies.study_routes import FAMILIES
from astra.studies.study_sectors import SECTORS, sample_masks, sector_id, slabs
from astra.studies.workbook_cases import CASES, ROOT
from astra.utils.config import ASTRAConfig


@pytest.fixture
def runtime(tmp_path):
    config=configure_profile(ASTRAConfig(),'tsn_tma')
    reader=StateReader.for_mock(config,sim_step_s=1);reader.connect()
    app=create_app(CycleStore(),config,reader,scenarios_dir=str(tmp_path/'builder'))
    return reader,app,app.test_client()


@pytest.mark.parametrize('case_id',CASES)
@pytest.mark.parametrize('entrypoint',('builder','supervisor'))
def test_both_normal_entrypoints_load_stands_ctot_and_final_parking(runtime,case_id,entrypoint):
    reader,app,client=runtime
    if entrypoint=='builder':
        assert case_id in {p['key'] for p in client.get('/scenario/presets').json['presets']}
        response=client.post('/scenario/presets/'+case_id+'/load')
    else:
        assert case_id in {p['case_id'] for p in client.get('/api/system-tests').json['scenarios']}
        response=client.post('/api/system-tests/load',json={'case_id':case_id})
    assert response.status_code==200,response.json
    replay=reader._connector.case_replay
    initial=client.get('/airport/state').json['aircraft']
    history=sum(bool(f.get('startup_airborne_departure')) for f in replay.manifest['flights'])
    assert len(initial)==CASES[case_id]['departures']-history
    assert all(a['state'] in ('PARKED','TAXIING','HOLDING','LINING_UP') and a['fpl']['ctot_s']>0 for a in initial)
    assert 1<=sum(a['state']!='PARKED' for a in initial)<=2
    assert sum(a['state']=='PARKED' for a in initial)>=len(initial)-2
    assert all(a['fpl']['tobt_s']>0 for a in initial if a['state']=='PARKED')
    assert len(reader.list_aircraft())==CASES[case_id]['arrivals']+history
    assert len({(a['x'],a['y']) for a in initial})==len(initial)
    first=next(f for f in replay.metadata.values() if f['direction']=='departure' and not f.get('startup_airborne_departure'))
    marks=replay.ground_replay.milestones[first['callsign']]
    replay.seek(max(0,marks['runway_entry']+1))
    ac=next(a for a in client.get('/airport/state').json['aircraft'] if a['callsign']==first['callsign'])
    assert ac['state']=='LINING_UP' and ac['speed_kt']==0
    replay.seek(replay.duration_s)
    final=client.get('/airport/state').json['aircraft']
    counts=replay.manifest['counts']
    assert len(final)==counts['arrivals']
    assert all(a['state']=='ARRIVED' and a['speed_kt']==0 for a in final)
    assert len({a['stand'] for a in final})==len(final)
    assert replay.status()['completed']==counts['total']
    assert all(s['count']==0 for s in replay.status()['sector_occupancy'])
    replay.seek(0)
    assert len(client.get('/airport/state').json['aircraft'])==len(initial)
    assert replay.status()['completed']==0


@pytest.mark.parametrize('case_id',CASES)
def test_all_ground_journeys_and_full_runway_evacuation(case_id):
    manifest=json.loads((ROOT/case_id/'manifest.json').read_text())
    replay=GroundReplay(ROOT/case_id/'ground_tracks.json.gz')
    arrivals=[f for f in manifest['flights'] if f['direction']=='arrival']
    departures=[f for f in manifest['flights'] if f['direction']=='departure']
    for f in arrivals:
        m=replay.milestones[f['callsign']]
        assert m['touchdown']<m['landing_two_thirds']<m['runway_exit']<m['stand_arrival']
        states={s[6] for s in replay.flights[f['callsign']]['samples']}
        assert {'LANDED','TAXIING','ARRIVED'}<=states
    start=datetime.fromisoformat(manifest['local_start']).timestamp()
    # Recheck exported positions against the approach buffer, independent of
    # the audit fields stored in the manifest. Six NM applies at roll start;
    # touchdown must also follow wheel-off by more than thirty seconds.
    from astra.airspace import load_profile
    from astra.utils.geodesy import haversine_distance_nm
    threshold=load_profile('tsn_tma')['waypoint_data']['RW25R']
    protection={}
    with (ROOT/case_id/'tracks.csv').open(encoding='utf-8',newline='') as stream:
        for row in csv.DictReader(stream):
            if row['callsign'].startswith('A') and haversine_distance_nm(float(row['lat']),float(row['lon']),threshold['lat'],threshold['lon'])<=6:
                protection.setdefault(row['callsign'],datetime.fromisoformat(row['time_utc']).timestamp()-start)
    for f in departures:
        m=replay.milestones[f['callsign']]
        assert m['off_block']<m['runway_entry']<m['takeoff']
        assert m['takeoff']==f['ctot_s']==f['original_ctot_s']
        assert datetime.fromisoformat(f['simulated_slot_utc']).timestamp()-start==m['takeoff']
        states={s[6] for s in replay.flights[f['callsign']]['samples']}
        assert {'TAXIING','CLIMBING'}<=states
        assert states & {'HOLDING','LINING_UP'}
        assert f['tobt_s']<=m['off_block']<f['ctot_s']
        for a in arrivals:
            landing=replay.milestones[a['callsign']]
            assert not landing['touchdown']<=m['takeoff_roll']<landing['runway_exit']
            assert not m['takeoff_roll']<=landing['touchdown']<=m['takeoff']
            assert m['takeoff_roll']<protection[a['callsign']] or m['takeoff_roll']>=landing['runway_exit']
            assert m['takeoff_roll']>=landing['touchdown'] or m['takeoff']+30<landing['touchdown']
    # Both cases must actually use a gap between arrivals, not merely declare
    # the shorter protection distance while retaining the old late CTOTs.
    last_landing=max(replay.milestones[f['callsign']]['touchdown'] for f in arrivals)
    assert any(replay.milestones[f['callsign']]['takeoff']<last_landing
        and any(replay.milestones[a['callsign']]['runway_exit']<=replay.milestones[f['callsign']]['takeoff_roll'] for a in arrivals)
        for f in departures)
    departures=sorted(replay.milestones[f['callsign']]['takeoff'] for f in departures)
    assert min(b-a for a,b in zip(departures,departures[1:]))>=120
    transfers=sorted(f['transfer_time_s'] for f in arrivals)
    assert min(b-a for a,b in zip(transfers,transfers[1:]))>=120


@pytest.mark.parametrize('case_id',CASES)
def test_corridor_diversity_prioritizes_w1_without_sapen_departures(case_id):
    flights=json.loads((ROOT/case_id/'manifest.json').read_text())['flights']
    arrivals=[f for f in flights if f['direction']=='arrival']
    departures=[f for f in flights if f['direction']=='departure']
    assert {f['callsign'] for f in arrivals}=={f'A{i:03d}' for i in range(1,len(arrivals)+1)}
    assert {f['callsign'] for f in departures}=={f'D{i:03d}' for i in range(1,len(departures)+1)}
    assert all(f['source_callsign'].startswith(('L20-','P50-','REGIONAL-')) for f in flights)
    assert .3<=sum(f['route_family'].startswith('W1_') for f in arrivals)/len(arrivals)<=.5
    families={f['route_family'] for f in flights}
    assert {'W1_AC','W1_LKH','PTH_BAOMY','BIBAN_BITIS','VTV','SAPEN_WEST','PQU_BITIS','XOBAV_NIXIV'}<=families
    assert len({f['procedure'] for f in departures})>=4
    assert all('SAPEN' not in f['centre_route'] and 'SAPEN' not in f['procedure'] for f in departures)


@pytest.mark.parametrize('case_id',CASES)
def test_forward_streams_and_timed_stand_releases(case_id):
    from astra.studies.vvts_cases import dataset_for_case
    from astra.utils.geodesy import haversine_distance_nm
    manifest=json.loads((ROOT/case_id/'manifest.json').read_text());data=dataset_for_case(ROOT/case_id)
    arrivals=[f for f in manifest['flights'] if f['direction']=='arrival']
    initial=[]
    for f in arrivals:
        profile=f['initial_airborne_spec']['procedure_profile']
        assert profile['sequencing_circuits']==0
        assert all(leg.get('phase')!='centre_hold' for leg in profile['legs'])
        points=data.points[f['callsign']];a=points[0].state;b=points[60].state
        assert haversine_distance_nm(a.lat,a.lon,b.lat,b.lon)>1
        if not f.get('origin_pending'):initial.append(a)
    assert min(haversine_distance_nm(a.lat,a.lon,b.lat,b.lon) for i,a in enumerate(initial) for b in initial[i+1:])>=10
    assert manifest['stream_audit']['centre_horizontal_conflict_pairs']==[]
    ground=GroundReplay(ROOT/case_id/'ground_tracks.json.gz')
    for f in manifest['flights']:
        if f['direction']!='departure' or f['tobt_s']<=0:continue
        actual=ground.milestones[f['callsign']]['off_block']
        before={a['callsign']:a for a in ground.frame_at(actual-1,{})['aircraft']}
        after={a['callsign']:a for a in ground.frame_at(actual+2,{})['aircraft']}
        assert actual>=f['tobt_s']
        assert before[f['callsign']]['state']=='PARKED'
        assert after[f['callsign']]['state']=='TAXIING'
    peak_active=0
    for now in range(0,int(manifest['duration_s']),20):
        active=[a for a in ground.frame_at(now,{})['aircraft'] if a['operation']=='dep' and a['state'] not in ('PARKED','CLIMBING','DEPARTED')]
        peak_active=max(peak_active,len(active))
        assert len(active)<=4
    assert 1<=peak_active<=4
    queued=[f for f in manifest['flights'] if f['direction']=='departure' and ground.milestones[f['callsign']]['off_block']<1500]
    assert len(queued)>=2  # Ready traffic can leave stand before late CTOT slots.
    assert manifest['surface_audit']['maximum_departures_on_runway']==1
    assert manifest['surface_audit']['arrival_protection_nm']==6
    assert manifest['surface_audit']['arrival_protection_s']==30


def test_native_runway_guard_uses_6nm_at_roll_start_and_predicted_touchdown_margin(runtime):
    _,app,_=runtime
    airport=app.airport_integration
    graph=airport.graph
    departure=Aircraft('DEP','A320','dep',graph.stands()[0].id)
    airport.sim.add_aircraft(departure);airport.sim.assign_departure_route('DEP')
    departure.seg_idx=departure.route.index(KEY_NODES['RWY25L_START'])
    start=graph.node(KEY_NODES['RWY25R_SPAWN']);end=graph.node(KEY_NODES['RWY25R_EXIT_P4'])
    arrival=Aircraft('ARR','A320','arr',start.id)
    airport.sim.add_aircraft(arrival)
    outside=next(n for n in graph.nodes.values() if n.id not in airport.sim.rwy25r_nodes|airport.sim.rwy25l_nodes)
    arrival.route=[start.id,end.id,outside.id]
    for fraction in (.65,.67,.99):
        arrival.x=start.x+(end.x-start.x)*fraction
        arrival.y=start.y+(end.y-start.y)*fraction
        assert not airport.departure_runway_available(departure)
    arrival.seg_idx=2;arrival.x=outside.x;arrival.y=outside.y
    assert airport.departure_runway_available(departure)
    airport.sim.aircraft.pop('ARR')
    airport.approaches={'FINAL':dict(distance_nm=.3,speed_kt=140)}
    assert not airport.departure_runway_available(departure)
    airport.approaches={'FINAL':dict(distance_nm=6,speed_kt=140)}
    assert not airport.departure_runway_available(departure)
    airport.approaches={'FINAL':dict(distance_nm=7,speed_kt=450)}
    assert not airport.departure_runway_available(departure)
    # The arrival may cross 6 NM after the roll has begun. There is still
    # enough time for wheel-off and the separate touchdown margin.
    airport.approaches={'FINAL':dict(distance_nm=7,speed_kt=140)}
    assert airport.departure_runway_available(departure)
    airport.approaches={'FINAL':dict(distance_nm=10,speed_kt=230)}
    assert airport.departure_runway_available(departure)


def test_arrival_blocks_takeoff_roll_but_allows_one_aircraft_to_line_up(runtime):
    _,app,_=runtime;airport=app.airport_integration;sim=airport.sim
    departure=Aircraft('LINEUP','A320','dep',airport.graph.stands()[0].id)
    sim.add_aircraft(departure);sim.assign_departure_route(departure.callsign)
    hld=departure.route.index(KEY_NODES['HLD_S1']);departure.seg_idx=hld
    departure.cleared_takeoff=True
    node=airport.graph.node(departure.route[hld]);departure.x=node.x;departure.y=node.y
    # A future CTOT must not stop the queue leader from lining up now.
    departure.ctot_s=3600
    airport.approaches={'FINAL':dict(distance_nm=5,speed_kt=140)}
    assert not sim._should_hold(departure,departure.route[hld],departure.route[hld+1])
    departure.seg_idx=hld+1;node=airport.graph.node(departure.route[hld+1])
    departure.x=node.x;departure.y=node.y
    assert sim._should_hold(departure,departure.route[hld+1],departure.route[hld+2])
    assert departure.state.name=='LINING_UP' and not departure.takeoff_roll_started
    sim._update_rwy_occupation()
    follower=Aircraft('NEXT','A320','dep',airport.graph.stands()[1].id)
    sim.add_aircraft(follower);sim.assign_departure_route(follower.callsign)
    follower.seg_idx=follower.route.index(KEY_NODES['HLD_S1']);follower.cleared_takeoff=True
    assert sim._should_hold(follower,follower.route[follower.seg_idx],follower.route[follower.seg_idx+1])


def test_tower_sees_arrival_outside_8nm_without_blocking_a_safe_departure(runtime):
    from astra.utils.geodesy import move_position
    reader,app,_=runtime;airport=app.airport_integration
    departure=Aircraft('DEP','A320','dep',airport.graph.stands()[0].id)
    airport.sim.add_aircraft(departure);airport.sim.assign_departure_route(departure.callsign)
    spec=procedure_aircraft('tsn_tma','DALAP2H','OUTSIDE8')
    threshold=airport.profile['waypoint_data']['RW25R']
    spec['lat'],spec['lon']=move_position(threshold['lat'],threshold['lon'],69,11)
    reader.create_aircraft(**spec)
    assert not airport.approaches
    assert airport.departure_runway_available(departure)
    tower=airport.state()['tower_arrivals']['OUTSIDE8']
    assert tower['distance_nm']==pytest.approx(11,abs=.01)
    assert tower['lat']==pytest.approx(spec['lat']) and tower['lon']==pytest.approx(spec['lon'])


def test_stopped_lineup_allows_distant_arrival_crossing_before_takeoff(runtime):
    _,app,_=runtime;airport=app.airport_integration;sim=airport.sim
    departure=Aircraft('LINEUP','A320','dep',airport.graph.stands()[0].id)
    sim.add_aircraft(departure);sim.assign_departure_route(departure.callsign)
    departure.seg_idx=departure.route.index(KEY_NODES['RWY25L_START'])
    node=airport.graph.node(KEY_NODES['RWY25L_START'])
    departure.x,departure.y=node.x,node.y
    exit_node=airport.graph.node(KEY_NODES['RWY25R_EXIT_P5'])
    stand=airport.graph.node('n9')
    arrival=Aircraft('CROSS','A320','arr',stand.id)
    sim.add_aircraft(arrival);sim.assign_arrival_route(arrival.callsign,exit_node.id,stand.id)
    arrival.seg_idx=next(i for i,(cur,nxt) in enumerate(zip(arrival.route,arrival.route[1:]))
        if cur not in sim.rwy25l_nodes and nxt in sim.rwy25l_nodes)
    node=airport.graph.node(arrival.route[arrival.seg_idx]);arrival.x,arrival.y=node.x,node.y
    arrival.cleared_cross=True
    sim._update_rwy_occupation()
    cur,nxt=arrival.route[arrival.seg_idx:arrival.seg_idx+2]
    assert not sim._should_hold(arrival,cur,nxt)
    assert not airport.departure_runway_available(departure)
    departure.takeoff_roll_started=True
    assert sim._should_hold(arrival,cur,nxt)


def test_sector_membership_respects_saved_vertical_layers_and_counts_each_aircraft_once():
    # Find a point in the map's S1 lower / S5 upper overlap, outside Approach.
    chosen=None
    for lat in np.arange(12,15,.1):
        for lon in np.arange(107,110,.1):
            if sector_id(lat,lon,26000)=='HCM-S1' and sector_id(lat,lon,27000)=='HCM-S5':
                chosen=(lat,lon);break
        if chosen:break
    assert chosen is not None
    lat,lon=chosen
    assert sector_id(lat,lon,26500)=='HCM-S1'
    assert sector_id(lat,lon,26501)=='HCM-S5'
    assert sector_id(lat,lon,0) is None
    assert sector_id(0,0,10000) is None
    assert sector_id(lat,lon,47000) is None
    from astra.centre import centre_point
    assert sector_id(*centre_point(),100)=='APPROACH'
    assert sector_id(*centre_point(),0) is None
    values=np.asarray([[[lat,lat,0],[lon,lon,0],[26000,27000,10000],[0,0,0]]])
    masks=sample_masks(values,np.ones((1,3),dtype=bool))
    assert list(masks.sum(axis=0)[0])==[1,1,0]
