"""Synthetic VVTS-context ATFM experiment. Python standard library only.
No real TMA geometry, declared capacity, tactical separation or operational clearance.
Run: python demo.py --out results
"""
import argparse, csv, json, math, random, statistics, time
from pathlib import Path


def make_scenario():
    rng = random.Random(20260929)
    counts = [5, 6, 10, 10, 8, 6, 5, 4]
    flights = []
    for window, count in enumerate(counts):
        for k in range(count):
            eta = round(window * 15 + (k + .5) * 15 / count + rng.uniform(-.25, .25), 2)
            i = len(flights)
            # Pre-tactical decision at t=-60; fixed flights are already airborne.
            eligible = i % 5 != 0
            lead = rng.choice([35, 45, 55]) if eligible else 90
            flights.append(dict(id=f'SYN{i+1:03}', gate=['G_N','G_E','G_W'][i%3],
                aircraft_type=['A320','A321','B789'][i%3], eta_min=eta,
                dwell_min=[18,20,24][i%3], ground_eligible=eligible,
                reference_takeoff_min=eta-lead, travel_to_entry_min=lead))
            if not eligible:
                # Ensure flight was already airborne at the planning instant.
                flights[-1]['reference_takeoff_min'] = -70
                flights[-1]['travel_to_entry_min'] = eta+70
    return dict(name='VVTS_SYNTHETIC_ATFM_01', synthetic=True, decision_min=-60,
        note='All demand, capacities, gates and timings are study assumptions, not VVTS operational values.',
        demand_counts_15min=counts, entry_capacity_15min=[6,6,4,4,6,6,6,6],
        tail_capacity_15min=6, occupancy_limit=8, max_ground_delay_min=30,
        weights=dict(ground=1,airborne=4,max_delay=.2), flights=flights)


def validate(s):
    assert s['synthetic'] in (True, False)
    assert s['occupancy_limit'] > 0 and s['tail_capacity_15min'] > 0
    assert all(c > 0 for c in s['entry_capacity_15min'])
    assert len({f['id'] for f in s['flights']}) == len(s['flights'])
    for f in s['flights']:
        assert f['dwell_min'] > 0
        assert abs(f['reference_takeoff_min']+f['travel_to_entry_min']-f['eta_min']) < 1e-6
        if f['ground_eligible']:
            assert f['reference_takeoff_min'] >= s['decision_min']
        else:
            assert f['reference_takeoff_min'] < s['decision_min']


def simulate(s, genes):
    fs = s['flights']
    assert len(genes) == len(fs)
    for f,g in zip(fs,genes):
        assert 0 <= g <= s['max_ground_delay_min']
        assert f['ground_eligible'] or g == 0
    # One pooled arrival-entry resource. Fixed-bin rates spread into uniform slots.
    # Slots are modelling conventions, NOT separation minima.
    requests = sorted(range(len(fs)),key=lambda i:(fs[i]['eta_min']+genes[i],fs[i]['id']))
    admitted=[]; rows=[]; last_slot=-1e9; window=0; k=0
    for i in requests:
        f=fs[i]; request=f['eta_min']+genes[i]
        while True:
            caps=s['entry_capacity_15min']
            cap=caps[window] if window<len(caps) else s['tail_capacity_15min']
            if k>=cap:
                window+=1; k=0; continue
            slot=15*window + k*15/cap
            k+=1
            if slot+1e-9<request or slot<=last_slot: continue
            admitted=[exit_t for exit_t in admitted if exit_t>slot+1e-9]
            if len(admitted)>=s['occupancy_limit']: continue
            break
        admitted.append(slot+f['dwell_min']); last_slot=slot
        air=slot-request
        rows.append(dict(**f,ground_delay_min=genes[i],request_min=round(request,5),
                         entry_min=slot,exit_min=slot+f['dwell_min'],airborne_delay_min=air,
                         total_delay_min=genes[i]+air))
    gs=sum(r['ground_delay_min'] for r in rows); air=sum(r['airborne_delay_min'] for r in rows)
    ds=sorted(r['total_delay_min'] for r in rows)
    weights=s['weights']
    events=sorted([(r['entry_min'],1) for r in rows]+[(r['exit_min'],-1) for r in rows])
    occ=0; peak=0
    for _,delta in events: occ+=delta; peak=max(peak,occ)
    objective=weights['ground']*gs+weights['airborne']*air+weights['max_delay']*max(ds,default=0)
    metrics=dict(objective=objective,ground_delay_min=gs,airborne_delay_min=air,
        total_delay_min=gs+air,mean_delay_min=statistics.mean(ds) if ds else 0,
        p95_delay_min=ds[max(0,math.ceil(.95*len(ds))-1)] if ds else 0,
        max_delay_min=max(ds,default=0),peak_occupancy=peak,flights_completed=len(rows),
        final_exit_min=max((r['exit_min'] for r in rows),default=0))
    return metrics,rows


def fcfs_plan(s):
    # Move eligible flights' baseline airborne waiting to the ground, preserving
    # the baseline target entry as far as the 30-minute bound permits.
    _,rows=simulate(s,[0]*len(s['flights']))
    by_id={r['id']:r for r in rows}
    return [min(s['max_ground_delay_min'],max(0,math.floor(by_id[f['id']]['airborne_delay_min'])))
            if f['ground_eligible'] else 0 for f in s['flights']]


def optimize(s,seed,popsize=60,generations=100):
    rng=random.Random(seed); n=len(s['flights']); bound=s['max_ground_delay_min']
    mutable=[i for i,f in enumerate(s['flights']) if f['ground_eligible']]
    base=fcfs_plan(s)
    def mutate(x,rate=.12):
        out=x[:]
        for i in mutable:
            if rng.random()<rate:
                out[i]=max(0,min(bound,out[i]+rng.choice([-4,-2,-1,1,2,4])))
        return out
    population=[base,[0]*n]+[mutate(base,.55) for _ in range(popsize-2)]
    cache={}; history=[]
    def score(x):
        key=tuple(x)
        if key not in cache: cache[key]=simulate(s,x)[0]['objective']
        return cache[key]
    for generation in range(generations+1):
        population.sort(key=score)
        history.append(dict(generation=generation,best_objective=score(population[0])))
        if generation==generations: break
        def parent(): return min(rng.sample(population,3),key=score)
        nxt=[x[:] for x in population[:2]]
        while len(nxt)<popsize:
            a,b=parent(),parent()
            child=[a[i] if rng.random()<.5 else b[i] for i in range(n)]
            nxt.append(mutate(child))
        population=nxt
    return population[0],history,len(cache)


def write_csv(path,rows):
    if not rows: return
    with path.open('w',encoding='utf-8-sig',newline='') as h:
        w=csv.DictWriter(h,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)


def check(s,genes,rows):
    assert len(rows)==len(s['flights'])
    assert len({r['id'] for r in rows})==len(rows)
    events=[]; bins={}
    for r in rows:
        assert r['entry_min']+1e-7>=r['request_min']
        assert r['ground_eligible'] or r['ground_delay_min']==0
        assert r['ground_delay_min']<=s['max_ground_delay_min']
        assert abs(r['total_delay_min']-(r['entry_min']-r['eta_min']))<1e-6
        b=int((r['entry_min']+1e-8)//15); bins[b]=bins.get(b,0)+1
        events.extend([(r['entry_min'],1),(r['exit_min'],-1)])
    occ=0
    for _,d in sorted(events):
        occ+=d; assert 0<=occ<=s['occupancy_limit']
    assert occ==0
    for b,count in bins.items():
        caps=s['entry_capacity_15min']; assert count<=(caps[b] if b<len(caps) else s['tail_capacity_15min'])


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--scenario',type=Path)
    parser.add_argument('--out',type=Path,default=Path('results'))
    parser.add_argument('--generations',type=int,default=100); parser.add_argument('--population',type=int,default=60)
    args=parser.parse_args(); assert args.population>=4 and args.generations>=0
    s=json.loads(args.scenario.read_text(encoding='utf-8')) if args.scenario else make_scenario()
    validate(s); args.out.mkdir(parents=True,exist_ok=True)
    (args.out/'scenario.json').write_text(json.dumps(s,indent=2,ensure_ascii=False),encoding='utf-8')
    write_csv(args.out/'flights_input.csv',s['flights'])
    plans={'BASELINE':[0]*len(s['flights']),'FCFS_ATFM':fcfs_plan(s)}
    summary=[]; all_rows={}; seed_metrics=[]; start=time.perf_counter()
    for seed in [11,22,33,44,55]:
        genes,history,evaluations=optimize(s,seed,args.population,args.generations)
        metrics,rows=simulate(s,genes); check(s,genes,rows)
        seed_metrics.append(dict(seed=seed,evaluations=evaluations,**metrics))
        plans[f'GA_{seed}']=genes
        write_csv(args.out/f'convergence_{seed}.csv',history)
    for name,genes in plans.items():
        metrics,rows=simulate(s,genes); check(s,genes,rows)
        summary.append(dict(method=name,**metrics)); all_rows[name]=rows
        write_csv(args.out/f'{name}_flights.csv',rows)
    write_csv(args.out/'metrics.csv',summary); write_csv(args.out/'ga_seeds.csv',seed_metrics)
    (args.out/'results.json').write_text(json.dumps(dict(scenario=s,summary=summary,runs=all_rows,
        elapsed_s=time.perf_counter()-start),indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(summary,indent=2)); print('All capacity, occupancy, delay and conservation checks passed.')

if __name__=='__main__': main()
