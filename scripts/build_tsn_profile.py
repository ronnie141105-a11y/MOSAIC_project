"""Rebuild the VVTS study profile from the reviewed workbook audit and charts.

No chart pixels are used as coordinates. Source units/constraints and proposed
simulation target altitudes are deliberately separate fields.
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'scenarios/profiles/tsn_tma'


def write(name, value):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def build():
    rows = list(csv.DictReader((ROOT / 'output/tsn_tma_design/waypoint_boundary_audit.csv').open(encoding='utf-8')))
    points = {r['waypoint']: dict(name=r['waypoint'], lat=float(r['latitude_deg']), lon=float(r['longitude_deg']),
              latitude_dms=r['source_latitude'], longitude_dms=r['source_longitude'],
              type='runway_threshold' if r['waypoint'].startswith('RW') else 'sequence_fix' if r['waypoint'].startswith('TS') else 'named_fix') for r in rows}
    assert len(points) == 149
    write('waypoints.json', points)
    sids = {
        'SAPEN2D': (['TS616','SAPEN'], [600,4000]),
        'BACHU2D': (['TS616','TS618','BACHU'], [600,2500,4000]),
        'MISAN2D': (['TS616','TS618','MISAN'], [600,2500,4000]),
        'ENPAS2D': (['TS616','TS618','ENPAS'], [600,2500,4000]),
        'XOBAV2D': (['TS616','TS641','TS642','TS644','XOBAV'], [600,2500,3000,4000,4250]),
        'KADUM2D': (['TS616','TS636','TS638','TS686','KADUM'], [600,1000,1800,3050,4500]),
        'ANTRI2D': (['TS612','TS626','TS628','TS632','TS814','TS816','ANTRI'], [450,1200,2200,3050,3800,4200,4500]),
        'LANHI2D': (['TS612','TS626','TS628','TS632','LANHI'], [450,1200,2200,3050,4500]),
    }
    common = ['LETRO','VANLI','TS488','RUNSI','TS458','TS456','TS454','SOKAN']
    ca = [2150]*7+[1200]
    stars = {
        'SAPEN2H': (['SAPEN','TS498','TS496','NOKUM','TS492']+common, [5000,4550,4250,3650,3050]+ca),
        'BITIS2H': (['BITIS','NOKUM','TS492']+common, [3650,3650,3050]+ca),
        'VICAL3H': (['VICAL']+common, [2150]+ca),
        'ELSAS2H': (['ELSAS','GOMIN','RUNSI','TS458','TS456','TS454','SOKAN'], [3350,2500,2150,2150,2150,2150,1200]),
        'DALAP2H': (['DALAP','VIKEP','TS452','TS438','TS436','TS434','TS432','SOKAN'], [3350]+[2750]*6+[1200]),
        'DALAP2J': (['DALAP','ANSUP','TS448','TS446','TS444','TS442','BOMSU'], [3350]+[2750]*5+[1200]),
    }
    ceilings = {'SAPEN':4250,'TS618':3350,'TS641':2750,'TS642':3350,'TS644':4250,'TS638':3350,'TS628':2750}
    floors = {'TS626':1200,'TS632':3050,'TS686':3050}
    arrival_floors = {'TS498':4550,'TS496':4250,'NOKUM':3650,'TS492':3050}
    arrival_at = {'LETRO':2150,'RUNSI':2150,'TS454':2150,'DALAP':3350,'VIKEP':2750,'ANSUP':2750,'TS432':2750,'TS442':2750}
    files=[]
    for kind, items in [('sid',sids),('star',stars)]:
        for ident,(names,alts) in items.items():
            source = ('83847.pdf' if ident in ('ANTRI2D','LANHI2D') else '83854.pdf') if kind=='sid' else ('56084.pdf' if ident=='DALAP2H' else '56090.pdf' if ident=='DALAP2J' else '56080.pdf')
            legs=[]
            for n,a in zip(names,alts):
                assert n in points
                constraints=[]
                if kind=='sid':
                    if n in ceilings:constraints.append(dict(type='at_or_below',value=ceilings[n],unit='m'))
                    if n in floors:constraints.append(dict(type='at_or_above',value=floors[n],unit='m'))
                else:
                    if n in arrival_floors:constraints.append(dict(type='at_or_above',value=arrival_floors[n],unit='m'))
                    if n in arrival_at:constraints.append(dict(type='at',value=arrival_at[n],unit='m'))
                    if n in ('SOKAN','BOMSU'):constraints.append(dict(type='window',minimum=730 if n=='SOKAN' else 790,maximum=1500,unit='m'))
                speed = 445 if n in ('TS612','TS614') else 460 if n in ('LETRO','RUNSI','DALAP') else 425 if n in ('SOKAN','BOMSU') else None
                legs.append(dict(fix=n, altitude_constraints=constraints, max_ias_kmh=speed, simulation_target_altitude_m=a))
            proc=dict(id=ident,kind=kind,direction='outbound' if kind=='sid' else 'inbound',runways=['25L','25R'],source=source,
                      coordination_required=kind=='star' or ident in ('KADUM2D','ANTRI2D'), legs=legs,
                      nominal_ground_speed_kt=180 if kind=='sid' else 210,
                      endpoint_behavior='handoff',simulation_model='piecewise_linear_altitude_on_fix_centrelines',
                      limitations=['Nominal altitudes are scenario assumptions within extracted fix constraints, not ATC clearances.',
                                   'No fly-by turn radius, wind or automatic holding; procedure extensions beyond the named SID terminus are not included.'])
            if kind=='sid':
                proc['start_altitude_m']=10
                proc['runway_fix_overrides']={'25R':{'TS612':'TS614'}} if ident in ('ANTRI2D','LANHI2D') else {}
            if ident in ('ANTRI2D','LANHI2D','KADUM2D'):
                proc['climb_gradient']={'minimum_percent':4.6 if ident=='KADUM2D' else 6.2,'until_altitude_m':3050,'thereafter_percent':3.3,'enforcement':'metadata_only_pending_aircraft_performance_model'}
            path=f'{kind}s/{ident.lower()}.json';write(path,proc);files.append(path)
    write('holds.json',[
        dict(fix='NOKUM',source='56080.pdf',inbound_magnetic_deg=113,minimum_altitude_m=3650,maximum_altitude_m=4250,max_ias_kmh=405),
        dict(fix='BITIS',source='56080.pdf',inbound_magnetic_deg=29,minimum_altitude_m=2450,maximum_flight_level=200,max_ias_kmh=425),
        dict(fix='VICAL',source='56080.pdf',inbound_magnetic_deg=1,minimum_altitude_m=2150,maximum_altitude_m=3650,max_ias_kmh=425),
        dict(fix='DALAP',source='56084.pdf',inbound_magnetic_deg=57,minimum_altitude_m=3350,maximum_altitude_m=4250,max_ias_kmh=405),
    ])
    write('profile.json',dict(id='tsn_tma',label='VVTS TMA study - RWY 25L/25R',kind='tma',waypoints='waypoints.json',procedures=files,holds='holds.json',
        center=dict(lat=10+49/60+6/3600,lon=106+39/60+2/3600,ident='TSH',source='10430.pdf'),
        radius_nm=40,lower_altitude_m=600,upper_altitude_m=5050,prediction_horizons_min=[1,2,3,5,10,15],
        study_thresholds=dict(cluster_horizontal_nm=8,conflict_horizontal_nm=5,vertical_ft=1000,
                              status='Simulation assumptions; not validated VVTS separation minima'),
        source_status='Historical 2022/2023/2024 charts; academic study boundary, not certified published TMA',
        limitations=['Conventional SID coordinate reconciliation pending; not included as flyable procedures.',
                     'Holding data retained; no holding execution in this version.',
                     'Climb gradients and aircraft performance not enforced; no GA optimization in this version.']))


if __name__=='__main__':
    build()
    from build_tsn_context import build as build_context
    build_context()

    from extend_tsn_chart_catalogue import build as extend_catalogue
    extend_catalogue()
