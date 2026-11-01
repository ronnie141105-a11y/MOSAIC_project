"""Explicit saved-airway corridors for the two synthetic operational studies.

Named joins absent from the saved graph are listed as assumed connectors.
These are scenario routes, not statements about currently cleared routes.
"""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache

import numpy as np

from astra.airspace import procedure_aircraft
from astra.centre import airway_network, distance_nm, with_boundary
from astra.interface.traffic_state import AircraftState
from astra.point_merge import arc_for_procedure
from astra.trajectory.procedure import advance_procedure
from astra.utils.geodesy import bearing_deg, move_position


FAMILIES = {
    'W1_AC': dict(direction='arrival',procedure='DALAP2H',start_index=1,
        fixes=['BMT','ENRIN','AC','VIKEP'],origin='VVNB',sector='CENTRE_NE'),
    'W1_LKH': dict(direction='arrival',procedure='DALAP2H',start_index=0,
        fixes=['BMT','ONEBI','LKH','VETOM','DALAP'],origin='VVDN',sector='CENTRE_NE'),
    'PTH_BAOMY': dict(direction='arrival',procedure='DALAP2J',start_index=1,
        fixes=['PTH','MATGI','BAOMY','ANSUP'],origin='VVCR',sector='CENTRE_NE'),
    'BIBAN_BITIS': dict(direction='arrival',procedure='BITIS2H',start_index=0,
        fixes=['BIBAN','ANHOA','BITIS'],origin='WSSS',sector='CENTRE_SW'),
    'PQU_BITIS': dict(direction='arrival',procedure='BITIS2H',start_index=0,
        fixes=['PQU','RG','TRN','BITIS'],origin='VVPQ',sector='CENTRE_SW'),
    'VTV': dict(direction='arrival',procedure='ELSAS2H',start_index=2,
        fixes=['TULTU','VTV','RUNSI'],origin='VVCS',sector='CENTRE_SE'),
    'SAPEN_WEST': dict(direction='arrival',procedure='SAPEN2J',start_index=0,
        fixes=['SAPEN'],origin='VDPP',sector='CENTRE_NW'),
    'NIXIV_VICAL': dict(direction='arrival',procedure='VICAL3H',start_index=0,
        fixes=['NIXIV','VICAL'],origin='VDPP',sector='CENTRE_SW'),
    'KADUM_BMT': dict(direction='departure',procedure='KADUM2D',
        fixes=['KADUM','PATMA','BMT'],destination='VVNB',sector='CENTRE_NE'),
    'ANTRI_DOVIN': dict(direction='departure',procedure='ANTRI2D',
        fixes=['ANTRI','DOVIN','BMT'],destination='VVDN',sector='CENTRE_NE'),
    'ANTRI_PTH': dict(direction='departure',procedure='ANTRI2D',
        fixes=['ANTRI','PTH','SOSPA','LKH'],destination='VVCR',sector='CENTRE_NE'),
    'LANHI_ELSAS': dict(direction='departure',procedure='LANHI2D',
        fixes=['LANHI','ELSAS','RUTIT'],destination='VVCS',sector='CENTRE_SE'),
    'XOBAV_NIXIV': dict(direction='departure',procedure='XOBAV2D',
        fixes=['XOBAV','NIXIV','CN'],destination='VVPQ',sector='CENTRE_SW'),
}
ARRIVAL_MIX = ('W1_AC','W1_LKH','W1_AC','PTH_BAOMY','BIBAN_BITIS',
               'W1_AC','W1_LKH','VTV','W1_AC','BIBAN_BITIS')
DEPARTURE_MIX = ('KADUM_BMT','ANTRI_DOVIN','ANTRI_PTH','XOBAV_NIXIV',
                 'KADUM_BMT','LANHI_ELSAS','ANTRI_DOVIN','XOBAV_NIXIV')


def make_spec(family, requested_fl=300, speed_reduction_pct=0):
    f=FAMILIES[family]
    inbound=f['direction']=='arrival'
    spec=procedure_aircraft('tsn_tma',f['procedure'],'TEMPLATE',start_index=f.get('start_index',0))
    p=spec['procedure_profile']
    if inbound:
        arc,merge=arc_for_procedure(f['procedure'])
        legs=p['legs']; names=[l['fix'] for l in legs]
        release=next(n for n in arc if n in names)
        keep=list(range(names.index(release)+1))+list(range(names.index(merge),len(names)))
        spec['route_waypoints']=[spec['route_waypoints'][i] for i in keep]
        p['legs']=[legs[i] for i in keep]
        p.update(direct_from_fix=release,direct_to_fix=merge)
        p['legs'][keep.index(names.index(merge))]['nominal_speed_kt']=230
    nodes,graph=airway_network()
    named=[(name,*nodes[name]) for name in f['fixes']]
    if len(named)==1:
        heading=bearing_deg(*named[0][1:],spec['lat'],spec['lon']) if tuple(named[0][1:])!=(spec['lat'],spec['lon']) else 120
        named.insert(0,('UPSTREAM',*move_position(*named[0][1:],heading+180,120)))
    named=with_boundary(named)
    anchor=(spec['lat'],spec['lon']) if inbound else tuple(spec['route_waypoints'][-1])
    base=distance_nm(*anchor)
    entry=spec['altitude_ft'] if inbound else p['legs'][-1]['target_altitude_ft']
    def altitude(point):return min(requested_fl*100,entry+max(0,distance_nm(*point)-base)*220)
    extra=named[1:]
    legs=[dict(fix=n,target_altitude_ft=altitude((lat,lon)),
        nominal_speed_kt=430 if distance_nm(lat,lon)>70 else 300 if distance_nm(lat,lon)>40.00001 else 250,
        phase='centre',max_ias_kt=None) for n,lat,lon in extra]
    if inbound:
        spec.update(lat=named[0][1],lon=named[0][2],altitude_ft=altitude(named[0][1:]),
            speed_kt=430,heading_deg=bearing_deg(*named[0][1:],*named[1][1:]))
        spec['route_waypoints']=[tuple(n[1:]) for n in extra]+spec['route_waypoints']
        p['legs']=legs+p['legs']
    else:
        spec['route_waypoints'] += [tuple(n[1:]) for n in extra]
        p['legs'] += legs
        p['endpoint_behavior']='fir_exit'
    assumed=[]
    for a,b in zip(f['fixes'],f['fixes'][1:]):
        if not any(link[0]==b for link in graph.get(a,[])):
            assumed.append(a+' → '+b)
    p.update(connected_fir=True,centre_route=' → '.join(f['fixes']),route_family=family,
        centre_join_connector_assumed=bool(assumed),assumed_connectors=assumed,
        centre_routing_basis='Named saved airway coordinates plus explicitly listed study connectors')
    if speed_reduction_pct:
        if not inbound:raise ValueError('Only arrivals receive upstream speed controls')
        for leg,coord in zip(p['legs'],spec['route_waypoints']):
            if leg['phase']=='centre' and distance_nm(*coord)>=40-.001:
                leg['nominal_speed_kt'] *= 1-speed_reduction_pct/100
        spec['speed_kt'] *= 1-speed_reduction_pct/100
    return spec


def departure_handoff_spec(family,requested_fl=300):
    spec=make_spec(family,requested_fl)
    spec['altitude_ft']=1500
    spec['lat'],spec['lon']=move_position(spec['lat'],spec['lon'],
        bearing_deg(spec['lat'],spec['lon'],*spec['route_waypoints'][0]),205*45/3600)
    spec['speed_kt']=205
    spec['heading_deg']=bearing_deg(spec['lat'],spec['lon'],*spec['route_waypoints'][0])
    return spec


@lru_cache(maxsize=128)
def trajectory(family,requested_fl=300,speed_reduction_pct=0):
    f=FAMILIES[family]
    spec=make_spec(family,requested_fl,speed_reduction_pct) if f['direction']=='arrival' else departure_handoff_spec(family,requested_fl)
    route,p=spec['route_waypoints'],spec['procedure_profile']
    meta=deepcopy(p)
    state=AircraftState('TEMPLATE',spec['lat'],spec['lon'],spec['altitude_ft'],spec['speed_kt'],spec['heading_deg'],0,'A320',0)
    points=[state]
    for _ in range(5000):
        step=advance_procedure(state,route,p,5)
        state,route,p=step.aircraft,step.remaining_route,step.profile
        if step.completed:state=replace(state,timestamp_s=points[-1].timestamp_s+step.elapsed_s)
        points.append(state)
        if step.completed:break
    else:raise ValueError('Study corridor did not complete: '+family)
    return np.asarray([[s.timestamp_s,s.lat,s.lon,s.altitude_ft,s.ground_speed_kt,s.heading_deg,s.vertical_speed_fpm]
                       for s in points]),meta
