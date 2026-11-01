"""Merge reviewed area/approach chart data with the existing Centre catalogue.

Existing named fixes win over lower precision Centre coordinates. Display routes
are independent of the aircraft's SID/STAR/approach flight plan.
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'scenarios/profiles/tsn_tma'
GEO = ROOT / 'astra/dashboard/geo'


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf8')


def dms(value):
    degrees, minutes, seconds = value.split(':')
    return float(degrees) + float(minutes)/60 + float(seconds)/3600


def distance(a, b):
    lat1, lat2 = map(math.radians, [a['lat'], b['lat']])
    dl = math.radians(a['lon']-b['lon'])
    return 3440.065 * 2 * math.asin(min(1, math.sqrt(
        math.sin((lat1-lat2)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dl/2)**2)))


def build():
    profile = read(OUT/'profile.json')
    points = read(OUT/'waypoints.json')
    centre = profile['center']
    audit = []

    def merge(name, lat, lon, source, kind='named_fix'):
        candidate = dict(name=name, lat=lat, lon=lon, source=source, type=kind)
        if name in points:
            delta = distance(points[name], candidate)
            if delta > .01:
                audit.append(dict(fix=name, retained_source='existing TMA catalogue',
                                  incoming_source=source, difference_nm=delta))
        else:
            points[name] = candidate

    # Area chart 10430 / supplied screenshot; not coordinates inferred from pixels.
    chart = {
        'TSH': ('10:49:06','106:39:02'), 'AC': ('10:56:21','107:11:18'),
        'VTV': ('10:22:22','107:05:40'), 'BAOMY': ('10:52:15','107:19:45'),
        'DONXO': ('11:25:24','106:57:06'), 'POPET': ('11:06:00','105:57:00'),
        'BIHON': ('10:59:30','106:32:55'), 'RUNOP': ('11:05:17','106:38:18'),
        'MOXEB': ('10:53:58','106:27:46'), 'ANRAN': ('11:21:00','107:04:09'),
        'ENRIN': ('11:11:27','107:19:26'), 'ESDOB': ('10:53:19','106:57:05'),
        'VETOM': ('11:13:59','107:36:27'), 'VEPMA': ('10:56:00','107:40:18'),
        'MATGI': ('10:53:44','107:38:48'), 'BUKMA': ('10:50:50','107:01:51'),
        'LEDUP': ('10:46:33','107:08:49'), 'LOSON': ('10:29:36','107:04:32'),
        'RUTIT': ('10:27:15','107:45:27'), 'ASEBO': ('10:19:54','107:17:24'),
    }
    for name, (lat, lon) in chart.items():
        merge(name, dms(lat), dms(lon), '10430.pdf / supplied area-chart image',
              'navaid' if name in ('TSH','AC','VTV') else 'named_fix')
    # Workbook typo: DONXD and DONXO refer to the same chart fix.
    if 'DONXD' in points and distance(points['DONXD'], points['DONXO']) < .01:
        points['DONXO']['aliases'] = ['DONXD']
        del points['DONXD']

    approach_coords = {
        'BOMSU': ('10:54:37.875','106:53:59.311'),
        'SOKAN': ('10:52:13.005','106:54:17.156'),
        'TS420': ('10:49:01.800','106:38:34.000'),
        'TS422': ('10:49:53.800','106:40:51.800'),
        'TS424': ('10:51:38.765','106:45:30.124'),
        'TS426': ('10:53:02.523','106:49:12.337'),
        'TS500': ('10:57:14.000','106:20:00.000'),
        'RW25R': ('10:49:29.480','106:39:47.432'),
        'HCM_GP': ('10:49:29.5','106:39:36.4'),
        'HCM_LLZ': ('10:48:49.9','106:38:02.7'),
    }
    for name, (lat, lon) in approach_coords.items():
        merge(name, dms(lat), dms(lon), '123982.pdf waypoint table',
              'navaid' if name.startswith('HCM_') else 'approach_fix')

    navaids = {}
    for asset, key in [('waypoints.json','name'), ('navaids.json','ident')]:
        for f in read(GEO/asset)['features']:
            prop = f['properties']; name = prop.get(key)
            if not name or prop.get('category') == 'sector_boundary_point':
                continue
            lon, lat = f['geometry']['coordinates'][:2]
            if distance(centre, dict(lat=lat,lon=lon)) <= 120:
                merge(name, lat, lon, prop.get('source','ASTRA Centre catalogue'),
                      'navaid' if asset == 'navaids.json' else 'named_fix')
                if asset == 'navaids.json': navaids[name] = prop

    routes = []
    for f in read(GEO/'airways.json')['features']:
        names = f['properties'].get('waypoints',[])
        coords = f['geometry']['coordinates']
        # Retain connected local legs, including the first external endpoint.
        local = []
        for i in range(len(names)-1):
            a,b = coords[i:i+2]
            if min(distance(centre,dict(lat=a[1],lon=a[0])),
                   distance(centre,dict(lat=b[1],lon=b[0]))) <= 110:
                for name,(lon,lat) in zip(names[i:i+2],coords[i:i+2]):
                    merge(name,lat,lon,f['properties'].get('source','Centre airway'))
                local.append(names[i:i+2])
        if local:
            routes.append(dict(id=f['properties']['designator'],segments=local,
                               source=f['properties'].get('source'),kind='centre_airway'))
    # Local chart resolves intermediate fixes omitted by the Centre overview.
    replacements = {'N500': ('BUKMA','MATGI','BAOMY'),
                    'W17': ('TSH','ATGAS','BACHU'),
                    'W12': ('MOXEB','TRN','MISAN')}
    for route in routes:
        if route['id'] in replacements:
            a,b,middle = replacements[route['id']]
            route['segments'] = [part for seg in route['segments']
                for part in ([[a,middle],[middle,b]] if seg == [a,b] else [seg])]
    routes.extend([
        dict(id='R468',segments=[['POPET','SAPEN']],source='10430.pdf',kind='area_route'),
        *[dict(id='AREA-'+end,segments=[['TSH',end]],source='10430.pdf',
               kind='area_departure_arrival_routing')
          for end in ['RUNOP','KADUM','ANRAN','LANHI']],
    ])

    approach = dict(id='ILS_W_25R',runway='25R',sources=['123981.pdf','123982.pdf'],
        source_status='Supplied AIRAC AMDT 01/25 draft-labelled documents',
        transitions={n:dict(fixes=[n,'TS426','TS424','TS422','RW25R'],
                           initial_altitude_window_m=[minimum,1500],max_ias_kmh=425)
                     for n,minimum in [('BOMSU',790),('SOKAN',730)]},
        altitude_m={'TS426':600,'TS424':600,'RW25R':26},
        glidepath_deg=3,threshold_elevation_m=10,threshold_crossing_height_m=16.4,
        missed_approach=dict(fixes=['TS420','TS500'],altitude_m=600,
                             hold_fix='TS500',execution='not implemented'),
        nominal_speed_kt={'TS426':180,'TS424':160,'TS422':140,'RW25R':140},
        landing_model='Threshold crossing then nominal touchdown 16/tan(3deg) metres beyond threshold; no ground roll')
    profile.update(approach='approach_ils_w_25r.json',area_routes='area_routes.json',
                   navaids='context_navaids.json',radar_display_radius_nm=100,
                   source_status='Supplied historical area/SID/STAR charts and 2025 approach documents; study use')
    write('profile.json',profile)
    write('waypoints.json',points)
    write('approach_ils_w_25r.json',approach)
    write('area_routes.json',routes)
    write('context_navaids.json',navaids)
    write('coordinate_merge_audit.json',audit)


if __name__ == '__main__': build()
