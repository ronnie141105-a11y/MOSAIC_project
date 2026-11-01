"""Centre arrival drawings end at the handoff; terminal procedure data stays full."""
from functools import lru_cache
import math

from astra.airspace import load_profile,geo_asset
from astra.centre import distance_nm,outward_route
from astra.utils.geodesy import bearing_deg,haversine_distance_nm,move_position

ROUTE_STYLE=dict(stroke='rgba(160,182,199,0.45)',width=.85,dash=[5,5])


def collection(features):
    return dict(type='FeatureCollection',features=features)


def outside_prefix(points):
    """Stop at the first inward 40 NM crossing, including long crossing chords."""
    if not points or distance_nm(points[0][1],points[0][0])<40-1e-7:return []
    result=[points[0]]
    for a,b in zip(points,points[1:]):
        lat,lon=a[1],a[0]
        length=haversine_distance_nm(lat,lon,b[1],b[0])
        heading=bearing_deg(lat,lon,b[1],b[0])
        steps=max(1,math.ceil(length))
        previous=0.0
        for step in range(1,steps+1):
            fraction=step/steps
            sample=move_position(lat,lon,heading,length*fraction)
            if distance_nm(*sample)<40:
                low,high=previous,fraction
                for _ in range(35):
                    mid=(low+high)/2
                    if distance_nm(*move_position(lat,lon,heading,length*mid))>=40:low=mid
                    else:high=mid
                p=move_position(lat,lon,heading,length*(low+high)/2)
                result.append([p[1],p[0]])
                return result
            previous=fraction
        result.append(b)
    return result


@lru_cache(maxsize=32)
def star_route(procedure_id):
    profile=load_profile('tsn_tma');proc=profile['procedure_data'][procedure_id]
    if proc['kind']!='star':return geo_asset('tsn_tma',f'procedure_{procedure_id}_route.json')
    points=profile['waypoint_data'];legs=[l['fix'] for l in proc['legs']]
    # A named gate just outside the nominal circle is the transfer endpoint.
    # DALAP is farther out: retain DALAP → the exact circle intersection.
    gate=next((name for name in legs if 39.5<=distance_nm(points[name]['lat'],points[name]['lon'])<=42),None)
    terminal=legs[:legs.index(gate)+1] if gate else legs
    paths=[]
    if proc.get('transitions'):
        for transition in proc['transitions'].values():
            paths.append(transition['fixes'][:-1]+terminal)
    else:
        anchor=points[legs[0]]
        feeder,_,_=outward_route((anchor['lat'],anchor['lon']),legs[0],100,'inbound')
        paths.append(list(reversed(feeder))+terminal[1:])
    features=[]
    for path in paths:
        coords=[[points[p]['lon'],points[p]['lat']] if isinstance(p,str) else [p[2],p[1]] for p in path]
        coords=outside_prefix(coords)
        if len(coords)>1:
            features.append(dict(type='Feature',geometry=dict(type='LineString',coordinates=coords),
                properties=dict(name=procedure_id,direction='inbound',transfer_fix=gate or 'VVTS_40NM')))
    return collection(features)


@lru_cache(maxsize=1)
def arrival_feeders():
    features=[];seen={}
    for proc in load_profile('tsn_tma')['procedure_data'].values():
        if proc['kind']!='star':continue
        for feature in star_route(proc['id'])['features']:
            key=tuple(tuple(round(x,7) for x in p) for p in feature['geometry']['coordinates'])
            if key in seen:seen[key]['properties']['procedures'].append(proc['id'])
            else:
                feature=dict(feature,properties=dict(feature['properties'],procedures=[proc['id']]))
                seen[key]=feature;features.append(feature)
    return collection(features)


@lru_cache(maxsize=1)
def transfer_waypoints():
    profile=load_profile('tsn_tma');points=profile['waypoint_data'];roles={}
    for proc in profile['procedure_data'].values():
        for leg in proc['legs']:
            name=leg['fix'];p=points[name]
            if name.startswith(('TS','_','RW')) or not 39<=distance_nm(p['lat'],p['lon'])<=42:continue
            roles.setdefault(name,set()).add('arrival' if proc['kind']=='star' else 'departure')
    # Named area handoff fixes also belong to the shared Centre/Approach picture.
    for route in profile['area_routes_data']:
        for edge in route['segments']:
            for name in edge:
                p=points[name]
                if not name.startswith(('TS','_','RW')) and 39<=distance_nm(p['lat'],p['lon'])<=42:
                    roles.setdefault(name,set()).add('area_route')
    return collection([dict(type='Feature',geometry=dict(type='Point',coordinates=[points[n]['lon'],points[n]['lat']]),
        properties=dict(name=n,roles=sorted(roles[n]),distance_nm=round(distance_nm(points[n]['lat'],points[n]['lon']),3)))
        for n in sorted(roles)])


@lru_cache(maxsize=1)
def arrival_limits():
    profile=load_profile('tsn_tma');points=profile['waypoint_data'];result={}
    for proc in profile['procedure_data'].values():
        if proc['kind']!='star':continue
        gate=next((l['fix'] for l in proc['legs'] if 39.5<=distance_nm(points[l['fix']]['lat'],points[l['fix']]['lon'])<=42),None)
        result[proc['id']]=(dict(name=gate,lat=points[gate]['lat'],lon=points[gate]['lon'],
            radius_nm=distance_nm(points[gate]['lat'],points[gate]['lon'])) if gate else dict(name='VVTS_40NM',radius_nm=40))
    return result
