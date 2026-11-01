"""Small, explicitly synthetic scenarios for testing the connected monitors.

Trajectories use the existing procedure propagator. Admission times are chosen
before publishing tracks; a 1 s audit checks separation and 120 s handoff gaps.
These are functional fixtures, not flight plans or ATFM research case studies.
"""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import csv
import json
import math
from pathlib import Path

import numpy as np

from astra.airspace import procedure_aircraft
from astra.centre import connect_procedure, distance_nm
from astra.interface.traffic_state import AircraftState
from astra.trajectory.procedure import advance_procedure

ROOT=Path(__file__).resolve().parents[2]/'scenarios/synthetic/system_tests'
CASES={
    'test_arrival_stream':dict(label='T1 · Arrival handoff stream',
        description='Four BITIS2H arrivals: Centre → Approach → Tower.',
        procedures=['BITIS2H']*4),
    'test_mixed_flow':dict(label='T2 · Arrivals and departures',
        description='Two arrivals and two departures across all three monitors.',
        procedures=['BITIS2H','XOBAV2D','DALAP2H','SAPEN2D']),
    'test_three_gates':dict(label='T3 · Three arrival routes',
        description='Six arrivals via three STARs, with two departures.',
        procedures=['BITIS2H','DALAP2H','VICAL3H','XOBAV2D','BITIS2H','DALAP2H','VICAL3H','SAPEN2D']),
    'test_full_cycle':dict(label='T4 · Full cycle · 10 departures + 10 arrivals',
        description='Stand → taxi → 25L → SID → Centre, and Centre → STAR → 25R → taxi → stand.',
        mode='full_cycle'),
}
VERSION='system-tests-1'
START=datetime(2026,10,20,2,0,tzinfo=timezone.utc)


def catalog(root=ROOT):
    result=[]
    for case_id,spec in CASES.items():
        path=Path(root)/case_id/'manifest.json'
        if path.exists():
            manifest=json.loads(path.read_text(encoding='utf-8'))
            result.append(dict(case_id=case_id,label=spec['label'],description=spec['description'],
                counts=manifest['counts'],duration_s=manifest['duration_s'],audit=manifest['separation_audit'],
                synthetic=True))
    return result


@lru_cache(maxsize=None)
def trajectory(procedure):
    spec=procedure_aircraft('tsn_tma',procedure,'TEST')
    spec=connect_procedure(spec,requested_fl=300,reach_nm=130)
    route,profile=spec['route_waypoints'],spec['procedure_profile']
    state=AircraftState('TEST',spec['lat'],spec['lon'],spec['altitude_ft'],spec['speed_kt'],
                        spec['heading_deg'],0,'A320',0)
    points=[state]
    for _ in range(3000):
        step=advance_procedure(state,route,profile,5)
        state,route,profile=step.aircraft,step.remaining_route,step.profile
        points.append(state)
        if step.completed:break
    else:raise ValueError(f'Procedure did not finish: {procedure}')
    path=np.asarray([[p.timestamp_s,p.lat,p.lon,p.altitude_ft,p.ground_speed_kt,
                      p.heading_deg,p.vertical_speed_fpm] for p in points])
    inbound=profile['direction']=='inbound'
    radii=np.asarray([distance_nm(p.lat,p.lon) for p in points])
    crossing=np.where((radii[:-1]>40)&(radii[1:]<=40))[0] if inbound else np.where((radii[:-1]<=40)&(radii[1:]>40))[0]
    if not len(crossing):raise ValueError(f'No 40 NM transfer: {procedure}')
    i=int(crossing[0]);fraction=(40-radii[i])/(radii[i+1]-radii[i])
    transfer=float(path[i,0]+fraction*(path[i+1,0]-path[i,0]))
    gate=dict(fix='VVTS_40NM',lat=float(path[i,1]+fraction*(path[i+1,1]-path[i,1])),
              lon=float(path[i,2]+fraction*(path[i+1,2]-path[i,2])))
    return path,transfer,gate,inbound,profile.get('centre_route')


def pair_audit(a,b,margin=False,terminal_mixed=False):
    start=math.ceil(max(a[0,0],b[0,0]));end=math.floor(min(a[-1,0],b[-1,0]))
    if end<start:return dict(violations=0,minimum_horizontal_nm=None,minimum_vertical_ft=None)
    times=np.arange(start,end+1,dtype=float)
    left=np.asarray([np.interp(times,a[:,0],a[:,k]) for k in (1,2,3,5)])
    right=np.asarray([np.interp(times,b[:,0],b[:,k]) for k in (1,2,3,5)])
    la,lb=np.radians(left[0]),np.radians(right[0])
    h=np.sin((lb-la)/2)**2+np.cos(la)*np.cos(lb)*np.sin(np.radians(right[1]-left[1])/2)**2
    horizontal=6880.13*np.arcsin(np.sqrt(np.clip(h,0,1)))
    vertical=np.abs(left[2]-right[2])
    heading=np.abs((left[3]-right[3]+180)%360-180)
    # Admission uses 20.3 NM for every heading or 1,100 ft, deliberately more
    # conservative than the displayed 10/20 NM or 1,000 ft test criteria.
    threshold=20.3 if margin else np.where(heading<=25,20,10)
    if terminal_mixed:
        from astra.studies.separation_policy import low_terminal,TERMINAL_MIXED_HORIZONTAL_NM
        inside=low_terminal(*left[:3])&low_terminal(*right[:3])
        threshold=np.where(inside,TERMINAL_MIXED_HORIZONTAL_NM+(.3 if margin else 0),threshold)
    violation=(horizontal<threshold)&(vertical<(1100 if margin else 1000))
    return dict(violations=int(violation.sum()),minimum_horizontal_nm=float(horizontal.min()),
                minimum_vertical_ft=float(vertical.min()))


def build(case_id,root=ROOT):
    if CASES[case_id].get('mode')=='full_cycle':
        from astra.studies.full_cycle import build_full_cycle
        return build_full_cycle(case_id,root)
    spec=CASES[case_id];placed=[];metadata=[];transfers=[]
    for index,procedure in enumerate(spec['procedures']):
        original,transfer,gate,inbound,centre_route=trajectory(procedure)
        offset=0
        while offset<=14400:
            path=original.copy();path[:,0]+=offset
            gap_ok=not inbound or all(abs(transfer+offset-t['time_s'])>=125 for t in transfers if t['direction']=='arrival')
            if gap_ok and all(not pair_audit(path,old,margin=True)['violations'] for old in placed):break
            offset+=10
        else:raise ValueError('Could not admit synthetic traffic with the required separation')
        callsign=f'TST{case_id.split("_")[-1][:2].upper()}{index+1:02d}'
        direction='arrival' if inbound else 'departure'
        stamp=lambda seconds:(START+timedelta(seconds=float(seconds))).isoformat(timespec='seconds')
        event=path[-1,0] if inbound else path[0,0]
        metadata.append(dict(callsign=callsign,aircraft_type='A320',direction=direction,
            adep='VVNB' if inbound else 'VVTS',ades='VVTS' if inbound else 'VVNB',
            runway='25R' if inbound else '25L',procedure=procedure,centre_route=centre_route,
            simulated_slot_utc=stamp(event),planned_event_utc=stamp(event),
            first_track_utc=stamp(path[0,0]),last_track_utc=stamp(path[-1,0]),
            evidence='synthetic_system_test',synthetic=True))
        transfers.append(dict(callsign=callsign,direction=direction,time_s=round(transfer+offset,3),
                              procedure=procedure,**gate))
        placed.append(path)
    pair_checks=[]
    for i,a in enumerate(placed):
        for j in range(i+1,len(placed)):
            pair_checks.append(dict(left=metadata[i]['callsign'],right=metadata[j]['callsign'],**pair_audit(a,placed[j])))
    arrivals=sorted((t for t in transfers if t['direction']=='arrival'),key=lambda t:t['time_s'])
    gaps=[round(b['time_s']-a['time_s'],3) for a,b in zip(arrivals,arrivals[1:])]
    if any(p['violations'] for p in pair_checks) or any(gap<120 for gap in gaps):
        raise ValueError('Synthetic test audit failed; package was not published')
    duration=math.ceil(max(p[-1,0] for p in placed))+35
    folder=Path(root)/case_id;folder.mkdir(parents=True,exist_ok=True)
    fields=['flight_id','callsign','aircraft_type','adep','ades','time_utc','lat','lon','altitude_ft',
            'ground_speed_kt','heading_deg','vertical_speed_fpm','on_ground','source']
    with (folder/'tracks.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for f,path in zip(metadata,placed):
            for t,lat,lon,alt,speed,heading,vs in path:
                writer.writerow(dict(flight_id=f['callsign'],callsign=f['callsign'],aircraft_type='A320',
                    adep=f['adep'],ades=f['ades'],time_utc=stamp(t),lat=lat,lon=lon,altitude_ft=alt,
                    ground_speed_kt=speed,heading_deg=heading,vertical_speed_fpm=vs,
                    on_ground=False,source='SYNTHETIC_SYSTEM_TEST'))
    audit=dict(sample_s=1,horizontal_nm=10,same_heading_horizontal_nm=20,same_heading_tolerance_deg=25,
        vertical_ft=1000,separation_logic='horizontal >= threshold OR vertical >= 1000 ft',
        admission_buffer_horizontal_nm=.3,admission_buffer_vertical_ft=100,
        transfer_minimum_s=120,minimum_arrival_transfer_gap_s=min(gaps) if gaps else None,
        violating_pairs=sum(bool(p['violations']) for p in pair_checks),pair_checks=pair_checks,
        transfer_events=transfers,arrival_transfer_gaps_s=gaps)
    manifest=dict(case_id=case_id,label=spec['label'],basis=spec['description'],synthetic=True,
        system_test_version=VERSION,local_start=START.isoformat(),local_end=stamp(duration),
        duration_s=duration,connected_fir=True,
        counts=dict(total=len(metadata),arrivals=sum(f['direction']=='arrival' for f in metadata),
                    departures=sum(f['direction']=='departure' for f in metadata)),
        flights=metadata,separation_audit=audit,limitations=[
            'Synthetic functional test; not real FPL, observed traffic or an ATFM case study.',
            'Paths are generated by the existing procedure propagator and checked on a one-second grid.',
            'Departure tracks begin at the runway; taxi movements are not part of these fixtures.',
            '40 NM transfer fixes are study boundary intersections, not published transfer agreements.'])
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return manifest
