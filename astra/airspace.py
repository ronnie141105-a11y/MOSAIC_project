"""Data-driven airspace profiles and nominal procedure scenarios.

Airspace-specific names live in JSON. Engines consume generic volume and route
data; a SID and STAR may share any number of fixes without being merged.
"""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
from pathlib import Path
import math

from astra.utils.config import SectorDefinition
from astra.utils.geodesy import bearing_deg, move_position

PROFILE_ROOT=Path(__file__).resolve().parents[1]/'scenarios/profiles'


@lru_cache(maxsize=8)
def _read_profile(name):
    if name!='tsn_tma':raise ValueError(f'Unknown airspace profile: {name}')
    root=PROFILE_ROOT/name
    data=json.loads((root/'profile.json').read_text(encoding='utf-8'))
    data['waypoint_data']=json.loads((root/data['waypoints']).read_text(encoding='utf-8'))
    data['procedure_data']={}
    for file in data['procedures']:
        p=json.loads((root/file).read_text(encoding='utf-8'))
        if p['id'] in data['procedure_data']:raise ValueError('Duplicate procedure ID')
        for leg in p['legs']:
            if leg['fix'] not in data['waypoint_data']:raise ValueError(f"Missing fix {leg['fix']}")
        data['procedure_data'][p['id']]=p
    data['holding_data']=json.loads((root/data['holds']).read_text(encoding='utf-8'))
    for key in ('approach','area_routes','navaids'):
        if key in data:
            data[key+'_data']=json.loads((root/data[key]).read_text(encoding='utf-8'))
    return data


def load_profile(name):
    return deepcopy(_read_profile(name))


def configure_profile(config, name):
    if name=='hcm_fir':return config
    p=load_profile(name);center=p['center']
    volume=SectorDefinition('VVTS-40NM',center['lat'],center['lon'],p['radius_nm'],
                            p['lower_altitude_m']/0.3048,p['upper_altitude_m']/0.3048)
    return replace(config,airspace_profile=name,assessment_volume=volume,sectors=[volume],
                   prediction_horizons_min=p['prediction_horizons_min'],max_prediction_horizon_min=15,
                   separation_horizontal_nm=p['study_thresholds']['cluster_horizontal_nm'],
                   separation_vertical_ft=p['study_thresholds']['vertical_ft'],
                   conflict_horizontal_min_nm=p['study_thresholds']['conflict_horizontal_nm'],
                   conflict_vertical_min_ft=p['study_thresholds']['vertical_ft'],
                   hotspot_horizontal_buffer_nm=p['study_thresholds']['cluster_horizontal_nm'],
                   hotspot_conflict_sample_step_s=5.0)


def procedure_aircraft(profile_name, procedure_id, callsign, runway=None, start_index=0,
                       include_approach=True, transition=None):
    """Compile a directed procedure to existing coordinate routes plus metadata.

    start_index supports reproducible in-route demo traffic. It never reverses
    a SID to make a STAR. Scenario altitudes remain distinct from restrictions.
    """
    data=load_profile(profile_name)
    try:proc=data['procedure_data'][procedure_id]
    except KeyError:raise ValueError(f'Unknown procedure: {procedure_id}') from None
    required_runway = '25L' if proc['kind']=='sid' else '25R'
    runway = runway or required_runway
    if runway != required_runway:
        raise ValueError('VVTS study configuration requires 25L departures and 25R arrivals.')
    if runway not in proc['runways']:raise ValueError('Unsupported runway')
    legs=deepcopy(proc['legs'])
    if transition:
        try: fixes=proc['transitions'][transition]['fixes']
        except KeyError: raise ValueError('Unknown procedure transition') from None
        inbound=proc['kind']=='star'
        join=legs[0] if inbound else legs[-1]
        names=fixes[:-1] if inbound else fixes[1:]
        extra=[dict(fix=n,altitude_constraints=[],max_ias_kmh=None,
                    simulation_target_altitude_m=join['simulation_target_altitude_m'],phase='transition') for n in names]
        legs=extra+legs if inbound else legs+extra

    approach = data.get('approach_data')
    landing = (include_approach and proc['kind']=='star' and approach is not None
               and runway==approach['runway'])
    if landing:
        transition = approach['transitions'][legs[-1]['fix']]
        threshold = data['waypoint_data']['RW25R']
        from astra.utils.geodesy import haversine_distance_nm
        faf = data['waypoint_data']['TS424']
        intercept_altitude = max(600,26+haversine_distance_nm(faf['lat'],faf['lon'],
            threshold['lat'],threshold['lon'])*1852*math.tan(math.radians(3)))
        for fix in transition['fixes'][1:]:
            point = data['waypoint_data'][fix]
            altitude = approach['altitude_m'].get(fix)
            if fix in ('TS426','TS424'):
                # Tabular +600 is a minimum. Use the geometric 3-degree
                # intercept (~610 m) rather than bending the glideslope.
                altitude = intercept_altitude
            if altitude is None:
                altitude = 26 + haversine_distance_nm(point['lat'],point['lon'],
                    threshold['lat'],threshold['lon'])*1852*math.tan(math.radians(3))
            legs.append(dict(fix=fix,simulation_target_altitude_m=altitude,
                altitude_constraints=[],max_ias_kmh=None,
                nominal_speed_kt=approach['nominal_speed_kt'][fix],phase='approach'))
        # Crossing the threshold at 26 m is not touchdown at 10 m elevation.
        # This final synthetic point is a declared simulation assumption.
        touchdown_distance_m = 16 / math.tan(math.radians(3))
        lat,lon = move_position(threshold['lat'],threshold['lon'],249.1,touchdown_distance_m/1852)
        data['waypoint_data']['TD25R'] = dict(lat=lat,lon=lon)
        legs.append(dict(fix='TD25R',simulation_target_altitude_m=10,
            altitude_constraints=[],max_ias_kmh=None,nominal_speed_kt=140,phase='landing'))
    overrides=proc.get('runway_fix_overrides',{}).get(runway,{})
    for leg in legs:leg['fix']=overrides.get(leg['fix'],leg['fix'])
    if proc['kind']=='sid':
        legs.insert(0,dict(fix='RW'+runway,simulation_target_altitude_m=proc['start_altitude_m'],altitude_constraints=[],max_ias_kmh=None))
    if not isinstance(start_index,int) or not 0<=start_index<len(legs)-1:
        raise ValueError('Start fix must precede the procedure endpoint')
    start=legs[start_index];remaining=legs[start_index+1:]
    point=data['waypoint_data'][start['fix']]
    route=[(data['waypoint_data'][l['fix']]['lat'],data['waypoint_data'][l['fix']]['lon']) for l in remaining]
    compiled=[]
    for leg in remaining:
        target=leg['simulation_target_altitude_m']
        for con in leg['altitude_constraints']:
            if con['type']=='at' and target!=con['value']:raise ValueError('Nominal altitude violates exact constraint')
            if con['type']=='at_or_above' and target<con['value']:raise ValueError('Nominal altitude below minimum')
            if con['type']=='at_or_below' and target>con['value']:raise ValueError('Nominal altitude above maximum')
            if con['type']=='window' and not con['minimum']<=target<=con['maximum']:raise ValueError('Nominal altitude outside window')
        nominal_speed = leg.get('nominal_speed_kt')
        if nominal_speed is None and proc['kind'] == 'sid':
            # Ground-speed assumptions for the mock study, not IAS limits.
            # Increase speed after the low-altitude initial climb rather
            # than carrying 180 kt through the entire SID.
            nominal_speed = 240 if target >= 3048 else 220
        elif nominal_speed is None and proc['kind'] == 'star':
            nominal_speed = 250 if target >= 3048 else 240
        compiled.append(dict(fix=leg['fix'],target_altitude_ft=target/0.3048,
                             max_ias_kt=leg['max_ias_kmh']/1.852 if leg['max_ias_kmh'] else None,
                             nominal_speed_kt=nominal_speed,
                             phase=leg.get('phase',proc['kind'])))
    return dict(callsign=callsign,aircraft_type='A320',lat=point['lat'],lon=point['lon'],
                heading_deg=bearing_deg(point['lat'],point['lon'],*route[0]),
                altitude_ft=start['simulation_target_altitude_m']/0.3048,speed_kt=proc['nominal_ground_speed_kt'],
                route_waypoints=route,procedure_profile=dict(flight_type='PROCEDURE',procedure_id=proc['id'],
                direction=proc['direction'],runway=runway,transition=transition,endpoint_behavior='landing' if landing else 'handoff',legs=compiled,
                approach_id=approach['id'] if landing else None,
                coordination_assumed_granted=proc['coordination_required'],source=proc['source']))


def feeder_aircraft(name, callsign):
    """A published Centre leg joins BITIS2H, then the 25R approach.

    ANHOA -> BITIS is L637. Entry altitude and speed are scenario assumptions.
    """
    data = load_profile(name)
    spec = procedure_aircraft(name,'BITIS2H',callsign,'25R')
    entry_altitude = spec['altitude_ft']
    spec['route_waypoints'].insert(0,(spec['lat'],spec['lon']))
    spec['procedure_profile']['legs'].insert(0,dict(fix='BITIS',
        target_altitude_ft=entry_altitude,max_ias_kt=None,phase='centre',nominal_speed_kt=210))
    start = data['waypoint_data']['ANHOA']
    spec.update(lat=start['lat'],lon=start['lon'],altitude_ft=5000/.3048,
                heading_deg=bearing_deg(start['lat'],start['lon'],*spec['route_waypoints'][0]))
    spec['procedure_profile']['feeder_route'] = 'L637: ANHOA-BITIS'
    return spec


def profile_presets(name):
    if name=='hcm_fir':return None
    definitions=[
        ('vvts_mixed','VVTS mixed SID / STAR','Arrivals and departures on overlapping published centrelines.',
         [('SAPEN2D','DEP001','25L',0),('ANTRI2D','DEP002','25L',2),('SAPEN2H','ARR001','25R',0),('BITIS2H','ARR002','25R',0),('DALAP2J','ARR003','25R',1)]),
        ('vvts_arrivals','VVTS arrival merges','SAPEN, BITIS, VICAL and ELSAS streams feeding SOKAN.',
         [('SAPEN2H','ARR101','25R',1),('BITIS2H','ARR102','25R',0),('VICAL3H','ARR103','25R',0),('ELSAS2H','ARR104','25R',0)]),
        ('vvts_departures','VVTS departure fan','Staggered positions along four outbound procedures; not simultaneous runway releases.',
         [('SAPEN2D','DEP101','25L',1),('KADUM2D','DEP102','25L',2),('LANHI2D','DEP103','25L',3),('XOBAV2D','DEP104','25L',2)]),
    ]
    presets = {key:dict(key=key,label=label,description=description,
                    aircraft=[procedure_aircraft(name,*args) for args in specs])
            for key,label,description,specs in definitions}
    presets['vvts_centre_entry'] = dict(key='vvts_centre_entry',label='Centre to TMA to landing',
        description='ANHOA on L637 to BITIS2H, SOKAN, ILS W 25R and landing.',
        aircraft=[feeder_aircraft(name,'FEED01')])
    return presets


def seed_profile(reader,name):
    for ac in profile_presets(name)['vvts_mixed']['aircraft']:reader.create_aircraft(**ac)
    reader.send_command('OP')


def profile_airways(name):
    """Connected area-route chains for the existing Centre-style spawn form."""
    data=load_profile(name);grouped={};result=[]
    for route in data['area_routes_data']:
        grouped.setdefault(route['id'],[]).extend(route['segments'])
    for ident,segments in grouped.items():
        remaining=list(dict.fromkeys(tuple(s) for s in segments))
        part=0
        while remaining:
            ends={b for a,b in remaining}
            first=next((s for s in remaining if s[0] not in ends),remaining[0])
            remaining.remove(first);chain=list(first)
            while True:
                edge=next((s for s in remaining if s[0]==chain[-1]),None)
                if edge is None:break
                remaining.remove(edge);chain.append(edge[1])
            part+=1
            result.append(dict(designator=ident if part==1 else f'{ident}/{part}',
                waypoint_names=chain,coordinates=[dict(lat=data['waypoint_data'][n]['lat'],
                    lon=data['waypoint_data'][n]['lon']) for n in chain]))
    return result


def geo_asset(name, asset):
    data=load_profile(name)
    if asset=='manifest.json':
        from astra.dashboard.tma_layers import manifest
        return manifest(data['procedure_data'])
    if asset=='transfer_waypoints.json':
        from astra.dashboard.centre_layers import transfer_waypoints
        return transfer_waypoints()
    if asset in ('VVP4.json','VVR19.json','VVR36.json'):
        from astra.airspace_zones import zone_asset
        return zone_asset(asset[:-5])
    def feature(geometry,properties):return dict(type='Feature',geometry=geometry,properties=properties)
    pts=data['waypoint_data'];features=[]
    if asset.startswith('procedure_'):
        import re
        match=re.fullmatch(r'procedure_([A-Z0-9]+)_(route|fixes)\.json',asset)
        if not match or match[1] not in data['procedure_data']:raise ValueError('Unknown procedure layer')
        proc=data['procedure_data'][match[1]]
        ac=procedure_aircraft(name,proc['id'],'DISPLAY',include_approach=False)
        coords=[[ac['lon'],ac['lat']]]+[[lon,lat] for lat,lon in ac['route_waypoints']]
        used=set(proc.get('display_fixes',[l['fix'] for l in proc['legs']]))
        if match[2]=='route':features.append(feature(dict(type='LineString',coordinates=coords),dict(name=proc['id'])))
        for ident,t in proc.get('transitions',{}).items():
            used.update(t['fixes'])
            if match[2]=='route':features.append(feature(dict(type='LineString',coordinates=[[pts[n]['lon'],pts[n]['lat']] for n in t['fixes']]),dict(name=proc['id']+' / '+ident,source=t['source'])))
        if match[2]=='fixes':features=[feature(dict(type='Point',coordinates=[pts[n]['lon'],pts[n]['lat']]),dict(name=n)) for n in sorted(used) if not n.startswith('_')]
        return dict(type='FeatureCollection',features=features)
    if asset in ('coastlines.json','country_borders.json','centre_firs.json'):
        file = 'firs.json' if asset=='centre_firs.json' else asset
        return json.loads((Path(__file__).parent/'dashboard/geo'/file).read_text(encoding='utf8'))
    if asset in ('boundary.json','radar_range.json'):
        c=data['center'];coords=[]
        radius = data['radar_display_radius_nm'] if asset=='radar_range.json' else data['radius_nm']
        for bearing in range(0,361,2):
            lat,lon=move_position(c['lat'],c['lon'],bearing,radius);coords.append([lon,lat])
        features=[feature(dict(type='Polygon',coordinates=[coords]),dict(name=f'VVTS {radius} NM '+('radar range' if radius==100 else 'TMA'),source='user_defined_study_boundary'))]
    elif asset=='airways.json':
        seen=set()
        for route in data['area_routes_data']:
            for a,b in route['segments']:
                key=(route['id'],*sorted([a,b]))
                if key in seen:continue
                seen.add(key)
                features.append(feature(dict(type='LineString',coordinates=[[pts[n]['lon'],pts[n]['lat']] for n in (a,b)]),
                    dict(designator=route['id'],waypoints=[a,b],source=route['source'],kind=route['kind'])))
    elif asset in ('point_merge_arcs.json','point_merge_spokes.json'):
        from astra.point_merge import ARCS
        for arc_name, fixes in ARCS.items():
            merge = 'SOKAN' if arc_name.startswith('H_') else 'BOMSU'
            if asset == 'point_merge_arcs.json':
                features.append(feature(
                    dict(type='LineString', coordinates=[[pts[n]['lon'],pts[n]['lat']] for n in fixes]),
                    dict(name=arc_name, merge_fix=merge, kind='arc')))
            else:
                for fix in fixes:
                    features.append(feature(
                        dict(type='LineString', coordinates=[
                            [pts[fix]['lon'],pts[fix]['lat']],
                            [pts[merge]['lon'],pts[merge]['lat']]]),
                        dict(name=f'{fix} direct {merge}', from_fix=fix,
                             merge_fix=merge, kind='direct_to_option')))
    elif asset=='approach.json':
        for entry,transition in data['approach_data']['transitions'].items():
            features.append(feature(dict(type='LineString',coordinates=[[pts[n]['lon'],pts[n]['lat']] for n in transition['fixes']]),
                                    dict(name='ILS W 25R via '+entry,source='123981.pdf / 123982.pdf')))
    elif asset=='navaids.json':
        for n,properties in data['navaids_data'].items():
            properties={**properties, 'symbol':{'TSH':'vor_dme','AC':'ndb','VTV':'vor'}.get(n,'star'), 'compass_rose':n=='TSH'}
            features.append(feature(dict(type='Point',coordinates=[pts[n]['lon'],pts[n]['lat']]),properties))
    elif asset in ('sids.json','stars.json'):
        kind='sid' if asset=='sids.json' else 'star'
        for proc in data['procedure_data'].values():
            if proc['kind']!=kind:continue
            for runway in (['25L'] if kind=='sid' else ['25R']):
                ac=procedure_aircraft(name,proc['id'],'DISPLAY',runway,include_approach=False)
                coords=[[ac['lon'],ac['lat']]]+[[lon,lat] for lat,lon in ac['route_waypoints']]
                features.append(feature(dict(type='LineString',coordinates=coords),dict(name=proc['id'],direction=proc['direction'],runway=runway,source=proc['source'])))
    elif asset in ('waypoints.json','approach_fixes.json','sid_fixes.json','star_fixes.json'):
        app={'BOMSU','SOKAN','TS420','TS422','TS424','TS426','TS500'}
        if asset=='approach_fixes.json':
            used=app
        elif asset in ('sid_fixes.json','star_fixes.json'):
            kind='sid' if asset=='sid_fixes.json' else 'star'
            used={leg['fix'] for p in data['procedure_data'].values() if p['kind']==kind
                  for leg in procedure_aircraft(name,p['id'],'DISPLAY',include_approach=False)['procedure_profile']['legs']
                  if not leg['fix'].startswith('RW')}
            used.update(p['legs'][0]['fix'] for p in data['procedure_data'].values() if p['kind']==kind)
        else:
            from astra.utils.geodesy import haversine_distance_nm
            c=data['center']
            used={n for route in data['area_routes_data'] for pair in route['segments'] for n in pair}
            used.update(['BIHON'])
            used={n for n in used if n not in app and n not in data['navaids_data']
                  and haversine_distance_nm(c['lat'],c['lon'],pts[n]['lat'],pts[n]['lon'])<=110}
        features=[feature(dict(type='Point',coordinates=[pts[n]['lon'],pts[n]['lat']]),dict(name=n)) for n in sorted(used)]
    elif asset=='runways.json':
        for a,b in [('RW07L','RW25R'),('RW07R','RW25L')]:
            features.append(feature(dict(type='LineString',coordinates=[[pts[n]['lon'],pts[n]['lat']] for n in [a,b]]),dict(name=('25L departure' if b=='RW25L' else '25R arrival'))))
    else:raise ValueError('Unknown profile geographic asset')
    return dict(type='FeatureCollection',features=features)
