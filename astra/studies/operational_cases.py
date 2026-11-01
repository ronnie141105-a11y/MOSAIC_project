"""Generate safe native stand–runway–sector journeys for the two study cases."""
from collections import Counter
from copy import deepcopy
from datetime import datetime
from functools import lru_cache
import gzip
import json
import math
from pathlib import Path

import numpy as np

from astra.airport.aircraft import Aircraft, AircraftState
from astra.airport.simulation import Simulation
from astra.airport.graph import AirportGraph,KEY_NODES
from astra.airport.surface_policy import (MAX_ACTIVE_DEPARTURES,MINIMUM_TAKEOFF_GAP_S,
    ARRIVAL_PROTECTION_NM,ARRIVAL_PROTECTION_S,LANDING_RELEASE_FRACTION,arrival_blocks_departure)
from astra.centre import distance_nm
from astra.studies.full_cycle import _runtime, _transfer
from astra.studies.study_routes import FAMILIES, ARRIVAL_MIX, DEPARTURE_MIX, make_spec, trajectory
from astra.studies.study_sectors import SECTORS, occupancy_audit, sample_masks
from astra.studies.separation_policy import (low_terminal,TERMINAL_MIXED_HORIZONTAL_NM,TERMINAL_RADIUS_NM,TERMINAL_ALTITUDE_FT)
from astra.studies.flow_routes import (NOMINAL_MIX,OVERLOAD_MIX,TRANSFER_FIXES,
    arrival_spec,planning_path,spec_trajectory,controlled_spec)
from astra.utils.geodesy import bearing_deg, move_position

VERSION='operational-fixed-order-gate-flow-9'
WARMUP_S=3600


class AirbornePlanConflict(ValueError):
    def __init__(self,callsigns):
        self.callsigns=set(callsigns)
        super().__init__('Already-airborne plan conflicts: '+', '.join(sorted(self.callsigns)))


@lru_cache(maxsize=1)
def airport_graph():
    return AirportGraph(str(Path(__file__).resolve().parents[1]/'airport/vvts_layout.json'))


def catalog(root=None):
    from astra.studies.workbook_cases import ROOT,CASES
    root=Path(root) if root is not None else ROOT
    result=[]
    for case_id in CASES:
        folder=root/case_id
        if not (folder/'ground_tracks.json.gz').exists():continue
        m=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        label=('Sector overload' if m['study_role']=='over_capacity' else 'Nominal')+f" · {m['counts']['total']} aircraft"
        result.append(dict(case_id=case_id,key=case_id,label=label,
            description='Stand → taxi/CTOT → SID → Centre; sector → STAR → landing → taxi → stand. '+
                ('Sector occupancy intentionally exceeds its limit; safety remains enforced.' if m['study_role']=='over_capacity' else 'All sector occupancies stay within their limits.'),
            aircraft_count=m['counts']['total'],counts=m['counts'],duration_s=m['duration_s'],
            synthetic=True,category='case_study',sector_occupancy=m['sector_occupancy']))
    return result


def path_conflict(a,b,margin=False,horizontal_only=False,terminal_mixed=False):
    if not len(a) or not len(b):return False
    lo,hi=math.ceil(max(a[0,0],b[0,0])),math.floor(min(a[-1,0],b[-1,0]))
    if hi<lo:return False
    # A conservative ten-second screen avoids interpolating the entire one-second
    # overlap for remote aircraft. The margins cover motion between samples;
    # every potentially close pair still receives the exact one-second check.
    coarse=np.append(np.arange(lo,hi+1,10,dtype=float),hi)
    vertical=np.abs(np.interp(coarse,a[:,0],a[:,3])-np.interp(coarse,b[:,0],b[:,3]))
    if not horizontal_only:coarse=coarse[vertical<(1750 if margin else 1650)]
    if not len(coarse):return False
    la,lb=[np.radians(np.interp(coarse,p[:,0],p[:,1])) for p in (a,b)]
    lon_a,lon_b=[np.interp(coarse,p[:,0],p[:,2]) for p in (a,b)]
    h=np.sin((lb-la)/2)**2+np.cos(la)*np.cos(lb)*np.sin(np.radians(lon_b-lon_a)/2)**2
    if not np.any(h<math.sin(22/6880.13)**2):return False
    times=np.arange(lo,hi+1,dtype=float)
    vertical=np.abs(np.interp(times,a[:,0],a[:,3])-np.interp(times,b[:,0],b[:,3]))
    if not horizontal_only:times=times[vertical<(1100 if margin else 1000)]
    if not len(times):return False
    la,lb=[np.radians(np.interp(times,p[:,0],p[:,1])) for p in (a,b)]
    lon_a,lon_b=[np.interp(times,p[:,0],p[:,2]) for p in (a,b)]
    h=np.sin((lb-la)/2)**2+np.cos(la)*np.cos(lb)*np.sin(np.radians(lon_b-lon_a)/2)**2
    near=h<math.sin((20.3 if margin else 20)/6880.13)**2
    if not near.any():return False
    times=times[near];h=h[near]
    heading_a,heading_b=[np.degrees(np.interp(times,p[:,0],np.unwrap(np.radians(p[:,5]))))%360 for p in (a,b)]
    heading=np.abs((heading_a-heading_b+180)%360-180)
    # Always keep a 10 NM horizontal floor in Centre, including vertically
    # separated streams. The normal check additionally enforces the existing
    # 20 NM same-heading rule when vertical separation is unavailable.
    limit=np.full_like(heading,10) if horizontal_only else np.where(heading<=25,20,10)
    if terminal_mixed and not horizontal_only:
        inside=[low_terminal(*[np.interp(times,p[:,0],p[:,k]) for k in (1,2,3)]) for p in (a,b)]
        limit=np.where(inside[0]&inside[1],TERMINAL_MIXED_HORIZONTAL_NM,limit)
    limit=limit+(.3 if margin else 0)
    return bool(np.any(h<np.sin(limit/6880.13)**2))


def flight_plans(case_id,records):
    from astra.studies.workbook_cases import TYPE_MAP,CASES
    graph=airport_graph()
    stands=[]
    for stand in sorted(graph.stands(),key=lambda n:(n.y,n.x)):
        spacing=30 if CASES[case_id]['departures']>35 else 40
        if all(math.hypot(stand.x-s.x,stand.y-s.y)>=spacing for s in stands):stands.append(stand)
    dep_count=CASES[case_id]['departures']
    if len(stands)<dep_count:raise ValueError('Not enough separate departure stands')
    result=[];lanes=Counter();families=Counter()
    expanded=[]
    for direction,kind,count in (('arrival','Arrival',CASES[case_id]['arrivals']),('departure','Departure',dep_count)):
        original=[row for row in records if row['FlightType']==kind]
        expanded.extend((direction,index,original[index%len(original)],index>=len(original)) for index in range(count))
    for direction,index,row,extension in expanded:
        mix=(OVERLOAD_MIX if CASES[case_id]['study_role']=='over_capacity' else NOMINAL_MIX) if direction=='arrival' else (
            'KADUM_BMT','LANHI_ELSAS','KADUM_BMT','XOBAV_NIXIV','ANTRI_DOVIN','LANHI_ELSAS','ANTRI_PTH')
        family=mix[index%len(mix)]
        if direction=='arrival' and family=='NIXIV_VICAL' and families['PQU_BITIS']==0:family='PQU_BITIS'
        f=FAMILIES[family]
        stream='W1' if family.startswith('W1_') else family
        lane=lanes[stream];lanes[stream]+=1
        family_index=families[family];families[family]+=1
        result.append(dict(callsign=f'{"A" if direction=="arrival" else "D"}{index+1:03d}',
            source_callsign=row['Callsign'],aircraft_type=TYPE_MAP[row['AircraftType']],
            source_aircraft_type=row['AircraftType'],wake_category=row['WakeCategory'],
            direction=direction,route_family=family,procedure=f['procedure'],
            requested_fl=310+((lane+{'VTV':4,'NIXIV_VICAL':1,'SAPEN_WEST':2}.get(family,0))%6)*20 if direction=='arrival' else (270,290)[index%2],
            adep=f['origin'] if direction=='arrival' else 'VVTS',
            ades='VVTS' if direction=='arrival' else f['destination'],
            stand_id=stands[index].id if direction=='departure' else None,
            source_row=row['source_row'],source_gate=row['EntryGate'],source_route=row['OptimizedRoute'],
            synthetic_extension=extension,stream_lane=lane,descent_level_ft=(24000,26000,28000)[index%3],
            stream_from_transfer=direction=='arrival',
            mid_descent_level_ft=(14000,16000,18000)[index%3],transfer_level_ft=12000 if family=='BIBAN_BITIS' or index%2 else 10000,
            initial_stage=(1.0 if family=='W1_AC' else .80 if family in ('BIBAN_BITIS','PTH_BAOMY','VTV') else .55)
                if direction=='arrival' and family_index==0 else 0))
    departures=[f for f in result if f['direction']=='departure']
    ranks=departure_queue(tuple((f['aircraft_type'],f['stand_id']) for f in departures))
    for f,rank in zip(departures,ranks):
        f['queue_rank']=rank
        if CASES[case_id]['study_role']=='over_capacity':
            f['reference_ready_event_s']=180+rank*240
    if CASES[case_id]['study_role']=='over_capacity':
        for f in result:
            if f['direction']=='arrival':
                f.update(initial_stage=0,minimum_sequence_delay_s=300,arrival_capacity_protected=False)
    if CASES[case_id].get('gate_flow'):
        for f in result:
            if f['direction']=='arrival':
                f['initial_stage']=0
                f['minimum_sequence_delay_s']=(300 if CASES[case_id]['study_role']=='over_capacity' else 0)+(int(f['callsign'][1:])-1)*150
        from astra.studies.gate_flow import extend_regional
        extend_regional(result,CASES[case_id].get('regional_arrivals',0),CASES[case_id]['study_role']=='over_capacity')
        from astra.studies.gate_flow import startup_approach_spec
        for index,f in enumerate(result[:2]):
            f.update(startup_approach=True,startup_transfer_s=-900+index*300,initial_stage=1)
            f['fixed_initial_airborne_spec']=startup_approach_spec(f,late=index==0)
        for f in departures:
            rank=f['queue_rank'];count=4 if CASES[case_id]['study_role']=='over_capacity' else 3
            if rank<count:
                elapsed=(template(f)[-1,0]-90) if rank==0 else (900 if rank==1 else 420 if count==4 and rank==2 else 180)
                f.update(startup_airborne_departure=True,reference_ready_event_s=-math.ceil(elapsed))
            else:f['reference_ready_event_s']=180+(rank-count)*240
    return result


@lru_cache(maxsize=8)
def departure_queue(identities):
    """Use physical taxi order, so later CTOTs cannot block earlier slots."""
    sim=Simulation(airport_graph());sim.running=True;sim.speed_factor=1
    sim.allow_lineup=True;sim.minimum_departure_gap_s=120
    for i,(kind,stand) in enumerate(identities):
        ac=Aircraft(f'Q{i}',kind,'dep',stand)
        ac.off_block_time_s=60+i*520/max(1,len(identities)-1);ac.ctot_s=WARMUP_S
        sim.add_aircraft(ac);sim.assign_departure_route(ac.callsign)
    order=[]
    for _ in range(15000):
        for ac in sim.aircraft.values():
            if ac.state==AircraftState.HOLDING:ac.cleared_takeoff=True
        sim.tick(1)
        for ac in sim.aircraft.values():
            if ac.state==AircraftState.DEPARTED and ac.callsign not in order:order.append(ac.callsign)
        if len(order)==len(identities):break
    else:raise ValueError('Departure taxi queue did not clear')
    return tuple(order.index(f'Q{i}') for i in range(len(identities)))


@lru_cache(maxsize=100)
def taxi_time(stand):
    sim=Simulation(airport_graph());sim.running=True;sim.speed_factor=1
    ac=Aircraft('TAXI','A320','dep',stand)
    sim.add_aircraft(ac);sim.assign_departure_route(ac.callsign)
    for _ in range(2500):
        sim.tick(1)
        if ac.state==AircraftState.HOLDING:
            return sim.time_s,sim.departure_roll_seconds(ac)
    raise ValueError('Departure cannot reach holding point')


@lru_cache(maxsize=1)
def landing_rollout_s():
    sim=Simulation(airport_graph());sim.running=True;sim.speed_factor=1
    exit_node=airport_graph().node(KEY_NODES['RWY25R_EXIT_P5'])
    stand=min(airport_graph().stands(),key=lambda n:(n.x-exit_node.x)**2+(n.y-exit_node.y)**2).id
    ac=Aircraft('ROLLOUT','A320','arr',stand);sim.add_aircraft(ac)
    sim.assign_arrival_route(ac.callsign,KEY_NODES['RWY25R_EXIT_P5'],stand)
    start=airport_graph().node(KEY_NODES['RWY25R_SPAWN']);ac.x=start.x;ac.y=start.y;ac.state=AircraftState.LANDED
    for _ in range(600):
        sim.tick(1)
        if ac.route[ac.seg_idx] not in sim.rwy25r_nodes:return sim.time_s
    raise ValueError('Landing rollout did not vacate the runway')


def arrival_protection_start(path):
    """First entry into the six-mile takeoff-roll release cutoff."""
    from astra.airspace import load_profile
    threshold=load_profile('tsn_tma')['waypoint_data']['RW25R']
    lat,lon=np.radians(path[:,1]),np.radians(path[:,2])
    a,b=np.radians(threshold['lat']),np.radians(threshold['lon'])
    h=np.sin((lat-a)/2)**2+np.cos(lat)*np.cos(a)*np.sin((lon-b)/2)**2
    distance=6880.13*np.arcsin(np.sqrt(np.clip(h,0,1)))
    inside=np.flatnonzero(distance<=ARRIVAL_PROTECTION_NM)
    return path[inside[0],0] if len(inside) else path[-1,0]


@lru_cache(maxsize=1)
def departure_roll_s():
    sim=Simulation(airport_graph());ac=Aircraft('ROLL','A320','dep',airport_graph().stands()[0].id)
    sim.add_aircraft(ac);sim.assign_departure_route(ac.callsign)
    ac.seg_idx=ac.route.index(KEY_NODES['RWY25L_START'])
    return sim.departure_roll_seconds(ac)


def template(flight):
    from astra.studies.study_routes import departure_handoff_spec
    spec=departure_handoff_spec(flight['route_family'],flight['requested_fl'])
    spec['procedure_profile']['study_altitude_speed']=True
    path,_=spec_trajectory(spec)
    path=path.copy()
    if flight['direction']=='departure':
        path[:,0]+=44
        spec=make_spec(flight['route_family'],flight['requested_fl'])
        heading=bearing_deg(spec['lat'],spec['lon'],*spec['route_waypoints'][0])
        prefix=[]
        for t in range(44):
            lat,lon=move_position(spec['lat'],spec['lon'],heading,205*(t+1)/3600)
            prefix.append([t,lat,lon,(t+1)*2000/60,205,heading,2000])
        path=np.vstack((prefix,path))
    return path


def schedule(flights,overload,earliest_timing=None):
    placed=[];placed_ids=[];centre_streams={};transfers=[];arrival_events=[];runway_arrivals=[];timing={};counts=Counter()
    grid=np.arange(0,40001,dtype=float)
    from astra.studies.gate_flow import programme,cluster_member
    flow_config=programme(overload);gate_stream=[]
    occupied=np.zeros((len(SECTORS),len(grid)),dtype=np.int16)
    caps=np.asarray([s['capacity'] for s in SECTORS])[:,None]
    def masks(path):
        values=np.asarray([[np.interp(grid,path[:,0],path[:,k]) for k in (1,2,3)]+[np.zeros(len(grid))]])
        return sample_masks(values,((grid>=path[0,0])&(grid<=path[-1,0]))[None,:])[:,0]
    def capacity_ok(path):return (overload and not f.get('arrival_capacity_protected')) or not np.any(occupied+masks(path)>caps)
    # Admission demand is higher in the overload case; safety remains the same.
    def priority(f):
        if f.get('startup_airborne_departure'):return (-1,f['reference_ready_event_s'],f['callsign'])
        if f.get('origin_pending'):
            from astra.studies.gate_flow import regional_spec
            return (0,f['origin_requested_ctot_s']+spec_trajectory(regional_spec(f),5)[1],f['callsign'])
        if f['direction']=='arrival':
            return (0,f.get('startup_transfer_s',f.get('reference_transfer_s',f.get('minimum_sequence_delay_s',0))),f['callsign'])
        # Inbound aircraft are already flying. Resolve their streams first;
        # departures can absorb the remaining demand at their stands.
        return (3,f.get('queue_rank',int(f['callsign'][1:])-1),f['callsign'])
    ordered=sorted(flights,key=priority)
    for f in ordered:
        inbound=f['direction']=='arrival';i=counts[f['direction']];counts[f['direction']]+=1
        if inbound:
            regional=f.get('origin_pending',False)
            if regional:
                from astra.studies.gate_flow import regional_spec
            fixed=f.get('fixed_initial_airborne_spec') or (regional_spec(f) if regional else None)
            minimum=f.get('minimum_sequence_delay_s',0)
            candidates=([0] if minimum==0 else [])+list(range(max(60,math.ceil(minimum/60)*60),21601,60))
            if fixed:candidates=[0]
            if regional:candidates=range(0,28801,60)
            if f.get('initial_stage',0)>=1:candidates=[0]
            base_mid=f['mid_descent_level_ft'];initial_level=f['transfer_level_ft']
            levels=[initial_level] if f.get('fixed_clearance') else ([12000,14000,16000] if f['route_family']=='BIBAN_BITIS' else [10000,12000,14000])
            found=False
            for loops in candidates:
                for level in levels:
                    f['transfer_level_ft']=level;f['mid_descent_level_ft']=max(base_mid,level+2000)
                    p,transfer=spec_trajectory(fixed,1) if fixed else planning_path(f,loops,f.get('speed_reduction_pct',0))
                    if f.get('startup_approach'):transfer=f['startup_transfer_s']
                    if regional:
                        origin_previous=max((a.get('origin_ctot_s',-1e9) for a in ordered[:ordered.index(f)]
                            if a.get('origin_pending') and a['adep']==f['adep']),default=-1e9)
                        birth=max(f['origin_ctot_s']+loops,origin_previous+240)
                        p[:,0]+=birth;transfer+=birth
                    centre=p[p[:,0]<=transfer]
                    event=p[-1,0];window=(arrival_protection_start(p),event+landing_rollout_s())
                    transfer_ok=all(abs(transfer-t)>=(120 if fixed else 140) for t in transfers)
                    if f.get('flow_cluster')=='AC_BAOMY':
                        for old,old_transfer in gate_stream:
                            t=max(transfer,old_transfer)
                            from astra.utils.geodesy import haversine_distance_nm
                            separation=haversine_distance_nm(*[np.interp(t,path[:,0],path[:,col]) for path in (p,old) for col in (1,2)])
                            if abs(transfer-old_transfer)<flow_config['minit_s']+2 or separation<flow_config['mit_nm']+.3:
                                transfer_ok=False;break
                    # Arrival protection windows may overlap one another;
                    # the exclusion applies to departures, not arrival streams.
                    landing_ok=((f.get('startup_approach') or event%900<=600) and all(event+landing_rollout_s()+10<=old or old+landing_rollout_s()+10<=event for old in arrival_events))
                    if (transfer_ok and landing_ok
                            and all(not path_conflict(p,old,not bool(fixed),terminal_mixed=name.startswith('D')) for name,old in zip(placed_ids,placed))
                            and all(not path_conflict(centre,old,not bool(fixed),True) for old in centre_streams.values())
                            and capacity_ok(p)):
                        found=True;break
                if found:break
            if not found:
                if fixed:
                    affected=[f['callsign']]
                    for index,(name,old) in enumerate(zip(placed_ids,placed)):
                        if (path_conflict(p,old,terminal_mixed=name.startswith('D')) or (name in centre_streams and
                            (path_conflict(centre,centre_streams[name],horizontal_only=True)
                            or abs(transfer-timing[name]['arrival_transfer_s'])<120
                            or not (event+landing_rollout_s()+10<=timing[name]['arrival_touchdown_s'] or timing[name]['arrival_touchdown_s']+landing_rollout_s()+10<=event)))):
                            affected.append(name)
                    raise AirbornePlanConflict(affected)
                raise ValueError('Could not sequence already-airborne '+f['callsign'])
            if regional:f['origin_ctot_s']=birth
            f['initial_airborne_spec']=deepcopy(fixed) if fixed else arrival_spec(f,loops,f.get('speed_reduction_pct',0))
            f['sequencing_circuits']=f['initial_airborne_spec']['procedure_profile']['sequencing_circuits']
            f['sequencing_delay_s']=f['initial_airborne_spec']['procedure_profile']['sequencing_delay_s']
            requested=(spec_trajectory(fixed,1)[0][-1,0]+f['origin_requested_ctot_s']) if regional else planning_path(f,0,f.get('speed_reduction_pct',0))[0][-1,0]
            offset=f['origin_ctot_s'] if regional else 0
        else:
            original=template(f)
            offset=f.get('reference_ready_event_s',180+i*(240 if overload else 480))
            requested=offset
            if earliest_timing:offset=earliest_timing[f['callsign']]['ctot_s']
            previous=max((v['ctot_s'] for v in timing.values() if v['ctot_s'] is not None),default=-1e9)
            offset=max(offset,previous+120)
            while offset<36000:
                p=original.copy();p[:,0]+=offset
                if (all(not arrival_blocks_departure(offset-departure_roll_s(),offset,*arrival) for arrival in runway_arrivals)
                        and all(not path_conflict(p,old,True,terminal_mixed=name.startswith('A')) for name,old in zip(placed_ids,placed)) and capacity_ok(p)):break
                if f.get('startup_airborne_departure') and f.get('fixed_startup_history'):
                    raise AirbornePlanConflict([f['callsign']]+placed_ids)
                offset+=30
            else:raise ValueError('Could not construct separated native study schedule')
        placed.append(p);placed_ids.append(f['callsign'])
        occupied+=masks(p)
        if inbound:
            transfers.append(transfer);arrival_events.append(event);centre_streams[f['callsign']]=centre
            runway_arrivals.append((window[0],event,window[1]))
            if f.get('flow_cluster')=='AC_BAOMY':gate_stream.append((p,transfer))
        timing[f['callsign']]=dict(admission_s=offset if inbound else None,
            arrival_transfer_s=transfer if inbound else None,arrival_touchdown_s=event if inbound else None,
            ctot_s=offset if not inbound else None,requested_event_s=requested)
        print(f"  {f['callsign']} {f['route_family']}: event={p[-1,0]:.0f}s upstream={f.get('sequencing_delay_s',0):.0f}s",flush=True)
    return timing


def simulate(flights,timing,max_s=40000,ordered_departures=False):
    reader,airport=_runtime();airport.study_key='operational_full_cycle'
    airport.sim.allow_lineup=True
    airport.sim.minimum_departure_gap_s=MINIMUM_TAKEOFF_GAP_S
    flow_gate=airport.sim.departure_gate
    ranks={f['callsign']:f['queue_rank'] for f in flights if f['direction']=='departure'}
    stands={f['callsign']:f['stand_id'] for f in flights if f['direction']=='departure'}
    def stand_gate(ac,entering=False):
        if flow_gate and not flow_gate(ac,entering=entering):return False
        if entering:
            return not ordered_departures or not any(a.operation=='dep' and not a.is_done()
                and ranks[a.callsign]<ranks[ac.callsign] for a in airport.sim.aircraft.values())
        active=[a for a in airport.sim.aircraft.values() if a.operation=='dep'
            and a.state!=AircraftState.PARKED and not a.is_done()]
        if ordered_departures:
            if any(a.operation=='dep' and a.state==AircraftState.PARKED and ranks[a.callsign]<ranks[ac.callsign]
                   for a in airport.sim.aircraft.values()):return False
            predecessors=[a for a in airport.sim.aircraft.values() if a.operation=='dep' and not a.is_done()
                and ranks[a.callsign]<ranks[ac.callsign]]
            if predecessors:
                previous=max(predecessors,key=lambda a:ranks[a.callsign])
                left=airport.milestones.get(previous.callsign,{}).get('off_block',airport.sim.time_s)
                expected=left+taxi_time(stands[previous.callsign])[0]
                if airport.sim.time_s+taxi_time(stands[ac.callsign])[0]<expected+30:return False
        return len(active)<MAX_ACTIVE_DEPARTURES
    airport.sim.departure_gate=stand_gate
    pending=[];paths={f['callsign']:[] for f in flights};ground={}
    for f in flights:
        spec=deepcopy(f['initial_airborne_spec']) if f['direction']=='arrival' else make_spec(f['route_family'],f['requested_fl'])
        if f['direction']=='departure':spec['procedure_profile']['study_altitude_speed']=True
        cs=f['callsign'];t=timing[cs]
        if f['direction']=='departure':
            taxi,roll=taxi_time(f['stand_id'])
            ready=f.get('reference_ready_event_s',t['requested_event_s'])
            release=WARMUP_S+ready+f.get('stand_atfm_delay_s',0)-taxi-roll-45
            if f.get('queue_rank',99)==0 and ready>=0:release=WARMUP_S-taxi-30
            release=max(0,release);t['tobt_s']=release-WARMUP_S
            t['estimated_taxi_out_s']=taxi+roll+45
            airport.add_departure(callsign=cs,aircraft_type=f['aircraft_type'],stand_id=f['stand_id'],
                sid=f['procedure'],requested_fl=f['requested_fl'],destination=f['ades'],
                off_block_time_s=release,ctot_s=WARMUP_S+t['ctot_s'],airborne_spec=spec)
            airport.fpl[cs].update(route_family=f['route_family'],centre_route=spec['procedure_profile']['centre_route'])
        else:pending.append((WARMUP_S+f.get('origin_ctot_s',0),f,spec))
    for native_now in range(max_s+WARMUP_S+1):
        now=native_now-WARMUP_S
        for birth,f,spec in pending[:]:
            if birth<=native_now:
                airport.add_arrival(callsign=f['callsign'],aircraft_type=f['aircraft_type'],origin=f['adep'],
                    star=f['procedure'],requested_fl=f['requested_fl'],airborne_spec=spec)
                airport.fpl[f['callsign']]['route_family']=f['route_family']
                if spec['procedure_profile'].get('approach_transfer_complete'):
                    airport._event(f['callsign'],'approach_handoff',native_now+f.get('startup_transfer_s',0))
                pending.remove((birth,f,spec))
        current={a['callsign']:a for a in reader.list_aircraft()}
        for f in flights:
            cs=f['callsign'];marks=airport.milestones.get(cs,{})
            if cs in current and ('touchdown' not in marks or native_now<=marks['touchdown']):
                a=current[cs]
                paths[cs].append([now,*[a[k] for k in ('lat','lon','altitude_ft','ground_speed_kt','heading_deg','vertical_speed_fpm')]])
            elif f['direction']=='departure' and airport.departures[cs]['stage']=='climb':
                state=airport.departures[cs];elapsed=state['elapsed_s']
                spec=airport.airborne_specs[cs]
                heading=bearing_deg(spec['lat'],spec['lon'],*spec['route_waypoints'][0])
                lat,lon=move_position(spec['lat'],spec['lon'],heading,205*elapsed/3600)
                paths[cs].append([now,lat,lon,state['altitude_ft'],205,heading,2000])
        for cs,ac in airport.sim.aircraft.items():
            stage=airport.departures.get(cs,{})
            if stage.get('stage')=='tma':continue
            climbing=stage.get('stage')=='climb';progress=min(1,stage.get('elapsed_s',0)/45) if climbing else 0
            track=ground.setdefault(cs,dict(operation=ac.operation,route=list(ac.route),stand=ac.stand_id,
                start_s=now,samples=[]))
            row=[now,round(ac.x-275*progress,5),round(ac.y-36*progress,5),
                205 if climbing else round(ac.current_speed_mps*1.943844,5),
                stage.get('altitude_ft') if climbing else None,2000 if climbing else 0,
                'CLIMBING' if climbing else ac.state.name,ac.seg_idx]
            old=track.get('_previous')
            if not track['samples'] or track['samples'][-1][1:]!=row[1:]:
                if old and old[0]>track['samples'][-1][0]:track['samples'].append(old)
                track['samples'].append(row)
            track['_previous']=row
        complete=not pending and all(('stand_arrival' if f['direction']=='arrival' else 'fir_route_exit')
            in airport.milestones.get(f['callsign'],{}) for f in flights)
        if complete:break
        for cs,ac in airport.sim.aircraft.items():
            if ac.operation=='dep' and ac.state==AircraftState.HOLDING and not ac.cleared_takeoff:
                airport.clear_takeoff(cs)
        reader.step_simulation()
    else:
        stuck={cs:dict(state=ac.state.name,node=ac.route[ac.seg_idx] if ac.route else None,
            next=ac.route[ac.seg_idx+1] if ac.seg_idx+1<len(ac.route) else None,
            progress=ac.seg_prog,x=ac.x,y=ac.y,roll=ac.takeoff_roll_started)
            for cs,ac in airport.sim.aircraft.items() if not ac.is_done()}
        raise ValueError('Operational study failed to complete: '+json.dumps(stuck))
    for cs,track in ground.items():
        last=track.pop('_previous')
        if track['samples'][-1][0]<last[0]:track['samples'].append(last)
        track['end_s']=airport.milestones[cs]['tma_handoff']-WARMUP_S if track['operation']=='dep' else now+31
    milestones={cs:{name:t-WARMUP_S for name,t in marks.items()} for cs,marks in airport.milestones.items()}
    events=[dict(event,time_s=event['time_s']-WARMUP_S) for event in airport.events]
    return dict(paths={cs:np.asarray(rows,dtype=float) for cs,rows in paths.items()},
        ground=ground,milestones=milestones,events=events,fpl=airport.fpl,duration_s=now+30)


def surface_audit(flights,marks,paths=None):
    arrivals=[f['callsign'] for f in flights if f['direction']=='arrival']
    departures=[f['callsign'] for f in flights if f['direction']=='departure']
    violations=[]
    landing_order=sorted(arrivals,key=lambda cs:marks[cs]['touchdown'])
    for a,b in zip(landing_order,landing_order[1:]):
        if marks[b]['touchdown']<marks[a]['runway_exit']:
            violations.append(dict(arrival=b,reason='touchdown before previous arrival runway evacuation'))
    for a in arrivals:
        m=marks[a]
        if not m['touchdown']<=m['landing_two_thirds']<=m['runway_exit']<=m['stand_arrival']:
            violations.append(dict(arrival=a,reason='arrival lifecycle ordering'))
        for d in departures:
            n=marks[d]
            roll=n.get('takeoff_roll',n['runway_entry'])
            if m['touchdown']<=roll<m['runway_exit']:
                violations.append(dict(arrival=a,departure=d,reason='departure before landing runway evacuation'))
            if roll<=m['touchdown']<=n['takeoff']:
                violations.append(dict(arrival=a,departure=d,reason='touchdown during departure roll'))
            if paths is not None and arrival_blocks_departure(roll,n['takeoff'],arrival_protection_start(paths[a]),m['touchdown'],m['runway_exit']):
                violations.append(dict(arrival=a,departure=d,reason='departure starts inside 6 NM or leaves insufficient touchdown margin'))
    takeoffs=sorted((marks[cs]['takeoff'],cs) for cs in departures)
    for a,b in zip(takeoffs,takeoffs[1:]):
        if b[0]-a[0]<120:violations.append(dict(departure=b[1],reason='takeoff gap below 120 s'))
    changes=sorted([(marks[cs]['runway_entry'],1) for cs in departures]+[(marks[cs]['takeoff'],-1) for cs in departures])
    count=peak=0
    for _,change in changes:count+=change;peak=max(peak,count)
    if peak>1:violations.append(dict(reason='more than one departure on runway'))
    return dict(landing_release_fraction=LANDING_RELEASE_FRACTION,arrival_protection_nm=ARRIVAL_PROTECTION_NM,
        maximum_departures_on_runway=peak,
        arrival_protection_s=ARRIVAL_PROTECTION_S,arrival_protection_basis='6_NM_AT_ROLL_START_AND_30_S_AFTER_WHEEL_OFF',minimum_takeoff_gap_s=min((b[0]-a[0] for a,b in zip(takeoffs,takeoffs[1:])),default=None),
        violations=violations,violating_pairs=len(violations))


def stream_audit(flights,run):
    arrivals=[f for f in flights if f['direction']=='arrival']
    centre={f['callsign']:run['paths'][f['callsign']][run['paths'][f['callsign']][:,0]
        <=run['milestones'][f['callsign']]['approach_handoff']] for f in arrivals}
    pairs=[(a['callsign'],b['callsign']) for i,a in enumerate(arrivals) for b in arrivals[i+1:]
        if path_conflict(centre[a['callsign']],centre[b['callsign']],horizontal_only=True)]
    initial=[run['paths'][f['callsign']][0] for f in arrivals if run['paths'][f['callsign']][0,0]==0]
    from astra.utils.geodesy import haversine_distance_nm
    minimum=min(haversine_distance_nm(*a[1:3],*b[1:3]) for i,a in enumerate(initial) for b in initial[i+1:])
    times=np.arange(0,int(run['duration_s'])+1)
    active=np.zeros(len(times),dtype=int)
    for cs,track in run['ground'].items():
        if track['operation']!='dep':continue
        rows=track['samples'];indices=np.searchsorted([r[0] for r in rows],times,side='right')-1
        active+=np.asarray([rows[max(0,k)][6] not in ('PARKED','CLIMBING','DEPARTED')
            and track['start_s']<=t<track['end_s'] for t,k in zip(times,indices)])
    holders=sum(any(leg.get('phase')=='centre_hold' for leg in f['initial_airborne_spec']['procedure_profile']['legs']) for f in arrivals)
    return dict(centre_horizontal_conflict_pairs=pairs,minimum_initial_horizontal_nm=minimum,
        maximum_airborne_holding_aircraft=holders,maximum_committed_surface_departures=int(active.max()))


def controlled_departure_order(flights,baseline,earliest,policy):
    """All methods retain the frozen physical queue, including parked flights."""
    if policy not in ('fcfs','optimized','baseline'):raise ValueError('Unknown departure ordering policy')
    departures=[f for f in flights if f['direction']=='departure']
    def key(f):return (baseline[f['callsign']].get('queue_rank',0),f['callsign'])
    order=sorted(departures,key=key)
    for rank,f in enumerate(order):f['queue_rank']=rank
    return [f['callsign'] for f in order]


def build(case_id,records,source_hash,controls=None,baseline_manifest=None,departure_order='baseline',control_basis='reference_slot'):
    from astra.studies.workbook_cases import CASES,TRACK_FIELDS,csv_bytes,json_bytes,stamp
    spec=CASES[case_id];overload=spec['study_role']=='over_capacity'
    flights=flight_plans(case_id,records)
    earliest=None
    if controls is None and baseline_manifest is not None:
        existing={f['callsign']:f for f in baseline_manifest['flights']}
        start=datetime.fromisoformat(baseline_manifest['local_start']).timestamp()
        for f in flights:
            old=existing.get(f['callsign'])
            if old is None:continue
            if f['direction']=='arrival':
                if not spec.get('gate_flow'):f['fixed_initial_airborne_spec']=deepcopy(old['initial_airborne_spec'])
                f['fixed_clearance']=True
                for name in ('transfer_level_ft','mid_descent_level_ft','descent_level_ft'):f[name]=old[name]
            else:
                f['reference_ready_event_s']=datetime.fromisoformat(old['requested_event_utc']).timestamp()-start
                f['queue_rank']=old['queue_rank']
    if controls is not None:
        baseline={f['callsign']:f for f in baseline_manifest['flights']}
        earliest={}
        for f,control in zip(flights,controls):
            if f.get('startup_airborne_departure'):f['fixed_startup_history']=True
            old=baseline[f['callsign']]
            if f['direction']=='departure':f['queue_rank']=old.get('queue_rank',int(f['callsign'][1:])-1)
            for name in ('transfer_level_ft','mid_descent_level_ft','descent_level_ft'):
                f[name]=old[name]
            f['fixed_clearance']=True
            ground=control[1]*60 if control[0]==1 else 0
            if f['direction']=='departure':
                f['stand_atfm_delay_s']=ground
                f['reference_ready_event_s']=datetime.fromisoformat(old['requested_event_utc']).timestamp()-datetime.fromisoformat(baseline_manifest['local_start']).timestamp()
            f['speed_reduction_pct']=control[1] if control[0]==2 else 0
            if f['direction']=='arrival':
                f['reference_transfer_s']=old['transfer_time_s']
                if f.get('origin_pending'):f['origin_ctot_s']=old['origin_ctot_s']+ground
                if f.get('origin_pending') and control[0]==1:f['flow_actions']=dict(gdp_delay_s=ground)
                if spec.get('gate_flow') and control[0]==2:
                    from astra.studies.gate_flow import speed_spec
                    f['fixed_initial_airborne_spec']=speed_spec(old['initial_airborne_spec'],-control[1])
                    f['flow_actions']=dict(speed_change_pct=-control[1])
                elif control[0]==5:
                    from astra.studies.gate_flow import level_cap_spec
                    f['fixed_initial_airborne_spec']=level_cap_spec(old['initial_airborne_spec'],control[1]*100)
                    f['flow_actions']=dict(level_cap_ft=control[1]*100)
                elif control[0]==4 and f.get('origin_pending') and control[1]>=0:
                    f['origin_ctot_s']=old['origin_ctot_s']+control[1]*60
                    f['fixed_initial_airborne_spec']=deepcopy(old['initial_airborne_spec'])
                    f['flow_actions']=dict(gdp_delay_s=control[1]*60,rta_delta_s=control[1]*60)
                elif control[0]==4:
                    from astra.studies.gate_flow import realize_rta
                    realized=realize_rta(old['initial_airborne_spec'],control[1]*60)
                    if realized is None:raise AirbornePlanConflict([f['callsign']])
                    f['fixed_initial_airborne_spec']=realized['spec'];f['flow_actions']=realized['actions']
                else:f['fixed_initial_airborne_spec']=(controlled_spec(old['initial_airborne_spec'],f['speed_reduction_pct'])
                    if f['speed_reduction_pct'] else deepcopy(old['initial_airborne_spec']))
                if control[0]==4:f['flow_actions']['rta_target_s']=old['transfer_time_s']+control[1]*60
            anchor=old['ctot_s']
            if (f['direction']=='departure' and control[0]==1 and control_basis=='requested_ready_time'
                    and old.get('origin_status_at_planning','PARKED')=='PARKED'):
                anchor=f['reference_ready_event_s']
            earliest[f['callsign']]=dict(admission_s=(datetime.fromisoformat(old['first_track_utc']).timestamp()-datetime.fromisoformat(baseline_manifest['local_start']).timestamp()+ground) if f['direction']=='arrival' else None,
                ctot_s=anchor+ground if f['direction']=='departure' else None)
        planned_departure_order=controlled_departure_order(flights,baseline,earliest,departure_order)
    timing=schedule(flights,overload,earliest)
    initial_ctots={cs:item['ctot_s'] for cs,item in timing.items()}
    for attempt in range(16):
        # Taxi releases and runway entry follow the same physical queue as CTOT
        # planning, including the reference case. Otherwise a shorter taxi route
        # can overtake the planned leader and invalidate its airborne separation.
        run=simulate(flights,timing,ordered_departures=True)
        conflicts=[(a['callsign'],b['callsign']) for i,a in enumerate(flights) for b in flights[i+1:]
            if path_conflict(run['paths'][a['callsign']],run['paths'][b['callsign']],terminal_mixed=a['direction']!=b['direction'])]
        surface=surface_audit(flights,run['milestones'],run['paths'])
        if controls is not None and departure_order in ('fcfs','optimized'):
            actual_order=sorted(planned_departure_order,key=lambda cs:run['milestones'][cs]['takeoff'])
            surface.update(departure_order_policy=departure_order,departure_order_preserved=actual_order==planned_departure_order)
            if actual_order!=planned_departure_order:raise ValueError('Native departure order differs from the controlled queue')
        streams=stream_audit(flights,run)
        occupancy=occupancy_audit(run['paths'])
        transfers=sorted(run['milestones'][f['callsign']]['approach_handoff'] for f in flights if f['direction']=='arrival')
        transfer_gap=min(b-a for a,b in zip(transfers,transfers[1:]))
        if controls is not None and spec.get('gate_flow'):
            arrivals=[f for f in flights if f['direction']=='arrival']
            for i,a in enumerate(arrivals):
                for b in arrivals[i+1:]:
                    if a['route_family']!=b['route_family']:continue
                    actual=run['milestones'][a['callsign']]['approach_handoff']-run['milestones'][b['callsign']]['approach_handoff']
                    if actual*(a['reference_transfer_s']-b['reference_transfer_s'])<=0:conflicts.append((a['callsign'],b['callsign']))
        revisions={f['callsign']:run['milestones'][f['callsign']]['takeoff'] for f in flights
            if f['direction']=='departure' and abs(run['milestones'][f['callsign']]['takeoff']-timing[f['callsign']]['ctot_s'])>.01}
        print(json.dumps(dict(case=case_id,attempt=attempt+1,duration_s=run['duration_s'],
            airborne_conflict_pairs=len(conflicts),centre_horizontal_conflict_pairs=len(streams['centre_horizontal_conflict_pairs']),
            surface_violations=surface['violating_pairs'],ctot_revisions=len(revisions),
            peaks={s['id']:s['peak'] for s in occupancy['sectors']})),flush=True)
        if not conflicts and not streams['centre_horizontal_conflict_pairs'] and not surface['violations'] and transfer_gap>=120:
            if streams['maximum_committed_surface_departures']>MAX_ACTIVE_DEPARTURES:raise ValueError('Too many active surface departures')
            if streams['maximum_airborne_holding_aircraft']>6:raise ValueError('Too many holding aircraft')
            if not revisions:break
            for cs,t in revisions.items():timing[cs]['ctot_s']=max(t,timing[cs]['ctot_s'])
            continue
        delayed=set(b for a,b in conflicts)
        delayed.update(b for a,b in streams['centre_horizontal_conflict_pairs'])
        delayed.update(v['departure'] for v in surface['violations'] if 'departure' in v)
        if transfer_gap<120:
            ordered=sorted(((run['milestones'][f['callsign']]['approach_handoff'],f['callsign']) for f in flights if f['direction']=='arrival'))
            delayed.update(b[1] for a,b in zip(ordered,ordered[1:]) if b[0]-a[0]<120)
        if controls is not None and any(f['direction']=='arrival' and f['callsign'] in delayed for f in flights):
            involved=set(delayed)
            for a,b in conflicts+streams['centre_horizontal_conflict_pairs']:
                if a in delayed or b in delayed:involved.update((a,b))
            if transfer_gap<120:
                involved.update(a[1] for a,b in zip(ordered,ordered[1:]) if b[0]-a[0]<120)
            raise AirbornePlanConflict(f['callsign'] for f in flights if f['direction']=='arrival' and f['callsign'] in involved)
        for cs in delayed:
            f=next(f for f in flights if f['callsign']==cs)
            if f['direction']=='arrival':f['minimum_sequence_delay_s']=f.get('sequencing_delay_s',0)+120
            else:earliest=earliest or {a['callsign']:dict(ctot_s=timing[a['callsign']]['ctot_s'],admission_s=0) for a in flights}
            if f['direction']=='departure':earliest[cs]['ctot_s']=timing[cs]['ctot_s']+120
        timing=schedule(flights,overload,earliest)
    else:raise ValueError('Could not satisfy native surface/airborne separation')
    if controls is None and not overload and occupancy['total_excess_aircraft_seconds']:
        raise ValueError('Nominal case exceeds a sector occupancy limit')
    if controls is None and overload and not occupancy['total_excess_aircraft_seconds']:
        raise ValueError('Overload case does not exceed a sector occupancy limit')
    run['duration_s']=max(10800,run['duration_s'])
    for track in run['ground'].values():
        if track['operation']=='arr':track['end_s']=run['duration_s']+1
    start=datetime.fromisoformat(spec['local_start']).timestamp()
    metadata=[];tracks=[];plans=[];flight_rows=[]
    queue_rank={cs:i for i,(_,cs) in enumerate(sorted((run['milestones'][f['callsign']]['takeoff'],f['callsign']) for f in flights if f['direction']=='departure'))}
    for f in flights:
        cs=f['callsign'];p=run['paths'][cs];m=run['milestones'][cs]
        inbound=f['direction']=='arrival';event=m['touchdown' if inbound else 'takeoff']
        if inbound:
            position=f['initial_airborne_spec']['procedure_profile']['approach_transfer_position']
            transfer=dict(time_s=m['approach_handoff'],lat=position[0],lon=position[1])
        else:transfer=_transfer(p,f['direction'])
        completion=m['stand_arrival' if inbound else 'fir_route_exit']
        if not inbound:f['queue_rank']=queue_rank[cs]
        origin=f.get('origin_ctot_s',-7200) if inbound else event
        meta=dict(**f,flight_id=case_id+':'+cs,source_sheet=spec['sheet'],runway='25R' if inbound else '25L',
            centre_route=run['fpl'][cs]['centre_route'],stand=run['fpl'][cs]['stand'],
            planned_event_utc=stamp(start+event),simulated_slot_utc=stamp(start+event),
            requested_event_utc=stamp(start+timing[cs]['requested_event_s']),
            first_track_utc=stamp(start+p[0,0]),last_track_utc=stamp(start+p[-1,0]),
            completed_s=completion,transfer_time_s=transfer['time_s'],transfer_utc=stamp(start+transfer['time_s']),
            transfer_lat=transfer['lat'],transfer_lon=transfer['lon'],
            origin_takeoff_utc=stamp(start+origin),ground_delay_eligible=(not inbound and origin>=0) or f.get('origin_pending',False),
            scheduled_offblock_utc=stamp(start+origin-900) if inbound else stamp(start+m['off_block']),
            actual_offblock_utc=None if inbound else stamp(start+m['off_block']),
            tobt_s=None if inbound else m['off_block'],
            ready_offblock_time_s=None if inbound else timing[cs]['tobt_s'],
            estimated_taxi_out_s=None if inbound else timing[cs]['estimated_taxi_out_s'],
            off_block_time_s=m.get('off_block'),ctot_s=event if not inbound else None,
            original_ctot_s=timing[cs]['ctot_s'],ctot_revision_reason='Native runway and taxi coordination; final plan matches wheel-off',
            initial_requested_ctot_s=initial_ctots[cs],
            origin_status_at_planning=('ORIGIN_STAND' if f.get('origin_pending') else 'ALREADY_AIRBORNE') if inbound else ('ALREADY_AIRBORNE' if origin<0 else next((row[6] for row in reversed(run['ground'][cs]['samples']) if row[0]<=0),'PARKED')),synthetic=True,
            approach_transfer_fix=TRANSFER_FIXES[f['route_family']] if inbound else 'VVTS_40NM',
            approach_transfer_position=[transfer['lat'],transfer['lon']],
            speed_control_eligible=inbound and f.get('initial_stage',0)<1,
            initial_altitude_ft=float(np.interp(0,p[:,0],p[:,3])),initial_ground_speed_kt=float(np.interp(0,p[:,0],p[:,4])),
            waypoint_times_s={name:t-WARMUP_S for name,t in run['fpl'][cs].get('study_waypoint_times',{}).items()},
            evidence='synthetic_native_full_cycle_sector_study',actual_takeoff_verified=False,actual_landing_verified=False,
            simulated_delay_min=0)
        if controls is not None:
            old=baseline[cs];control=controls[len(metadata)]
            meta.update(planned_event_utc=old['planned_event_utc'],requested_event_utc=old['requested_event_utc'],
                simulated_delay_min=max(0,(start+event-datetime.fromisoformat(old['simulated_slot_utc']).timestamp())/60),
                atfm_measure=control[0],atfm_level=control[1],
                ga_ground_delay_min=control[1] if control[0]==1 else 0,
                safety_metering_delay_min=max(0,(timing[cs]['admission_s' if inbound else 'ctot_s']-earliest[cs]['admission_s' if inbound else 'ctot_s'])/60))
        if f.get('origin_pending'):
            meta.update(origin_requested_tobt_s=max(0,f['origin_requested_ctot_s']-f['origin_taxi_s']),
                origin_tobt_s=max(0,origin-f['origin_taxi_s']),origin_ctot_s=origin,
                scheduled_offblock_utc=stamp(start+max(0,origin-f['origin_taxi_s'])),
                origin_surface_state='VIRTUAL_STAND_AND_TAXI',
                origin_requested_ctot_s=f['origin_requested_ctot_s'])
        if inbound:
            meta['cto_s']=transfer['time_s']
            if meta.get('flow_actions',{}).get('rta_target_s') is not None:
                meta['flow_actions']['rta_error_s']=transfer['time_s']-meta['flow_actions']['rta_target_s']
                meta['flow_actions']['rta_status']='MET' if abs(meta['flow_actions']['rta_error_s'])<=15 else 'REVISED_BY_SAFETY_METERING'
                meta['flow_actions']['cleared_cto_s']=transfer['time_s']
        metadata.append(meta)
        for row in p:
            t,lat,lon,alt,speed,heading,vs=map(float,row)
            tracks.append(dict(flight_id=meta['flight_id'],callsign=cs,aircraft_type=f['aircraft_type'],adep=f['adep'],ades=f['ades'],
                time_utc=stamp(start+t),lat=lat,lon=lon,altitude_ft=alt,ground_speed_kt=speed,heading_deg=heading,
                vertical_speed_fpm=vs,on_ground=False,source='SYNTHETIC_NATIVE_OPERATIONAL'))
        plans.append(dict(callsign=cs,direction=f['direction'],adep=f['adep'],origin_name=f.get('origin_name',f['adep']),ades=f['ades'],route_family=f['route_family'],
            procedure=f['procedure'],requested_fl=f['requested_fl'],stand=meta['stand'],
            offblock_utc=meta['scheduled_offblock_utc'],origin_takeoff_utc=meta['origin_takeoff_utc'],
            ctot_utc=meta['origin_takeoff_utc'] if not inbound or f.get('origin_pending') else '',
            tobt_utc=meta['scheduled_offblock_utc'] if not inbound or f.get('origin_pending') else '',
            cto_utc=meta['transfer_utc'] if inbound else '',origin_pending=f.get('origin_pending',False),
            sector_admission_utc=meta['first_track_utc'] if inbound else '',
            runway_event_utc=meta['simulated_slot_utc'],stand_arrival_utc=stamp(start+completion) if inbound else '',synthetic=True))
        flight_rows.append(dict(callsign=cs,aircraft_type=f['aircraft_type'],adep=f['adep'],ades=f['ades'],
            scheduled_departure_utc=meta['origin_takeoff_utc'],scheduled_arrival_utc=meta['planned_event_utc'] if inbound else '',
            actual_takeoff_utc='',actual_landing_utc='',runway=meta['runway'],source='synthetic_native_operation'))
    counts=dict(total=len(flights),arrivals=sum(f['direction']=='arrival' for f in flights),departures=sum(f['direction']=='departure' for f in flights))
    limitations=['Synthetic study routes, levels, scheduling and sector limits; not operational procedures.',
        'Capacity is simultaneous airborne occupancy within the displayed study sector, not movements/hour or whole-screen count.',
        'Both cases enforce airborne and runway safety. Only the overload case intentionally exceeds a sector occupancy limit.',
        'Mixed arrival/departure pairs use 5 NM or 1,000 ft when both are within 40 NM and at or below 10,000 ft; Centre and same-direction-pair rules retain 10/20 NM.',
        'Origin-airport transit for arrivals is a timing assumption outside the modelled upstream admission.',
        'Bounded taxi queues, lineup, full runway evacuation, a 6 NM takeoff-roll cutoff, 30 seconds from wheel-off to next touchdown, and arrival parking are included.',
        'Named airway coordinates are saved references; non-network joins are labelled assumed connectors.']
    settings=dict(sector_capacity_basis='simultaneous_occupancy',sectors=list(SECTORS),
        horizontal_nm=10,same_heading_horizontal_nm=20,same_heading_tolerance_deg=25,vertical_ft=1000,
        terminal_mixed_horizontal_nm=TERMINAL_MIXED_HORIZONTAL_NM,terminal_radius_nm=TERMINAL_RADIUS_NM,terminal_altitude_ft=TERMINAL_ALTITUDE_FT,
        planning_min=0,ground_levels_min=list(range(5,61,5)),speed_levels_pct=[5,10,15],
        ground_cost_per_min=1,speed_cost_per_delay_min=2,airborne_hold_cost_per_min=2,penalty_lambda=10000,
        arrival_transfer_minimum_gap_s=120,search_sample_s=20,validation_sample_s=1,
        runway_landing_release_fraction=LANDING_RELEASE_FRACTION,minimum_takeoff_gap_s=MINIMUM_TAKEOFF_GAP_S,
        runway_arrival_protection_nm=ARRIVAL_PROTECTION_NM,runway_arrival_protection_s=ARRIVAL_PROTECTION_S,
        runway_arrival_protection_basis='ROLL_START_DISTANCE_AND_POST_TAKEOFF_TOUCHDOWN_MARGIN',
        initial_airborne_arrivals=True,initial_surface_state='BOUNDED_TAXI_QUEUE_REST_AT_STANDS',
        taxi_release_basis='REQUESTED_READINESS_AND_QUEUE_SPACE',
        centre_arrival_horizontal_spacing=True,maximum_airborne_holding_aircraft=0,maximum_active_surface_departures=MAX_ACTIVE_DEPARTURES,
        descent_maximum_fpm=3500,cruise_speed_band_kt=[450,500])
    manifest=dict(schema_version=3,case_id=case_id,label='Nominal · full airport / sector cycle' if not overload else 'Sector overload · full airport / sector cycle',
        study_role=spec['study_role'],local_start=spec['local_start'],local_end=stamp(start+10800),duration_s=run['duration_s'],
        counts=counts,basis='Native stand / taxi / CTOT / SID / sector and arrival / rollout / taxi / stand journeys',
        source=dict(workbook='VVTS_scenarios.xlsx',sheet=spec['sheet'],sha256=source_hash,
            original_rows=len(records),source_rows_used=len({f['source_row'] for f in flights}),
            source_rows_omitted=len(records)-len({f['source_row'] for f in flights}),
            synthetic_extensions=sum(f['synthetic_extension'] for f in flights)),
        generated_by=VERSION,scenario_kind='native_operational_sector_study',native_connected_tracks=True,connected_fir=True,
        arrival_initial_state_basis='PRESERVED_VALIDATED_TRAFFIC' if baseline_manifest else 'GENERATED_UPSTREAM_STREAM',
        ground_replay_file='ground_tracks.json.gz',study_settings=settings,planning_utc=stamp(start),
        baseline_sequencing='SAFETY_CONSTRAINED_NATIVE_EXECUTION',supported_methods=['RECONSTRUCTED','NO_CONTROL','TEAM_GROUND','TEAM_MIXED'],
        limitations=limitations,flights=metadata,sector_occupancy=occupancy,surface_audit=surface,
        stream_audit=streams,
        separation_audit=dict(sample_s=1,violating_pairs=0,terminal_mixed_horizontal_nm=TERMINAL_MIXED_HORIZONTAL_NM,
            terminal_radius_nm=TERMINAL_RADIUS_NM,terminal_altitude_ft=TERMINAL_ALTITUDE_FT,
            arrival_transfer_minimum_s=120,minimum_arrival_transfer_gap_s=transfer_gap))
    if overload:
        arrival_occupancy=occupancy_audit({f['callsign']:run['paths'][f['callsign']] for f in flights if f['direction']=='arrival'})
        manifest['case_design']=dict(version='controllable-bank-1',minimum_upstream_lead_s=1200,
            departure_readiness_bank='1200..2190 s (12 parked departures), then 3000..4800 s; one committed leader',
            arrival_only_excess_aircraft_seconds=arrival_occupancy['total_excess_aircraft_seconds'],
            acceptance_basis='Physical feasibility and controllability, independent of optimizer outcomes')
    manifest['control_clock']=control_basis
    if controls is not None:manifest.update(departure_order_policy='FIXED_FIFO',planned_departure_order=planned_departure_order)
    if spec.get('gate_flow'):
        from astra.studies.gate_flow import programme,audit
        manifest['flow_programme']=programme(overload)
        manifest['flow_audit']=audit(flights,run['paths'],run['milestones'],manifest['flow_programme'])
        manifest['fixed_departure_order']=True
        manifest['origin_airports']=sorted({f['adep'] for f in flights if f.get('origin_pending')}|{'VVTS'})
    summary=dict(counts=counts,separation_audit=manifest['separation_audit'],surface_audit=surface,sector_occupancy=occupancy,
        duration_s=run['duration_s'],all_departures_spawn_at_stands=False,all_arrivals_park_at_stands=True,
        all_arrivals_visible_at_start=all(run['paths'][f['callsign']][0,0]==0 for f in flights if f['direction']=='arrival' and not f.get('origin_pending')),
        regional_arrivals_at_origins=sum(bool(f.get('origin_pending')) for f in flights),
        initial_departure_states=dict(Counter(track['samples'][0][6] for track in run['ground'].values() if track['operation']=='dep')),
        stream_audit=streams,
        route_distribution=dict(Counter(f['route_family'] for f in flights)),source_sha256=source_hash)
    ground_data=dict(flights=run['ground'],milestones=run['milestones'],events=run['events'])
    return {'manifest.json':json_bytes(manifest),'summary.json':json_bytes(summary),
        'source_rows.json':json_bytes(records),'tracks.csv':csv_bytes(TRACK_FIELDS,tracks),
        'ground_tracks.json.gz':gzip.compress(json.dumps(ground_data,separators=(',',':')).encode(),mtime=0),
        'planning.csv':csv_bytes(list(plans[0]),plans),'fpl.csv':csv_bytes(list(plans[0]),plans),
        'flights.csv':csv_bytes(list(flight_rows[0]),flight_rows),
        'capacity.csv':csv_bytes(['sector_id','capacity_aircraft','basis'],[dict(sector_id=s['id'],capacity_aircraft=s['capacity'],basis='simultaneous_airborne_in_sector') for s in SECTORS]),
        'demand.csv':csv_bytes(['callsign','requested_event_utc','scheduled_event_utc'],[dict(callsign=f['callsign'],requested_event_utc=f['requested_event_utc'],scheduled_event_utc=f['planned_event_utc']) for f in metadata])}
