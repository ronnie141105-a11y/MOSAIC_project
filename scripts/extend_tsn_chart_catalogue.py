"""Import the reviewed 25L/25R archive into the study profile.
RF legs use sampled WGS84 centre arcs. CA distances are explicit nominal
5% climb assumptions; they are not published fixed waypoints.
"""
import json, math, re
from pathlib import Path
from copy import deepcopy
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from astra.utils.geodesy import bearing_deg,move_position,haversine_distance_nm
OUT=ROOT/'scenarios/profiles/tsn_tma'
def read(n):return json.loads((OUT/n).read_text(encoding='utf8'))
def write(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def build():
 points=read('waypoints.json'); profile=read('profile.json')
 # 56092's longitude also reproduces the 305/288 true courses and 10.9 km legs.
 # The earlier workbook's 1070334.340E produces 308/287 and 10.2/11.8 km.
 points['TS444'].update(lon=107+3/60+3.340/3600,longitude_dms='1070303.340E',
                       source='56092.pdf; corrected against adjacent chart courses/distances')
 specs={
 'ANTRI2E':('sid','83860','TS616 TS618 TS622 TS624 TS626 TS628 TS632 TS814 TS816 ANTRI',[600,2500,3300,4000,5000,6096,6096,6096,6096,6096]),
 'LANHI2E':('sid','83904','TS616 TS618 TS622 TS624 TS626 TS628 TS632 LANHI',[600,2500,3300,4000,5000,6096,6096,6096]),
 'TANOS2E':('sid','83864','TS616 TS618 TS622 TS624 TS626 TS628 TS632 TANOS',[600,2500,3300,4000,5000,6096,6096,6096]),
 'TANOS2D':('sid','83853','TS612 TS626 TS628 TS632 TANOS',[450,1200,2200,3050,4500]),
 'ANTRI2F':('sid','83868','TS652 TS658 TS662 TS664 TS666 TS668 TS814 TS816 ANTRI',[400,900,1000,1200,1850,3050,3650,4200,4500]),
 'KADUM2F':('sid','83872','TS652 TS658 TS686 KADUM',[400,900,3050,4500]),
 'KADUM2G':('sid','107126','TS638 TS686 KADUM',[1800,3050,4500]),
 'KADUM2K':('sid','107129','TS638 TS686 KADUM',[1800,3050,4500]),
 'SAPEN2K':('sid','107129','SAPEN',[4000]),
 'BITIS2J':('star','56088','BITIS TS484 TS482 BUTGA NUNGO TS468 TS466 TS464 TS462 BOMSU',[5000,4550,3650,2150,2150,2150,2150,2150,2150,1200]),
 'SAPEN2J':('star','56088','SAPEN BUTGA NUNGO TS468 TS466 TS464 TS462 BOMSU',[3350,2150,2150,2150,2150,2150,2150,1200]),
 'VICAL3J':('star','56089','VICAL TS484 TS482 BUTGA NUNGO TS468 TS466 TS464 TS462 BOMSU',[5000,4550,3650,2150,2150,2150,2150,2150,2150,1200]),
 }
 for ident,(kind,source,names,alts) in specs.items():
  legs=[]
  for n,a in zip(names.split(),alts):
   assert n in points,n
   constraints=[];speed=None
   if kind=='star':
    if n in ('TS484','TS482','BUTGA'):constraints=[dict(type='at_or_above',value={'TS484':4550,'TS482':3650,'BUTGA':2150}[n],unit='m')]
    if n in ('NUNGO','TS462'):constraints=[dict(type='at',value=2150,unit='m')]
    if n=='BOMSU':constraints=[dict(type='window',minimum=790,maximum=1500,unit='m')]
    speed=460 if n=='BUTGA' else 425 if n=='BOMSU' else None
   else:
    floor={'TS626':1200,'TS632':3050,'TS686':3050,'TS664':1200,'TS666':1850,'TS668':3050,'TS814':3650}.get(n)
    if ident.endswith('2E') and n in ('TS626','TS632','TS814'):floor=None
    ceiling={'TS618':3350,'TS638':3350,'SAPEN':4250}.get(n)
    if n=='TS628':
     if ident.endswith('2E'):floor=6096
     else:ceiling=2750
    if floor:constraints.append(dict(type='at_or_above',value=floor,unit='m'))
    if ceiling:constraints.append(dict(type='at_or_below',value=ceiling,unit='m'))
    speed=445 if n in ('TS612','TS658','TS662') else 500 if n=='TS624' or (n=='TS638' and ident=='KADUM2G') else None
   legs.append(dict(fix=n,altitude_constraints=constraints,max_ias_kmh=speed,simulation_target_altitude_m=a))
  proc=dict(id=ident,kind=kind,direction='outbound' if kind=='sid' else 'inbound',runways=['25L','25R'],source=source+'.pdf',legs=legs,
    coordination_required=True,nominal_ground_speed_kt=180 if kind=='sid' else 210,endpoint_behavior='handoff',
    simulation_model='nominal_chart_route',limitations=['Nominal altitude and speed assumptions; no wind or aircraft performance model.'])
  if kind=='sid':proc.update(start_altitude_m=10,runway_fix_overrides={})
  proc['display_fixes']=names.split()
  if ident in ('ANTRI2F','KADUM2F'):
   expanded=[];previous=None
   for leg in legs:
    if leg['fix'] in ('TS658','TS662'):
     center=points['TSC03'];a=points[previous['fix']];b=points[leg['fix']]
     begin=bearing_deg(center['lat'],center['lon'],a['lat'],a['lon']);finish=bearing_deg(center['lat'],center['lon'],b['lat'],b['lon'])
     sweep=(finish-begin)%360; steps=math.ceil(sweep/3)
     radius=haversine_distance_nm(center['lat'],center['lon'],a['lat'],a['lon'])
     for i in range(1,steps):
      t=i/steps;lat,lon=move_position(center['lat'],center['lon'],begin+sweep*t,radius)
      fix=f'_{ident}_{leg["fix"]}_{i}'
      points[fix]=dict(name=fix,lat=lat,lon=lon,type='rf_sample',source=source+'.pdf')
      expanded.append(dict(fix=fix,altitude_constraints=[],max_ias_kmh=445,simulation_target_altitude_m=previous['simulation_target_altitude_m']+(leg['simulation_target_altitude_m']-previous['simulation_target_altitude_m'])*t,phase='sid_rf'))
     leg['path_descriptor']='RF';leg['arc_center']='TSC03';leg['radius_km']=5.9;leg['turn']='R'
    expanded.append(leg);previous=leg
   proc['legs']=expanded
  if ident in ('KADUM2G','KADUM2K','SAPEN2K'):
   alt=150 if ident=='KADUM2G' else 900
   dist=(alt-10)/.05/1852;rw=points['RW25L'];lat,lon=move_position(rw['lat'],rw['lon'],249.1,dist)
   fix='_'+ident+'_CA';points[fix]=dict(name=fix,lat=lat,lon=lon,type='nominal_ca_endpoint',source='5 percent nominal climb assumption')
   proc['legs'].insert(0,dict(fix=fix,altitude_constraints=[dict(type='at_or_above',value=alt,unit='m')],max_ias_kmh=None,simulation_target_altitude_m=alt,phase='sid_ca'))
   proc['limitations'].append('CA endpoint assumes 5% climb. Subsequent turn/CF interception is a straight nominal connection, not a protected turn model.')
  file=f'{kind}s/{ident.lower()}.json';write(file,proc)
  if file not in profile['procedures']:profile['procedures'].append(file)
 # Transition routes are read from the reviewed table text; whitespace in fix names is normalized.
 sources=ROOT/'reference/tsn_complete/TSN_TMA_CHART'
 for file in profile['procedures']:
  proc=read(file);ident=proc['id'];folder=next(p for p in sources.rglob('*') if p.is_dir() and ident in p.name)
  transitions={}
  for pdf in sorted(folder.glob('*.pdf')):
   textpath=ROOT/'reference/tsn_complete/extracted_tables'/f'{pdf.stem}.txt'
   if not textpath.exists():continue
   active=None;rows=[]
   def flush():
    if active and len(rows)>1:
     terminal=ident[:5]
     if (rows[0]==terminal if proc['kind']=='sid' else rows[-1]==terminal):transitions[active]=dict(fixes=rows.copy(),source=pdf.name)
   for line in textpath.read_text(encoding='utf8').splitlines():
    compact=re.sub(r'\s+','',line)
    head=re.fullmatch(r'([A-Z]{3,5})TRANSITION',compact)
    if head:flush();active=head[1];rows=[];continue
    if re.fullmatch(r'[A-Z]{5}\d[A-Z](DEPARTURE|ARRIVAL)',compact) or 'WAYPOINTLIST' in compact or 'HOLDINGPROCEDURES' in compact:
     flush();active=None;rows=[]
    match=re.match(r'\s*\d{3}\s+(?:IF|TF)\s+(.+?)\s{2,}',line)
    if active and match:
     fix=re.sub(r'\s+','',match[1])
     assert fix in points,(ident,fix)
     rows.append(fix)
   flush()
  proc['transitions']=transitions
  proc.setdefault('display_fixes',[l['fix'] for l in proc['legs'] if not l['fix'].startswith('_')])
  write(file,proc)
 write('waypoints.json',points);profile['archive']='TSN_TMA_CHART.zip';write('profile.json',profile)
 print('Imported',len(profile['procedures']),'procedures;',sum(len(read(f)['transitions']) for f in profile['procedures']),'transitions')
if __name__=='__main__':build()
