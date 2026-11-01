"""Synthetic flow optimization: ground delay plus upstream speed absorption.
This is an arrival-entry model, not operational ATC separation or fuel modelling.
"""
from copy import deepcopy
import math
import random
import statistics
import time
from . import flow_core as core


def scenario():
    s=core.make_scenario()
    s.update(name='VVTS_SYNTHETIC_MULTI_ATFM_02',max_speed_delay_min=4,
             upstream_segment_min=20,nominal_ground_speed_kt=300)
    s['weights']['speed']=2
    return s


def evaluate(s, plan):
    n=len(s['flights'])
    if len(plan)!=2*n: raise ValueError('Plan must contain ground and speed genes for every flight')
    ground,speed=list(plan[:n]),list(plan[n:])
    for f,g,v in zip(s['flights'],ground,speed):
        if not all(isinstance(x,(int,float)) and math.isfinite(x) for x in (g,v)):
            raise ValueError('Delay genes must be finite numbers')
        if not 0<=g<=s['max_ground_delay_min'] or (not f['ground_eligible'] and g!=0):
            raise ValueError('Invalid ground delay')
        if not 0<=v<=s['max_speed_delay_min']: raise ValueError('Invalid speed absorption')
        if f['eta_min']-s['upstream_segment_min']<s['decision_min']:
            raise ValueError('Speed segment must be entirely after decision time')
    shifted=deepcopy(s)
    for f,v in zip(shifted['flights'],speed): f['eta_min']+=v
    _,rows=core.simulate(shifted,ground)
    original={f['id']:(f,v) for f,v in zip(s['flights'],speed)}
    for r in rows:
        f,v=original[r['id']]
        r.update(eta_min=f['eta_min'],speed_delay_min=v,
                 upstream_ground_speed_kt=s['nominal_ground_speed_kt']*s['upstream_segment_min']/(s['upstream_segment_min']+v))
        r['total_delay_min']=r['entry_min']-f['eta_min']
    delays=sorted(r['total_delay_min'] for r in rows)
    metrics=dict(ground_delay_min=sum(ground),speed_delay_min=sum(speed),
        airborne_holding_min=sum(r['airborne_delay_min'] for r in rows),
        total_delay_min=sum(delays),max_delay_min=max(delays,default=0),
        p95_delay_min=delays[max(0,math.ceil(.95*n)-1)] if n else 0,
        completed=n,final_exit_min=max((r['exit_min'] for r in rows),default=0))
    metrics['airborne_extra_min']=metrics['speed_delay_min']+metrics['airborne_holding_min']
    w=s['weights']
    metrics['objective']=(w['ground']*metrics['ground_delay_min']+w['speed']*metrics['speed_delay_min']
        +w['airborne']*metrics['airborne_holding_min']+w['max_delay']*metrics['max_delay_min'])
    events=sorted([(r['entry_min'],1) for r in rows]+[(r['exit_min'],-1) for r in rows])
    occ=0; peak=0
    for _,d in events: occ+=d;peak=max(peak,occ)
    metrics['peak_occupancy']=peak
    return metrics,rows


def heuristic(s,mixed=False):
    n=len(s['flights']); ground=core.fcfs_plan(s); speed=[0]*n
    if mixed:
        _,rows=evaluate(s,ground+speed); byid={r['id']:r for r in rows}
        speed=[min(s['max_speed_delay_min'],max(0,math.floor(byid[f['id']]['airborne_delay_min']))) for f in s['flights']]
    return ground+speed


def optimize(s,mode='mixed',seed=11,population=60,generations=100):
    if mode not in ('ground','mixed'): raise ValueError('Unknown measure set')
    if not 4<=population<=100 or not 0<=generations<=200: raise ValueError('Invalid GA budget')
    rng=random.Random(seed); n=len(s['flights']); cache={}
    bounds=[s['max_ground_delay_min'] if f['ground_eligible'] else 0 for f in s['flights']]
    bounds += [s['max_speed_delay_min'] if mode=='mixed' else 0]*n
    def mutate(x,rate=.12):
        y=x[:]
        for i,b in enumerate(bounds):
            if b and rng.random()<rate:
                y[i]=max(0,min(b,y[i]+rng.choice([-4,-2,-1,1,2,4])))
        return y
    def score(x):
        key=tuple(x)
        if key not in cache: cache[key]=evaluate(s,x)[0]['objective']
        return cache[key]
    initial=heuristic(s,mode=='mixed')
    pop=[initial,heuristic(s),[0]*(2*n)]+[mutate(initial,.5) for _ in range(population-3)]
    history=[]
    for generation in range(generations+1):
        pop.sort(key=score);history.append(dict(generation=generation,objective=score(pop[0])))
        if generation==generations:break
        def parent():return min(rng.sample(pop,3),key=score)
        children=[p[:] for p in pop[:2]]
        while len(children)<population:
            a,b=parent(),parent();children.append(mutate([x if rng.random()<.5 else y for x,y in zip(a,b)]))
        pop=children
    return pop[0],history,len(cache)


def audit(s,plan,rows):
    expected={f['id'] for f in s['flights']}
    if {r['id'] for r in rows}!=expected or len(rows)!=len(expected): raise ValueError('Flight conservation failed')
    bins={};events=[]
    for r in rows:
        if abs(r['total_delay_min']-(r['ground_delay_min']+r['speed_delay_min']+r['airborne_delay_min']))>1e-6:
            raise ValueError('Delay accounting failed')
        if r['airborne_delay_min'] < -1e-7: raise ValueError('Negative holding')
        b=int((r['entry_min']+1e-8)//15);bins[b]=bins.get(b,0)+1
        events.extend([(r['entry_min'],1),(r['exit_min'],-1)])
    for b,count in bins.items():
        caps=s['entry_capacity_15min'];cap=caps[b] if b<len(caps) else s['tail_capacity_15min']
        if count>cap:raise ValueError('Entry capacity exceeded')
    occ=0
    for _,d in sorted(events):
        occ+=d
        if not 0<=occ<=s['occupancy_limit']:raise ValueError('Occupancy exceeded')
    return True


def experiment(seeds=(11,22,33,44,55),population=60,generations=100):
    start=time.perf_counter();s=scenario();core.validate(s);runs={}
    def record(name,plan,history=None,evaluations=0):
        metrics,rows=evaluate(s,plan);audit(s,plan,rows)
        runs[name]=dict(metrics=metrics,plan=plan,flights=rows,history=history or [],evaluations=evaluations)
    record('BASELINE',[0]*(2*len(s['flights'])))
    record('FCFS_GROUND',heuristic(s));record('FCFS_MIXED',heuristic(s,True))
    for mode in ['ground','mixed']:
        for seed in seeds:
            plan,history,count=optimize(s,mode,seed,population,generations)
            record(f'GA_{mode.upper()}_{seed}',plan,history,count)
    # Frozen plans, out-of-sample ETA perturbation; no reoptimization and no claim of robustness.
    stress=[]
    for noise_seed in [101,102,103]:
        perturbed=deepcopy(s);rng=random.Random(noise_seed)
        for f in perturbed['flights']:
            jitter=rng.uniform(-2,2);f['eta_min']+=jitter;f['travel_to_entry_min']+=jitter
        for name,run in runs.items():
            m,r=evaluate(perturbed,run['plan']);audit(perturbed,run['plan'],r)
            stress.append(dict(method=name,noise_seed=noise_seed,**m))
    sensitivity=[]
    for weight in [1,2,4]:
        for name,run in runs.items():
            m=run['metrics'];sensitivity.append(dict(method=name,speed_weight=weight,
                rescored_objective=m['ground_delay_min']+weight*m['speed_delay_min']+4*m['airborne_holding_min']+.2*m['max_delay_min']))
    return dict(scenario=s,runs=runs,stress=stress,sensitivity=sensitivity,
        settings=dict(seeds=list(seeds),population=population,generations=generations),elapsed_s=time.perf_counter()-start,
        limitations=['Synthetic arrival-entry flow model; no validated VVTS capacity or 4D separation.',
        'Speed absorption over a hypothetical upstream 100 NM segment: 300 to 250 kt ground speed, no wind/fuel model.',
        'Replay is visualization of optimized event times, not independent kinematic validation.',
        'Frozen-plan ETA stress and weight re-scoring only; not robust optimization.'])
