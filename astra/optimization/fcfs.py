"""Bounded, capacity-regulated FCFS benchmark for the frozen study traffic.

The request clock is the modelled earliest takeoff slot. Already-airborne
arrivals are committed traffic, not requests that can be held at an origin.
"""
import time
import numpy as np


def fcfs_plan(evaluator):
    if getattr(evaluator,'flow',False):return flow_fcfs_plan(evaluator)
    e=evaluator;started=time.perf_counter();codes=np.zeros(e.n,dtype=int)
    committed=np.asarray([f['direction']=='arrival' for f in e.metadata])
    occupied=e.occupancy_masks[:,np.flatnonzero(committed),0,:].sum(axis=1)
    capacities=np.asarray([s['capacity'] for s in e.s['sectors']])[:,None]
    inherited=float(np.maximum(occupied-capacities,0).sum()*e.sample_s/60)
    from datetime import datetime
    def request(i):
        f=e.metadata[i]
        return datetime.fromisoformat(f['requested_event_utc']).timestamp()-e.start if 'requested_event_utc' in f else e.events[i,0]
    order=sorted(np.flatnonzero(~committed),key=lambda i:(0 if e.metadata[i].get('origin_status_at_planning','PARKED')!='PARKED' else 1,request(i),e.metadata[i]['callsign']))
    decisions=[];previous=-float('inf');tests=0
    for i in order:
        candidates=sorted((c for c in e.domains[i] if e.options[c][0] in (0,1)),
                          key=lambda c:(e.events[i,c],c))
        chosen=None;last_reasons=[]
        active=committed.copy();active[i]=True
        involved=active[e.pair_i]&active[e.pair_j]&((e.pair_i==i)|(e.pair_j==i))
        for code in candidates:
            tests+=1;trial=codes.copy();trial[i]=code
            counts=occupied+e.occupancy_masks[:,i,code,:]
            state=e.state(trial,sector_counts=counts)
            reasons=[]
            if e.events[i,code]<previous+e.s.get('minimum_takeoff_gap_s',120)-1e-6:reasons.append('FCFS_ORDER')
            if np.any(involved&(state['conflicts']|state['runway']|state['sequence'])):reasons.append('SAFETY_OR_COMMITTED_ORDER')
            if np.any(np.maximum(counts-capacities,0)>np.maximum(occupied-capacities,0)):reasons.append('SECTOR_CAPACITY')
            if not reasons:chosen=code;break
            last_reasons=reasons
        exhausted=chosen is None
        if exhausted:
            # Both methods have the same finite action domain. Do not give
            # FCFS an unreported unlimited hold, or call this choice feasible.
            chosen=candidates[-1]
        codes[i]=chosen;committed[i]=True
        occupied+=e.occupancy_masks[:,i,chosen,:]
        previous=float(e.events[i,chosen])
        decisions.append(dict(callsign=e.metadata[i]['callsign'],request_time_s=float(request(i)),
            proposed_takeoff_s=previous,ground_delay_min=e.options[chosen][1],
            domain_exhausted=exhausted,unresolved_reasons=last_reasons if exhausted else []))
    return e.decode(codes),dict(policy='FCFS_READY_TIME',request_clock='fixed requested ready-event; committed surface prefix first',
        arrival_policy='frozen airborne trajectories; no origin GDP or arrival speed control',
        departure_order=[e.metadata[i]['callsign'] for i in order],decisions=decisions,
        domain_exhaustions=sum(d['domain_exhausted'] for d in decisions),
        inherited_arrival_excess_aircraft_minutes=inherited,candidate_checks=tests,
        planning_elapsed_s=time.perf_counter()-started)


def flow_fcfs_plan(e):
    """FIFO at each origin/physical queue, with a shared gate/capacity check."""
    from datetime import datetime
    started=time.perf_counter();codes=np.zeros(e.n,dtype=int)
    committed=np.asarray([f['direction']=='arrival' and not f.get('origin_pending') for f in e.metadata])
    occupied=e.occupancy_masks[:,np.flatnonzero(committed),0,:].sum(axis=1)
    capacities=np.asarray([s['capacity'] for s in e.s['sectors']])[:,None]
    groups={}
    for i,f in enumerate(e.metadata):
        if not committed[i]:groups.setdefault(f['adep'],[]).append(i)
    for origin,indices in groups.items():indices.sort(key=lambda i:e.metadata[i].get('origin_queue_rank',e.metadata[i].get('queue_rank',0)))
    decisions=[];order=[];tests=0
    while any(groups.values()):
        def request(i):
            f=e.metadata[i]
            if f['direction']=='departure' and f.get('origin_status_at_planning')!='PARKED':return -1e9
            return f.get('origin_requested_ctot_s',datetime.fromisoformat(f['requested_event_utc']).timestamp()-e.start)
        i=min((v[0] for v in groups.values() if v),key=lambda i:(request(i),e.metadata[i]['callsign']))
        groups[e.metadata[i]['adep']].pop(0);order.append(i)
        candidates=sorted((c for c in e.domains[i] if e.options[c][0] in (0,1)),key=lambda c:(e.events[i,c],c))
        active=committed.copy();active[i]=True
        involved=active[e.pair_i]&active[e.pair_j]&((e.pair_i==i)|(e.pair_j==i))
        chosen=None;reasons=[]
        for code in candidates:
            tests+=1;trial=codes.copy();trial[i]=code;counts=occupied+e.occupancy_masks[:,i,code,:]
            state=e.state(trial,sector_counts=counts);reasons=[]
            if np.any(involved&(state['conflicts']|state['runway']|state['transfer']|state['sequence'])):reasons.append('SAFETY_GATE_OR_FIXED_ORDER')
            if np.any(np.maximum(counts-capacities,0)>np.maximum(occupied-capacities,0)):reasons.append('SECTOR_CAPACITY')
            if not reasons:chosen=code;break
        exhausted=chosen is None
        if exhausted:chosen=candidates[-1]
        codes[i]=chosen;committed[i]=True;occupied+=e.occupancy_masks[:,i,chosen,:]
        decisions.append(dict(callsign=e.metadata[i]['callsign'],origin=e.metadata[i]['adep'],ground_delay_min=e.options[chosen][1],
            domain_exhausted=exhausted,unresolved_reasons=reasons if exhausted else []))
    return e.decode(codes),dict(policy='FIXED_ORIGIN_FIFO_WITH_SHARED_MIT_MINIT',request_clock='Fixed origin readiness; physical local queue retained',
        action_step_min=e.s['ground_action_step_min'],decisions=decisions,departure_order=[e.metadata[i]['callsign'] for i in order],
        candidate_checks=tests,domain_exhaustions=sum(d['domain_exhausted'] for d in decisions),
        planning_elapsed_s=time.perf_counter()-started)
