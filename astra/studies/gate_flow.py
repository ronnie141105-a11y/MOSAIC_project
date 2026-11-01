"""Study-only gate flow control and regional origin dispatch.

Targets are flow constraints, not published separation minima. Regional
airport surfaces use a declared taxi-time model; no foreign apron is invented.
Short vectors rejoin the same leg and never change the destination or STAR.
"""
from copy import deepcopy
import math
import numpy as np
from astra.centre import airway_network
from astra.utils.geodesy import bearing_deg,haversine_distance_nm,move_position
from astra.studies.flow_routes import spec_trajectory,TRANSFER_FIXES

VERSION='ac-baomy-flow-1'
AIRPORTS={
    'VVPQ':dict(name='Phú Quốc',short='PQU',lat=10.1698,lon=103.9931,taxi_s=600,family='PQU_BITIS'),
    'VVDL':dict(name='Liên Khương',short='LKH',lat=11.7533,lon=108.3681,taxi_s=480,family='PTH_BAOMY'),
    'VVBM':dict(name='Buôn Ma Thuột',short='BMT',lat=12.6683,lon=108.1167,taxi_s=480,family='W1_AC'),
    'VVPK':dict(name='Pleiku',short='PLK',lat=14.0044,lon=108.0197,taxi_s=480,family='W1_AC'),
    'VVCR':dict(name='Cam Ranh',short='CXR',lat=11.9982,lon=109.2194,taxi_s=600,family='PTH_BAOMY'),
    'VVCS':dict(name='Côn Sơn',short='VCS',lat=8.7315,lon=106.6326,taxi_s=480,family='VTV'),
    'VVTS':dict(name='Tân Sơn Nhất',short='TSN',lat=10.8183,lon=106.6519,taxi_s=600),
}

def programme(overload):
    return dict(version=VERSION,enabled=True,cluster_id='AC_BAOMY',fixes=['AC','BAOMY'],
        upstream_corridor=['PTH','MATGI','BAOMY'],mit_nm=15 if overload else 10,
        minit_s=180 if overload else 120,maximum_vector_offset_nm=8,maximum_extra_track_nm=12,
        speed_change_pct=[-15,10],ground_stop=False,rerouting=False,slot_swapping=False,
        basis='Synthetic coordinated shared-gate flow targets; not operational minima',
        origin_surface_basis='Published airport identity, approximate dispatch location, assumed taxi duration')

def cluster_member(f):return f['direction']=='arrival' and f['route_family'] in ('W1_AC','PTH_BAOMY')

def extend_regional(flights,count,overload):
    from astra.studies.study_routes import FAMILIES
    arrivals=[f for f in flights if f['direction']=='arrival']
    codes=list(AIRPORTS)[:-1]
    for index in range(count):
        icao=codes[index%len(codes)];airport=AIRPORTS[icao];family=airport['family']
        f=deepcopy(next((f for f in arrivals if f['route_family']==family),arrivals[0]))
        number=len(arrivals)+index+1
        ready=600+(index//len(codes))*900+(index%len(codes))*120
        f.update(callsign=f'A{number:03d}',adep=icao,ades='VVTS',route_family=family,
            procedure=FAMILIES[family]['procedure'],origin_name=airport['name'],origin_pending=True,
            origin_requested_ctot_s=ready,origin_ctot_s=ready,origin_taxi_s=airport['taxi_s'],
            origin_queue_rank=index//len(codes),initial_stage=0,requested_fl=240 if icao!='VVPK' else 280,
            synthetic_extension=True,regional_origin_model=True,minimum_sequence_delay_s=0)
        f.pop('initial_airborne_spec',None);f.pop('fixed_initial_airborne_spec',None)
        flights.append(f)
    for f in flights:
        f.setdefault('origin_name',AIRPORTS.get(f['adep'],{}).get('name',f['adep']))
        f['flow_gate']=TRANSFER_FIXES.get(f['route_family']) if f['direction']=='arrival' else None
        f['flow_cluster']='AC_BAOMY' if cluster_member(f) else f.get('flow_gate')
    return flights

def regional_spec(flight):
    from astra.studies.flow_routes import arrival_spec
    f=dict(flight,initial_stage=0,stream_from_transfer=True)
    spec=arrival_spec(f,0);p=spec['procedure_profile'];nodes,_=airway_network()
    gate=TRANSFER_FIXES[f['route_family']]
    terminal_route=[nodes[gate]]+spec['route_waypoints']
    terminal_legs=[dict(fix=gate,target_altitude_ft=spec['altitude_ft'],nominal_speed_kt=280,
        phase='centre',record_event=True)]+p['legs']
    icao=f['adep'];airport=AIRPORTS[icao];origin=(airport['lat'],airport['lon'])
    if icao=='VVPK':upstream=['PLK','BMT','ENRIN']
    elif icao=='VVPQ':upstream=['PQU','RG','TRN']
    elif icao=='VVBM':upstream=['BMT','ENRIN']
    elif icao=='VVCS':upstream=[]
    elif f['route_family']=='PTH_BAOMY':upstream=['PTH','MATGI']
    else:upstream=['NIXIV']
    # A positive climb leg prevents a zero-length navaid join from changing altitude.
    upstream=[name for name in upstream if haversine_distance_nm(*origin,*nodes[name])>5]
    first=nodes[upstream[0]] if upstream else nodes[gate];heading=bearing_deg(*origin,*first)
    climb=move_position(*origin,heading,12)
    route=[climb]+[nodes[n] for n in upstream if haversine_distance_nm(*climb,*nodes[n])>2]+terminal_route
    legs=[dict(fix='ORIGIN_CLIMB',target_altitude_ft=6000,nominal_speed_kt=210,phase='origin_climb',record_event=True)]
    for name in upstream:
        if haversine_distance_nm(*climb,*nodes[name])<=2:continue
        legs.append(dict(fix=name,target_altitude_ft=min(f['requested_fl']*100,24000),
            nominal_speed_kt=340,phase='centre',study_speed_factor=1,record_event=True))
    if len(legs)>1:legs[-1]['target_altitude_ft']=max(16000,spec['altitude_ft']+4000)
    # The final en-route leg descends toward the original handoff clearance.
    p.update(legs=legs+terminal_legs,study_altitude_speed=True,study_max_descent_fpm=3500,
        origin_airport=icao,origin_surface_model='VIRTUAL_TAXI_TIMELINE',sequencing_circuits=0,
        sequencing_delay_s=0,airborne_sequencing_kind='REGIONAL_ORIGIN_TO_GATE')
    p['approach_transfer_complete']=False;p.pop('approach_transfer_time_s',None)
    spec.update(lat=origin[0],lon=origin[1],altitude_ft=0,speed_kt=180,heading_deg=bearing_deg(*origin,*climb),route_waypoints=route)
    return spec

def speed_spec(spec,change_pct):
    if not -15<=change_pct<=10:raise ValueError('Speed change must be within -15..+10 percent')
    result=deepcopy(spec)
    for leg in result['procedure_profile']['legs']:
        if leg.get('phase') in ('centre','cruise'):leg['study_speed_factor']=1+change_pct/100
    result['procedure_profile']['flow_acceleration_kt_s']=1.0
    result['procedure_profile']['flow_speed_change_pct']=change_pct
    return result

def startup_approach_spec(flight,late=False):
    """A full remaining point-merge arc, with no direct-to-ILS shortcut."""
    from astra.airspace import procedure_aircraft
    from astra.point_merge import arc_for_procedure
    from astra.studies.study_routes import FAMILIES
    spec=procedure_aircraft('tsn_tma',flight['procedure'],flight['callsign'])
    profile=spec['procedure_profile'];arc,merge=arc_for_procedure(flight['procedure'])
    names=[leg['fix'] for leg in profile['legs']]
    available=[name for name in arc if name in names]
    entry=available[len(available)//2] if late else available[0]
    index=names.index(entry);position=spec['route_waypoints'][index]
    spec['route_waypoints']=spec['route_waypoints'][index+1:]
    profile['legs']=profile['legs'][index+1:]
    level=12000 if late else 10000
    for leg in profile['legs']:
        if leg['fix']==merge:break
        leg['target_altitude_ft']=level
    gate=TRANSFER_FIXES[flight['route_family']];nodes,_=airway_network()
    profile.update(study_altitude_speed=True,study_max_descent_fpm=3500,
        approach_transfer_fix=gate,approach_transfer_position=list(nodes[gate]),
        approach_transfer_complete=True,approach_transfer_time_s=flight['startup_transfer_s'],
        sequencing_circuits=0,sequencing_delay_s=0,startup_point_merge_pending=True,
        centre_route=' → '.join(FAMILIES[flight['route_family']]['fixes']))
    spec.update(lat=position[0],lon=position[1],altitude_ft=level,speed_kt=240,
        heading_deg=bearing_deg(*position,*spec['route_waypoints'][0]))
    return spec

def level_cap_spec(spec,cap_ft):
    if cap_ft not in (18000,22000,26000):raise ValueError('Choose a declared study level cap')
    result=deepcopy(spec);gate=result['procedure_profile']['approach_transfer_fix']
    for leg in result['procedure_profile']['legs']:
        if leg['fix']==gate:break
        leg['target_altitude_ft']=min(cap_ft,leg['target_altitude_ft'])
    result['procedure_profile']['flow_level_cap_ft']=cap_ft
    return result

def stretch_spec(spec,extra_nm):
    """One bounded dogleg which rejoins the original next waypoint."""
    if not 0<=extra_nm<=12:raise ValueError('Track extension must be within 0..12 NM')
    result=deepcopy(spec)
    if not extra_nm:return result
    route=result['route_waypoints'];legs=result['procedure_profile']['legs'];start=(result['lat'],result['lon'])
    for i,(end,leg) in enumerate(zip(route,legs)):
        length=haversine_distance_nm(*start,*end)
        if leg.get('phase') in ('centre','cruise') and length>=30:
            # A bounded midpoint offset preserves the named rejoin.
            heading=bearing_deg(*start,*end);offset=min(8,math.sqrt(max(0,((length+extra_nm)/2)**2-(length/2)**2)))
            midpoint=move_position(*start,heading,length/2)
            bend=move_position(*midpoint,heading+90,offset)
            inserted=deepcopy(leg);inserted.update(fix='FLOW_VECTOR',target_altitude_ft=leg['target_altitude_ft'],record_event=True)
            route.insert(i,bend);legs.insert(i,inserted)
            actual=haversine_distance_nm(*start,*bend)+haversine_distance_nm(*bend,*end)-length
            result['procedure_profile'].update(flow_vector_extra_nm=actual,flow_vector_offset_nm=offset,flow_vector_rejoin=leg['fix'])
            return result
        start=end
    raise ValueError('No eligible Centre leg for a short rejoining vector')

def realize_rta(spec,delta_s):
    """Find a bounded speed/vector plan; never invent a pause in the air."""
    base,gate=spec_trajectory(spec,5);target=gate+delta_s
    lo,hi=-15.0,10.0
    slow=spec_trajectory(speed_spec(spec,lo),5)[1];fast=spec_trajectory(speed_spec(spec,hi),5)[1]
    vector=0.0;working=spec
    if target>slow+5:
        best=spec
        for extra in (2,4,6,8,10,12):
            try:candidate=stretch_spec(spec,extra)
            except ValueError:break
            best=candidate;vector=candidate['procedure_profile']['flow_vector_extra_nm']
            slow=spec_trajectory(speed_spec(candidate,lo),5)[1]
            if slow>=target:break
        working=best;fast=spec_trajectory(speed_spec(working,hi),5)[1]
    if not fast-5<=target<=slow+5:return None
    for _ in range(10):
        mid=(lo+hi)/2;time=spec_trajectory(speed_spec(working,mid),5)[1]
        if time>target:lo=mid
        else:hi=mid
    chosen=speed_spec(working,(lo+hi)/2);path,actual=spec_trajectory(chosen,1)
    if abs(actual-target)>15:return None
    return dict(spec=chosen,path=path,transfer_s=actual,actions=dict(speed_change_pct=(lo+hi)/2,
        path_extension_nm=vector,rta_delta_s=delta_s,rta_residual_s=actual-target))

def audit(flights,paths,marks,config):
    rows=[];violations=[]
    for f in flights:
        if f['direction']!='arrival':continue
        cs=f['callsign'];t=marks[cs]['approach_handoff'];p=paths[cs]
        rows.append(dict(callsign=cs,gate=f.get('flow_gate',TRANSFER_FIXES[f['route_family']]),
            cluster='AC_BAOMY' if cluster_member(f) else f.get('flow_gate'),time_s=t,
            speed_kt=float(np.interp(t,p[:,0],p[:,4])),origin=f['adep']))
    shared=sorted((r for r in rows if r['cluster']=='AC_BAOMY'),key=lambda r:r['time_s'])
    for a,b in zip(shared,shared[1:]):
        t=b['time_s'];pa=paths[a['callsign']];pb=paths[b['callsign']]
        distance=haversine_distance_nm(*[np.interp(t,p[:,0],p[:,k]) for p in (pa,pb) for k in (1,2)])
        if b['time_s']-a['time_s']<config['minit_s']-1 or distance<config['mit_nm']-.1:
            violations.append(dict(leader=a['callsign'],follower=b['callsign'],gap_s=b['time_s']-a['time_s'],distance_nm=distance))
    return dict(programme=config,events=rows,violations=violations,violating_pairs=len(violations),
        shared_cluster='AC and BAOMY share one admission stream; PTH–BAOMY feeds that stream')
