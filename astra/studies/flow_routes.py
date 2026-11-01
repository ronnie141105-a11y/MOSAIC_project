"""Already-airborne feeders, staged descent and explicit upstream sequencing.

All geometry is generated from saved waypoint coordinates. The added descent
stations, cruise extensions and sequencing circuits are synthetic assumptions.
"""
from copy import deepcopy
from bisect import bisect_right
from dataclasses import replace
from functools import lru_cache
import json
import math
import numpy as np
from astra.centre import airway_network,distance_nm
from astra.interface.traffic_state import AircraftState
from astra.studies.study_routes import FAMILIES,make_spec
from astra.trajectory.procedure import advance_procedure
from astra.trajectory.study_performance import altitude_speed
from astra.utils.geodesy import bearing_deg,haversine_distance_nm,move_position

TRANSFER_FIXES=dict(W1_AC='AC',W1_LKH='DALAP',PTH_BAOMY='BAOMY',
    BIBAN_BITIS='BITIS',PQU_BITIS='BITIS',VTV='VTV',SAPEN_WEST='SAPEN',NIXIV_VICAL='VICAL')
NOMINAL_MIX=('W1_AC','BIBAN_BITIS','PTH_BAOMY','W1_LKH','NIXIV_VICAL',
    'SAPEN_WEST','W1_AC','BIBAN_BITIS','VTV','W1_LKH','PTH_BAOMY')
OVERLOAD_MIX=('W1_AC','BIBAN_BITIS','W1_LKH','PTH_BAOMY','SAPEN_WEST',
    'W1_AC','BIBAN_BITIS','W1_LKH','NIXIV_VICAL','PTH_BAOMY',
    'W1_AC','BIBAN_BITIS','W1_LKH','VTV','W1_AC','BIBAN_BITIS',
    'W1_LKH','PTH_BAOMY','SAPEN_WEST','W1_AC','BIBAN_BITIS',
    'W1_LKH','NIXIV_VICAL','PTH_BAOMY','W1_AC','BIBAN_BITIS',
    'W1_LKH','VTV','W1_AC','BIBAN_BITIS','PTH_BAOMY',
    'SAPEN_WEST','W1_AC','BIBAN_BITIS','W1_LKH','NIXIV_VICAL',
    'PTH_BAOMY','W1_AC','BIBAN_BITIS','W1_LKH','W1_AC','BIBAN_BITIS')


def along(points,distance):
    for a,b in zip(points,points[1:]):
        length=haversine_distance_nm(*a,*b)
        if distance<=length:return move_position(*a,bearing_deg(*a,*b),max(0,distance))
        distance-=length
    return points[-1]


def holding_pattern(spec,delay_s):
    """An 8 NM radius racetrack with variable straight legs, no tight turns.

    Its long axis points away from the feeder. Extra delay changes the straight
    length/lap count, rather than stopping the aircraft or requiring full laps
    in six-minute scheduling increments.
    """
    entry=(spec['lat'],spec['lon'])
    target=next(p for p in spec['route_waypoints'] if haversine_distance_nm(*entry,*p)>.001)
    heading=bearing_deg(*entry,*target)
    def coordinates(straight):
        local=[]
        if straight>1e-6:local.append((0,straight))
        local.extend((-8+8*math.cos(k*math.pi/16),straight+8*math.sin(k*math.pi/16)) for k in range(1,17))
        if straight>1e-6:local.append((-16,0))
        local.extend((-8+8*math.cos(math.pi+k*math.pi/16),8*math.sin(math.pi+k*math.pi/16)) for k in range(1,17))
        result=[]
        for forward,left in local:
            p=move_position(*entry,heading if forward>=0 else heading+180,abs(forward))
            result.append(move_position(*p,heading-90 if left>=0 else heading+90,abs(left)))
        result[-1]=entry
        return result
    def length(points):return sum(haversine_distance_nm(*a,*b) for a,b in zip([entry]+points,points))
    base=length(coordinates(0));speed=spec['speed_kt']
    distance=max(base,delay_s*speed/3600)
    laps=max(1,int(distance/base));straight=max(0,(distance/laps-base)/2)
    for _ in range(3):straight=max(0,straight+(distance/laps-length(coordinates(straight)))/2)
    points=coordinates(straight)
    return points,laps,length(points)*laps/speed*3600


def _seed_spec(flight,loops=0,speed_reduction_pct=0):
    family=flight['route_family'];definition=FAMILIES[family]
    spec=make_spec(family,flight['requested_fl'])
    profile=spec['procedure_profile'];nodes,_=airway_network()
    transfer=TRANSFER_FIXES[family]
    named=[(name,nodes[name]) for name in definition['fixes']]
    gate_index=next(i for i,(name,_) in enumerate(named) if name==transfer)
    feeder=[coord for _,coord in named[:gate_index+1]]
    # Short feeders receive enough upstream distance for the same staged descent.
    length=sum(haversine_distance_nm(*a,*b) for a,b in zip(feeder,feeder[1:]))
    inbound_heading=bearing_deg(*feeder[0],*feeder[1]) if len(feeder)>1 else bearing_deg(*feeder[0],*spec['route_waypoints'][-1])
    if length<110:
        feeder.insert(0,move_position(*feeder[0],inbound_heading+180,120-length))
    length=sum(haversine_distance_nm(*a,*b) for a,b in zip(feeder,feeder[1:]))
    tod=feeder[0]
    if family.startswith('W1_'):
        cruise_anchor=nodes['PLK'];tod=nodes['BMT']
    else:cruise_anchor=tod
    if not family.startswith('W1_'):inbound_heading=bearing_deg(*feeder[0],*feeder[1])
    heading=bearing_deg(*cruise_anchor,*tod) if family.startswith('W1_') else inbound_heading
    lane=flight['stream_lane']
    # Aircraft occupy distinct points along the feeder, rather than vertical
    # stacks at nearly identical radar positions.
    entry=move_position(*cruise_anchor,heading+180,lane*30)
    level=flight['requested_fl']*100
    route=[];legs=[]
    def leg(name,point,altitude,phase='centre'):
        route.append(tuple(point));legs.append(dict(fix=name,target_altitude_ft=altitude,
            nominal_speed_kt=altitude_speed(altitude),phase=phase,max_ias_kt=None,
            study_speed_factor=1-speed_reduction_pct/100))
    if family.startswith('W1_'):
        leg('PLK',nodes['PLK'],level,'cruise');legs[-1]['record_event']=True
    leg('TOP_OF_DESCENT' if not family.startswith('W1_') else 'BMT',tod,level,'cruise')
    if family.startswith('W1_'):
        feeder=[coord for _,coord in named[:gate_index+1]]
        length=sum(haversine_distance_nm(*a,*b) for a,b in zip(feeder,feeder[1:]))
    legs[-1]['record_event']=True
    stages=((.25,flight['descent_level_ft']),(.55,flight['mid_descent_level_ft']),
            (.80,max(12000,flight['transfer_level_ft'])),(1.0,flight['transfer_level_ft']))
    stations={round(length*fraction,6):(f'DESCENT_{int(fraction*100)}',alt) for fraction,alt in stages}
    passed=0
    for index in range(1,len(feeder)):
        passed+=haversine_distance_nm(*feeder[index-1],*feeder[index])
        if passed<length-1e-5:stations.setdefault(round(passed,6),(next((n for n,c in named if c==feeder[index]),'FEEDER'),None))
    for distance,(name,alt) in sorted(stations.items()):
        fraction=distance/length
        if alt is None:
            previous=(0,level)
            for end,target in stages:
                if fraction<=end:
                    alt=previous[1]+(target-previous[1])*(fraction-previous[0])/(end-previous[0]);break
                previous=(end,target)
        leg(transfer if distance>=length-1e-5 else name,along(feeder,distance),alt)
        legs[-1]['record_event']=True
    # Rejoin the already compiled terminal procedure after the named handoff.
    original_names=[l['fix'] for l in profile['legs']]
    index=original_names.index(transfer) if transfer in original_names else None
    if index is None:raise ValueError('Transfer fix missing from compiled route: '+transfer)
    route+=list(map(tuple,spec['route_waypoints'][index+1:]))
    terminal=deepcopy(profile['legs'][index+1:])
    for item in terminal:item['target_altitude_ft']=min(item['target_altitude_ft'],flight['transfer_level_ft'])
    release={'W1_AC':'VIKEP','W1_LKH':'VIKEP','PTH_BAOMY':'ANSUP',
        'BIBAN_BITIS':'LETRO','PQU_BITIS':'LETRO','NIXIV_VICAL':'LETRO','VTV':'RUNSI','SAPEN_WEST':'NUNGO'}[family]
    names=[item['fix'] for item in terminal]
    merge=profile['direct_to_fix']
    if release in names and merge in names:
        keep=list(range(names.index(release)+1))+list(range(names.index(merge),len(names)))
        terminal=[terminal[i] for i in keep]
        appended=list(map(tuple,spec['route_waypoints'][index+1:]))
        route=route[:-len(appended)]+[appended[i] for i in keep]
        profile.update(direct_from_fix=release,study_terminal_direct=True)
    legs+=terminal
    initial_stage=flight.get('initial_stage',0)
    already_transferred=initial_stage>=1
    if initial_stage:
        initial_fix=transfer if already_transferred else f'DESCENT_{round(initial_stage*100)}'
        index=next(i for i,item in enumerate(legs) if item['fix']==initial_fix)
        entry=route[index];level=legs[index]['target_altitude_ft']
        route=route[index+1:];legs=legs[index+1:]
    profile.update(legs=legs,study_altitude_speed=True,study_max_descent_fpm=3500,
        approach_transfer_fix=transfer,
        approach_transfer_position=list(nodes[transfer]),sequencing_circuits=0,sequencing_delay_s=0,
        centre_route=('PLK → ' if family.startswith('W1_') else '')+' → '.join(definition['fixes']),
        staged_descent=dict(top_of_descent='BMT' if family.startswith('W1_') else 'TOP_OF_DESCENT',
            distance_to_transfer_nm=length,first_level_ft=flight['descent_level_ft'],
            midpoint_level_ft=flight['mid_descent_level_ft'],transfer_level_ft=flight['transfer_level_ft']))
    if already_transferred:profile.update(approach_transfer_complete=True,approach_transfer_time_s=0)
    spec.update(lat=entry[0],lon=entry[1],altitude_ft=level,speed_kt=altitude_speed(level)*(1-speed_reduction_pct/100),
        heading_deg=bearing_deg(*entry,*next(point for point in route if haversine_distance_nm(*entry,*point)>.001)),route_waypoints=route)
    if loops:
        points,laps,delay=holding_pattern(spec,loops)
        prefix=[dict(fix=f'SEQUENCE_{i+1}',target_altitude_ft=level,nominal_speed_kt=altitude_speed(level),
            phase='centre_hold',max_ias_kt=None,study_speed_factor=1-speed_reduction_pct/100) for i in range(len(points))]
        prefix[-1]['sequence_end']=True
        profile.update(sequencing_pattern=dict(route=points,legs=deepcopy(prefix),remaining_laps=laps-1),
            sequencing_circuits=laps,sequencing_delay_s=delay,legs=prefix+legs)
        spec['route_waypoints']=points+route
        spec['heading_deg']=bearing_deg(*entry,*points[0])
    return spec


def arrival_spec(flight,sequence_s=0,speed_reduction_pct=0):
    """Sequence by distance still to fly, with no circular holding patterns."""
    keys=('route_family','requested_fl','stream_lane','descent_level_ft',
          'mid_descent_level_ft','transfer_level_ft','initial_stage','stream_from_transfer')
    values={key:flight[key] for key in keys if key in flight}
    return deepcopy(_stream_spec(json.dumps(values,sort_keys=True),float(sequence_s),speed_reduction_pct))


@lru_cache(maxsize=512)
def _stream_spec(encoded,sequence_s,reduction):
    flight=json.loads(encoded)
    seed=_seed_spec(dict(flight,initial_stage=1) if flight.get('stream_from_transfer') else flight,0,reduction)
    spec=seed
    if sequence_s>0:
        full=_seed_spec(dict(flight,initial_stage=0),0,reduction)
        checkpoints=_stream_checkpoints(json.dumps(full,sort_keys=True))
        seed_path,_=spec_trajectory(seed)
        advance_s=checkpoints[-1][0]-seed_path[-1,0]-sequence_s
        spec=full
        if advance_s>0:
            projection=dict(kind='crop',advance_s=advance_s)
            index=bisect_right([row[0] for row in checkpoints],advance_s)-1
            elapsed,state,route,profile=checkpoints[index]
            remaining=advance_s-elapsed
            while remaining>1e-8:
                dt=min(5,remaining);step=advance_procedure(state,route,profile,dt)
                state,route,profile=step.aircraft,step.remaining_route,step.profile;remaining-=dt
            profile=deepcopy(profile)
            profile.pop('study_waypoint_times',None)
            if profile.get('approach_transfer_complete'):profile['approach_transfer_time_s']=0
            spec.update(lat=state.lat,lon=state.lon,altitude_ft=state.altitude_ft,
                speed_kt=state.ground_speed_kt,heading_deg=state.heading_deg,
                route_waypoints=route,procedure_profile=profile)
        else:
            distance=-advance_s*full['speed_kt']/3600
            projection=dict(kind='prefix',duration_s=-advance_s)
            anchor=(full['lat'],full['lon'])
            entry=move_position(*anchor,full['heading_deg']+180,distance)
            leg=dict(fix='UPSTREAM_STREAM',target_altitude_ft=full['altitude_ft'],
                nominal_speed_kt=full['speed_kt'],phase='cruise',max_ias_kt=None,
                study_speed_factor=1-reduction/100)
            spec.update(lat=entry[0],lon=entry[1],heading_deg=bearing_deg(*entry,*anchor),
                route_waypoints=[anchor]+full['route_waypoints'])
            spec['procedure_profile']['legs']=[leg]+full['procedure_profile']['legs']
        spec['procedure_profile']['stream_projection']=projection
    spec['procedure_profile'].update(sequencing_circuits=0,sequencing_delay_s=sequence_s,
        airborne_sequencing_kind='FORWARD_UPSTREAM_STREAM',maximum_holding_aircraft=0)
    return spec


@lru_cache(maxsize=128)
def _stream_checkpoints(encoded):
    spec=json.loads(encoded);route=spec['route_waypoints'];profile=spec['procedure_profile']
    state=AircraftState('TEMPLATE',spec['lat'],spec['lon'],spec['altitude_ft'],spec['speed_kt'],spec['heading_deg'],0,'A320',0)
    points=[(0,state,route,profile)]
    for index in range(20000):
        step=advance_procedure(state,route,profile,5)
        state,route,profile=step.aircraft,step.remaining_route,step.profile
        if step.completed:
            points.append((index*5+step.elapsed_s,state,route,profile));return points
        if (index+1)%12==0:points.append(((index+1)*5,state,route,profile))
    raise ValueError('Forward stream did not finish')


@lru_cache(maxsize=256)
def _trajectory(encoded,step_s):
    spec=json.loads(encoded);profile=deepcopy(spec['procedure_profile']);route=spec['route_waypoints']
    state=AircraftState('TEMPLATE',spec['lat'],spec['lon'],spec['altitude_ft'],spec['speed_kt'],spec['heading_deg'],0,'A320',0)
    points=[state];transfer=0 if profile.get('approach_transfer_complete') else None
    for _ in range(20000):
        result=advance_procedure(state,route,profile,step_s)
        state,route,profile=result.aircraft,result.remaining_route,result.profile
        if transfer is None and profile.get('approach_transfer_complete'):
            transfer=profile['approach_transfer_time_s']
        if result.completed:state=replace(state,timestamp_s=points[-1].timestamp_s+result.elapsed_s)
        points.append(state)
        if result.completed:break
    else:raise ValueError('Staged flow route did not finish')
    return np.asarray([[p.timestamp_s,p.lat,p.lon,p.altitude_ft,p.ground_speed_kt,p.heading_deg,p.vertical_speed_fpm] for p in points]),transfer


def spec_trajectory(spec,step_s=5):
    path,transfer=_trajectory(json.dumps(spec,sort_keys=True),step_s)
    return path.copy(),transfer


def controlled_spec(spec,reduction):
    spec=deepcopy(spec)
    for leg in spec['procedure_profile']['legs']:
        if leg.get('phase') in ('centre','cruise','centre_hold'):leg['study_speed_factor']=1-reduction/100
        if leg['fix']==spec['procedure_profile'].get('approach_transfer_fix'):break
    for leg in spec['procedure_profile'].get('sequencing_pattern',{}).get('legs',[]):
        leg['study_speed_factor']=1-reduction/100
    spec['speed_kt']=altitude_speed(spec['altitude_ft'])*(1-reduction/100)
    return spec


def planning_path(flight,loops=0,speed_reduction_pct=0):
    spec=arrival_spec(flight,loops,speed_reduction_pct)
    projection=spec['procedure_profile'].get('stream_projection')
    if not projection:return spec_trajectory(spec)
    full=_seed_spec(dict(flight,initial_stage=0),0,speed_reduction_pct)
    path,transfer=spec_trajectory(full)
    if projection['kind']=='crop':
        advance=projection['advance_s'];path=path[path[:,0]>advance].copy();path[:,0]-=advance
        first=[0,spec['lat'],spec['lon'],spec['altitude_ft'],spec['speed_kt'],spec['heading_deg'],0]
        return np.vstack((first,path)),transfer-advance
    duration=projection['duration_s'];times=np.arange(0,duration,5)
    speed=spec['speed_kt'];heading=spec['heading_deg']
    prefix=np.asarray([[t,*move_position(spec['lat'],spec['lon'],heading,speed*t/3600),
        spec['altitude_ft'],speed,heading,0] for t in times])
    path[:,0]+=duration
    return np.vstack((prefix,path)),transfer+duration
