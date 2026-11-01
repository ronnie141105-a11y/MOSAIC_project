"""Shared Centre/Approach display boundary and saved-airway feeder routes.

The 40 NM boundary is a study convention. Saved airway geometry is historical;
route direction, cruise speed, levels and any join connector are assumptions.
"""
from copy import deepcopy
from functools import lru_cache
import heapq
import json
import math
from pathlib import Path

from astra.airspace import load_profile
from astra.utils.geodesy import bearing_deg, haversine_distance_nm, move_position


@lru_cache(maxsize=1)
def centre_point():
    c = load_profile('tsn_tma')['center']
    return c['lat'],c['lon']


def distance_nm(lat, lon):
    return haversine_distance_nm(lat, lon, *centre_point())


def control_area(lat, lon, direction=None, flight_type=None, altitude_ft=None, approach_transfer_complete=None):
    """Transfer ownership at 40 NM; retain gray Centre context down to 7,000 ft."""
    d = distance_nm(lat, lon)
    through = flight_type == 'OVERFLIGHT'
    owner = 'CENTRE' if through or d > 40 else 'APPROACH'
    if direction=='inbound' and isinstance(approach_transfer_complete,bool):
        owner='APPROACH' if approach_transfer_complete else 'CENTRE'
    centre = 1.0 if owner == 'CENTRE' else .7 if altitude_ft is not None and altitude_ft >= 7000 else 0.0
    approach = 1.0 if owner == 'APPROACH' else max(0.0, (44-d)/4) if direction == 'outbound' and not through else 0.0
    return dict(owner=owner, distance_nm=round(d, 5), centre_opacity=centre,
                approach_opacity=approach, boundary_nm=40)


@lru_cache(maxsize=1)
def airway_network():
    profile = load_profile('tsn_tma')
    path = Path(__file__).parent/'dashboard/geo/airways.json'
    features = json.loads(path.read_text(encoding='utf-8'))['features']
    nodes = {}
    links = []
    for feature in features:
        names = feature['properties'].get('waypoints', [])
        coords = feature['geometry'].get('coordinates', [])
        if len(names) != len(coords):
            continue
        for name, (lon, lat) in zip(names, coords):
            nodes[name] = (lat, lon)
        links.extend((a,b,feature['properties'].get('designator','AIRWAY')) for a,b in zip(names,names[1:]))
    nodes.update({n:(p['lat'],p['lon']) for n,p in profile['waypoint_data'].items()})
    for route in profile['area_routes_data']:
        links.extend((a,b,route['id']) for a,b in route['segments'])
    graph = {}
    for a,b,label in links:
        if a not in nodes or b not in nodes or a == b:
            continue
        length = haversine_distance_nm(*nodes[a],*nodes[b])
        graph.setdefault(a, []).append((b,length,label))
        graph.setdefault(b, []).append((a,length,label))
    return nodes, graph


@lru_cache(maxsize=1)
def arrival_network():
    """Add saved STAR transitions and exclude departure-only transition legs.

    The search walks outward, opposite to the aircraft's arrival direction.
    In particular, VICAL joins NIXIV directly rather than via XOBAV.
    """
    nodes,base=airway_network()
    graph={name:list(links) for name,links in base.items()}
    profile=load_profile('tsn_tma')
    arrivals=set();departures=set()
    for proc in profile['procedure_data'].values():
        for transition in proc.get('transitions',{}).values():
            names=transition['fixes']
            edges=arrivals if proc['kind']=='star' else departures
            edges.update(frozenset((a,b)) for a,b in zip(names,names[1:]))
            if proc['kind']=='star':
                for outer,inner in zip(names,names[1:]):
                    length=haversine_distance_nm(*nodes[outer],*nodes[inner])
                    graph.setdefault(inner,[]).append((outer,length,proc['id']+' transition'))
    forbidden=departures-arrivals
    # XOBAV–NIXIV is a departure leg even when no SID transition is selected.
    forbidden.add(frozenset(('XOBAV','NIXIV')))
    graph={name:[link for link in links if frozenset((name,link[0])) not in forbidden]
           for name,links in graph.items()}
    return nodes,graph


def outward_route(anchor, join_fix, reach_nm=220, direction=None):
    """Find an outward saved-airway chain without routing through VVTS.

    Output starts at anchor and ends upstream/downstream. A join connector is
    explicitly marked when the procedure anchor is absent from the network.
    """
    nodes, graph = arrival_network() if direction=='inbound' else airway_network()
    if join_fix in graph and haversine_distance_nm(*anchor,*nodes[join_fix]) < .2:
        start = join_fix
        connector = False
    else:
        start = min(graph, key=lambda n:haversine_distance_nm(*anchor,*nodes[n]))
        connector = haversine_distance_nm(*anchor,*nodes[start]) > .2
    base = distance_nm(*anchor)
    radial = {n:distance_nm(*nodes[n]) for n in graph}
    costs = {start:0.0}
    previous = {}
    todo = [(0.0,start)]
    while todo:
        cost, current = heapq.heappop(todo)
        if cost != costs[current]:
            continue
        for nxt, length, label in graph[current]:
            if radial[nxt] < max(base-3,radial[current]-8) or cost+length > 650:
                continue
            if cost+length < costs.get(nxt,math.inf):
                costs[nxt] = cost+length
                previous[nxt] = (current,label)
                heapq.heappush(todo,(cost+length,nxt))
    candidates = [n for n in costs if radial[n] >= max(base+30,reach_nm*.7)]
    if not candidates:
        candidates = [max(costs,key=lambda n:radial[n])]
    end = min(candidates,key=lambda n:abs(radial[n]-reach_nm)+costs[n]*.03)
    chain = [end]
    labels = []
    while chain[-1] != start:
        parent,label = previous[chain[-1]]
        labels.append(label)
        chain.append(parent)
    chain.reverse();labels.reverse()
    route = [(n,*nodes[n]) for n in chain]
    if connector:
        route.insert(0,(join_fix,*anchor))
    else:
        route[0] = (join_fix,*anchor)
    if len(route) < 2 or distance_nm(*route[-1][1:]) < max(base+10,60):
        # An unmapped isolated join is visibly synthetic, never an airway claim.
        c = load_profile('tsn_tma')['center']
        heading = bearing_deg(c['lat'],c['lon'],*anchor)
        route = [(join_fix,*anchor),('SYNTHETIC_FIR_END',*move_position(*anchor,heading,max(60,reach_nm-base)))]
        labels = ['SYNTHETIC CONNECTOR'];connector = True
    return route, list(dict.fromkeys(labels)), connector


def with_boundary(route):
    result = [route[0]]
    for a,b in zip(route,route[1:]):
        if (distance_nm(*a[1:])-40)*(distance_nm(*b[1:])-40) < 0:
            length = haversine_distance_nm(*a[1:],*b[1:])
            heading = bearing_deg(*a[1:],*b[1:])
            low,high = 0.0,1.0
            inside = distance_nm(*a[1:]) <= 40
            for _ in range(35):
                mid = (low+high)/2
                p = move_position(*a[1:],heading,length*mid)
                if (distance_nm(*p) <= 40) == inside:low = mid
                else:high = mid
            result.append(('VVTS_40NM',*move_position(*a[1:],heading,length*(low+high)/2)))
        result.append(b)
    return result


def connect_procedure(spec, requested_fl=300, reach_nm=220):
    """Extend an existing procedure without changing any of its terminal legs."""
    spec = deepcopy(spec)
    profile = spec['procedure_profile']
    inbound = profile['direction'] == 'inbound'
    proc = load_profile('tsn_tma')['procedure_data'][profile['procedure_id']]
    anchor = (spec['lat'],spec['lon']) if inbound else tuple(spec['route_waypoints'][-1])
    join_fix=proc['legs'][0]['fix'] if inbound else profile['legs'][-1]['fix']
    if inbound:
        points=load_profile('tsn_tma')['waypoint_data']
        # The compiler also uses `transition` for its ILS transition object.
        # Resolve the actual initial coordinates rather than treating it as a key.
        candidates=[join_fix]+[t['fixes'][0] for t in proc.get('transitions',{}).values()]
        join_fix=min(candidates,key=lambda n:haversine_distance_nm(*anchor,points[n]['lat'],points[n]['lon']))
    route, labels, connector = outward_route(anchor,join_fix,reach_nm,profile['direction'])
    for i,(a,b) in enumerate(zip(route,route[1:])):
        if distance_nm(*a[1:]) < reach_nm < distance_nm(*b[1:]):
            length=haversine_distance_nm(*a[1:],*b[1:]);heading=bearing_deg(*a[1:],*b[1:])
            low,high=0.0,1.0
            for _ in range(35):
                mid=(low+high)/2
                if distance_nm(*move_position(*a[1:],heading,length*mid)) < reach_nm:low=mid
                else:high=mid
            route=route[:i+1]+[('FIR_ROUTE_ENDPOINT',*move_position(*a[1:],heading,length*(low+high)/2))]
            break
    route = with_boundary(route)
    cruise = max(spec['altitude_ft'],requested_fl*100)
    entry = spec['altitude_ft'] if inbound else profile['legs'][-1]['target_altitude_ft']
    base = distance_nm(*anchor)
    def altitude(p):return min(cruise,entry+max(0,distance_nm(*p)-base)*220)
    if inbound:
        route.reverse()
        start = route[0]
        spec.update(lat=start[1],lon=start[2],altitude_ft=altitude(start[1:]),
                    speed_kt=250+min(180,max(0,distance_nm(*start[1:])-40)*3),
                    heading_deg=bearing_deg(*start[1:],*route[1][1:]))
        extra = route[1:]
        spec['route_waypoints'] = [tuple(p[1:]) for p in extra]+spec['route_waypoints']
        profile['legs'] = [dict(fix=p[0],target_altitude_ft=altitude(p[1:]),
             nominal_speed_kt=430 if distance_nm(*p[1:])>70 else 300 if distance_nm(*p[1:])>40.00001 else 250,
             phase='centre',max_ias_kt=None) for p in extra]+profile['legs']
    else:
        extra = route[1:]
        spec['route_waypoints'] += [tuple(p[1:]) for p in extra]
        profile['legs'] += [dict(fix=p[0],target_altitude_ft=altitude(p[1:]),
             nominal_speed_kt=430 if distance_nm(*p[1:])>70 else 300 if distance_nm(*p[1:])>40.00001 else 250,
             phase='centre',max_ias_kt=None) for p in extra]
        profile['endpoint_behavior'] = 'fir_exit'
    profile.update(connected_fir=True,centre_route=' / '.join(labels),
                   centre_join_connector_assumed=connector,
                   centre_routing_basis='Saved historical airway centreline. Direction, levels and speeds are study assumptions.')
    return spec
