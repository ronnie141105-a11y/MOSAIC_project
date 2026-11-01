"""FCFS chronology, inherited demand and controlled surface priority."""
from types import SimpleNamespace
import numpy as np

from astra.optimization.fcfs import fcfs_plan
from astra.optimization.full_route_cases import summarize_native
from astra.studies.operational_cases import controlled_departure_order


def traffic(arrivals=1,full=False):
    n=arrivals+2;options=((0,0),(1,1),(1,2),(1,3))
    metadata=[dict(callsign=f'A{i}',direction='arrival') for i in range(arrivals)]
    metadata += [dict(callsign='D002',direction='departure'),dict(callsign='D001',direction='departure')]
    masks=np.zeros((1,n,4,8),dtype=int)
    masks[:,:arrivals,:,:]=1 if full else 0
    if not full:masks[:,:arrivals,:,0:2]=1
    for i in range(arrivals,n):
        for code in range(4):masks[0,i,code,1+code]=1
    pi,pj=np.triu_indices(n,1)
    flags=np.zeros(len(pi),dtype=bool)
    return SimpleNamespace(n=n,options=options,metadata=metadata,sample_s=60,
        domains=[(0,)]*arrivals+[tuple(range(4))]*2,occupancy_masks=masks,
        events=np.array([[0]*4]*arrivals+[[60,120,180,240]]*2),pair_i=pi,pair_j=pj,
        s=dict(sectors=[dict(capacity=1)],minimum_takeoff_gap_s=120),
        state=lambda *args,**kw:dict(conflicts=flags,runway=flags,sequence=flags),
        decode=lambda codes:[list(options[c]) for c in codes])


def test_fcfs_ready_time_ties_and_earliest_capacity_slot():
    e=traffic();plan,info=fcfs_plan(e)
    assert info['departure_order']==['D001','D002']
    assert plan==[[0,0],[1,3],[1,1]]
    assert info['domain_exhaustions']==0
    assert [d['proposed_takeoff_s'] for d in info['decisions']]==[120,240]


def test_fcfs_uses_fixed_readiness_and_retains_committed_prefix():
    from datetime import datetime,timezone,timedelta
    e=traffic();start=datetime(2026,10,31,tzinfo=timezone.utc);e.start=start.timestamp()
    e.metadata[-2]['requested_event_utc']=(start+timedelta(seconds=10)).isoformat()
    e.metadata[-1]['requested_event_utc']=(start+timedelta(seconds=20)).isoformat()
    assert fcfs_plan(e)[1]['departure_order']==['D002','D001']
    e.metadata[-1]['origin_status_at_planning']='TAXIING'
    assert fcfs_plan(e)[1]['departure_order']==['D001','D002']


def test_fcfs_reports_unavoidable_arrival_excess_and_finite_domain():
    e=traffic(arrivals=2,full=True);plan,info=fcfs_plan(e)
    assert info['inherited_arrival_excess_aircraft_minutes']==8
    assert info['domain_exhaustions']==2
    assert plan[2:]==[[1,3],[1,3]]
    assert all('SECTOR_CAPACITY' in d['unresolved_reasons'] for d in info['decisions'])


def test_all_methods_preserve_the_frozen_physical_queue():
    flights=[dict(callsign=cs,direction='departure') for cs in ('D1','D2','D3')]
    old={cs:dict(ctot_s=t,origin_status_at_planning='PARKED',queue_rank=i)
         for i,(cs,t) in enumerate((('D1',100),('D2',200),('D3',300)))}
    old['D1']['origin_status_at_planning']='HOLDING'
    earliest={cs:dict(ctot_s=t) for cs,t in (('D1',1000),('D2',800),('D3',400))}
    assert controlled_departure_order(flights,old,earliest,'optimized')==['D1','D2','D3']
    assert controlled_departure_order(flights,old,earliest,'fcfs')==['D1','D2','D3']


def test_native_summary_includes_all_seeds_with_sample_standard_deviation():
    trials=[]
    for method,values in [('NO_CONTROL',[0]),('FCFS',[6]),('TEAM_GROUND',[2,4,6]),('TEAM_MIXED',[1,2,3])]:
        for value in values:
            trials.append(dict(method=method,metrics=dict(total_delay_min=value,separation_conflict_pairs=0,
                runway_spacing_pairs=0,arrival_transfer_spacing_pairs=0,feasible_sampled=True)))
    rows={r['method']:r for r in summarize_native(trials)}
    assert rows['TEAM_GROUND']['runs']==3
    assert rows['TEAM_GROUND']['mean_total_delay_min']==4
    assert rows['TEAM_GROUND']['std_total_delay_min']==2
    assert rows['FCFS']['std_total_delay_min']==0


def test_native_summary_supports_one_coordinated_ga():
    trials=[dict(method=m,metrics=dict(total_delay_min=d,separation_conflict_pairs=0,
        runway_spacing_pairs=0,arrival_transfer_spacing_pairs=0,feasible_sampled=True))
        for m,d in [('NO_CONTROL',3),('FCFS',3),('TEAM_MIXED',2)]]
    rows=summarize_native(trials)
    assert {r['method'] for r in rows}=={'NO_CONTROL','FCFS','TEAM_MIXED'}
