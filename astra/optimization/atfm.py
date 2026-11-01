"""Synthetic flow optimization: ground delay plus upstream speed absorption.
This is an arrival-entry model, not operational ATC separation or fuel modelling.
"""
from copy import deepcopy
from itertools import product
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


def transfer_delay(s, plan, flight_index, amount):
    """Move ground delay to speed absorption; negative amounts reverse it.

    Preserve the flight's request time exactly. Reject infeasible transfers
    instead of clipping one gene and inadvertently changing that time.
    """
    n = len(s['flights'])
    if len(plan) != 2*n or not 0 <= flight_index < n:
        raise ValueError('Invalid transfer plan or flight index')
    if not isinstance(amount, (int, float)) or not math.isfinite(amount):
        raise ValueError('Transfer must be finite')
    i = flight_index
    ground, speed = plan[i] - amount, plan[n+i] + amount
    ground_bound = s['max_ground_delay_min'] if s['flights'][i]['ground_eligible'] else 0
    if not 0 <= ground <= ground_bound or not 0 <= speed <= s['max_speed_delay_min']:
        raise ValueError('Delay transfer exceeds available measures')
    out = list(plan)
    out[i], out[n+i] = ground, speed
    return out


def _mutate(s, plan, mode, rng, rate=.12):
    n = len(s['flights'])
    out = list(plan)
    steps = (-4, -2, -1, 1, 2, 4)
    if mode == 'ground':
        for i, f in enumerate(s['flights']):
            if f['ground_eligible'] and rng.random() < rate:
                out[i] = max(0, min(s['max_ground_delay_min'], out[i]+rng.choice(steps)))
        return out
    for i, f in enumerate(s['flights']):
        if rng.random() >= rate:
            continue
        if f['ground_eligible'] and rng.random() < .5:
            feasible = [d for d in steps if
                        0 <= out[i]-d <= s['max_ground_delay_min'] and
                        0 <= out[n+i]+d <= s['max_speed_delay_min']]
            if feasible:
                out = transfer_delay(s, out, i, rng.choice(feasible))
                continue
        # Also change timing: transfers alone cannot change the entry order.
        gene = rng.choice((i, n+i)) if f['ground_eligible'] else n+i
        bound = s['max_ground_delay_min'] if gene < n else s['max_speed_delay_min']
        out[gene] = max(0, min(bound, out[gene]+rng.choice(steps)))
    return out


def optimize(s, mode='mixed', seed=11, population=60, generations=100,
             *, incumbent=None, max_evaluations=None, diagnostics=None,
             fitness=None, evaluation_cost=1):
    """Bounded GA, preserving the existing (plan, history, count) API.

    An explicit incumbent is scored and kept by elitism. The mixed search
    inherits a ground-only incumbent in experiment(); its preparation cost
    is charged to the same total evaluation budget as the ground search.
    An optional fitness(plan) returns (score, nominal_rows). evaluation_cost
    counts its underlying scenario simulations; budget/history use that unit.
    """
    if mode not in ('ground', 'mixed'):
        raise ValueError('Unknown measure set')
    if type(population) is not int or type(generations) is not int or not 4 <= population <= 100 or not 0 <= generations <= 200:
        raise ValueError('Invalid GA budget')
    if max_evaluations is None:
        max_evaluations = population + (population-2)*generations
    if type(evaluation_cost) is not int or evaluation_cost < 1:
        raise ValueError('Evaluation cost must be a positive integer')
    if fitness is not None and not callable(fitness):
        raise ValueError('Fitness must be callable')
    if type(max_evaluations) is not int or max_evaluations < evaluation_cost:
        raise ValueError('Evaluation budget must cover at least one fitness evaluation')
    start = time.perf_counter()
    rng = random.Random(seed)
    n = len(s['flights'])
    cache = {}
    bootstrap_rows = {}
    best_plan, best_score = None, float('inf')

    class BudgetExhausted(Exception):
        pass

    def score(plan, capture_rows=False):
        nonlocal best_plan, best_score
        key = tuple(plan)
        if key not in cache:
            if (len(cache)+1)*evaluation_cost > max_evaluations:
                raise BudgetExhausted
            if fitness is None:
                metrics, rows = evaluate(s, plan)
                value = metrics['objective']
            else:
                value, rows = fitness(plan)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError('Fitness must return a finite score')
            cache[key] = value
            if capture_rows:
                bootstrap_rows[key] = rows
        if cache[key] < best_score:
            best_plan, best_score = list(plan), cache[key]
        return cache[key]

    # Score the incumbent first, even if the budget ends in generation zero.
    if incumbent is not None:
        if len(incumbent) != 2*n or (mode == 'ground' and any(incumbent[n:])):
            raise ValueError('Incumbent does not match the measure set')
        score(incumbent, capture_rows=True)
    # Build heuristics from cached evaluations, charging their preparation
    # to the fitness budget too. Retain rows only for these few seed plans.
    bootstrap_exhausted = False
    try:
        zero = [0]*(2*n)
        score(zero, capture_rows=True)
        by_id = {r['id']: r for r in bootstrap_rows[tuple(zero)]}
        ground = [min(s['max_ground_delay_min'], max(0, math.floor(by_id[f['id']]['airborne_delay_min'])))
                  if f['ground_eligible'] else 0 for f in s['flights']] + [0]*n
        score(ground, capture_rows=True)
        initial = ground[:]
        if mode == 'mixed':
            by_id = {r['id']: r for r in bootstrap_rows[tuple(ground)]}
            initial[n:] = [min(s['max_speed_delay_min'], max(0, math.floor(by_id[f['id']]['airborne_delay_min'])))
                           for f in s['flights']]
        pop = ([list(incumbent)] if incumbent is not None else [])
        pop += [initial, ground, zero]
    except BudgetExhausted:
        bootstrap_exhausted = True
        initial, pop = list(best_plan), [list(best_plan)]
    while len(pop) < population:
        source = rng.choice(pop[:4]) if incumbent is not None else initial
        pop.append(_mutate(s, source, mode, rng, .5))
    history = []
    stop_reason = 'generation_limit'
    for generation in range(generations+1):
        try:
            if bootstrap_exhausted:
                raise BudgetExhausted
            pop.sort(key=score)
        except BudgetExhausted:
            stop_reason = 'evaluation_limit'
            history.append(dict(generation=generation, objective=best_score, evaluations=len(cache)*evaluation_cost))
            break
        history.append(dict(generation=generation, objective=best_score, evaluations=len(cache)*evaluation_cost))
        if generation == generations:
            break
        def parent():
            return min(rng.sample(pop, 3), key=score)
        children = [list(best_plan), pop[1][:]]
        while len(children) < population:
            a, b = parent(), parent()
            if mode == 'mixed':
                # Inherit each flight's ground/speed pair together.
                sources = [a if rng.random() < .5 else b for _ in range(n)]
                child = [p[i] for i, p in enumerate(sources)] + [p[n+i] for i, p in enumerate(sources)]
            else:
                child = [x if rng.random() < .5 else y for x, y in zip(a, b)]
            children.append(_mutate(s, child, mode, rng))
        pop = children
    if diagnostics is not None:
        diagnostics.update(search_evaluations=len(cache), max_evaluations=max_evaluations,
                           simulation_evaluations=len(cache)*evaluation_cost,
                           evaluation_cost=evaluation_cost,
                           search_elapsed_s=time.perf_counter()-start,
                           stop_reason=stop_reason, generations_completed=history[-1]['generation'],
                           incumbent_objective=cache.get(tuple(incumbent)) if incumbent is not None else None)
    return best_plan, history, len(cache)


def exact_optimize(s, mode='mixed', *, max_combinations=100000):
    """Enumerate a SMALL scenario's integer-minute decision grid only.

    This checks GA optimality against the same flow evaluator, not the
    physical validity of that evaluator. Refuse large grids before work.
    """
    if mode not in ('ground', 'mixed'):
        raise ValueError('Unknown measure set')
    if type(max_combinations) is not int or max_combinations < 1:
        raise ValueError('Invalid enumeration limit')
    bounds = [s['max_ground_delay_min'] if f['ground_eligible'] else 0 for f in s['flights']]
    bounds += [s['max_speed_delay_min'] if mode == 'mixed' else 0]*len(s['flights'])
    if any(type(b) is not int or b < 0 for b in bounds):
        raise ValueError('Exact enumeration requires nonnegative integer bounds')
    count = math.prod(b+1 for b in bounds)
    if count > max_combinations:
        raise ValueError(f'Exact grid has {count} combinations; limit is {max_combinations}')
    best_plan, best_score = None, float('inf')
    for plan in product(*(range(b+1) for b in bounds)):
        value = evaluate(s, plan)[0]['objective']
        if value < best_score:
            best_plan, best_score = list(plan), value
    return best_plan, best_score, count


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


def small_case_benchmark(seeds=(11,22,33)):
    """Report optimality gaps on tractable integer-minute grids."""
    cases = []
    for name, count, low_demand in [('single_slot', 1, False), ('mixed_eligibility', 2, False), ('low_demand', 2, True)]:
        s = scenario()
        s.update(max_ground_delay_min=2, max_speed_delay_min=2,
                 entry_capacity_15min=[1]*8, tail_capacity_15min=1, occupancy_limit=2)
        s['flights'] = s['flights'][:count]
        for i, f in enumerate(s['flights']):
            eta = 15*i if low_demand else 1+2*i
            eligible = i == 0
            takeoff = -10 if eligible else -70
            f.update(eta_min=eta, dwell_min=4, ground_eligible=eligible,
                     reference_takeoff_min=takeoff, travel_to_entry_min=eta-takeoff)
        core.validate(s)
        for mode in ('ground', 'mixed'):
            exact_plan, optimum, combinations = exact_optimize(s, mode)
            for seed in seeds:
                plan, _, count_evaluations = optimize(s, mode, seed, 12, 20)
                metrics, rows = evaluate(s, plan)
                audit(s, plan, rows)
                gap = metrics['objective']-optimum
                if gap < -1e-7:
                    raise ValueError('GA objective fell below the enumerated integer-grid optimum')
                cases.append(dict(case=name, mode=mode, seed=seed, exact_objective=optimum,
                                  ga_objective=metrics['objective'], absolute_gap=max(0, gap),
                                  relative_gap_pct=100*gap/optimum if optimum else None,
                                  exact_evaluations=combinations, ga_evaluations=count_evaluations,
                                  exact_plan=exact_plan, ga_plan=plan))
    return cases


def metric_rows(result):
    """Flatten KPIs and inclusive search costs for CLI and HTTP exports."""
    rows = []
    for name, run in result['runs'].items():
        search = run.get('search', {})
        rows.append(dict(method=name, **run['metrics'],
                         search_evaluations=search.get('search_evaluations', run.get('evaluations')),
                         simulation_evaluations=search.get('simulation_evaluations'),
                         preparation_evaluations=search.get('preparation_evaluations'),
                         total_evaluations=search.get('total_evaluations'),
                         total_budget=search.get('total_budget'),
                         search_elapsed_s=search.get('search_elapsed_s'),
                         total_elapsed_s=search.get('total_elapsed_s'),
                         stop_reason=search.get('stop_reason')))
    return rows


def experiment(seeds=(11,22,33,44,55),population=60,generations=100,*,max_evaluations=None):
    start=time.perf_counter();s=scenario();core.validate(s);runs={}
    seeds = tuple(seeds)
    phase_budget = population+(population-2)*generations
    budget = 2*phase_budget if max_evaluations is None else max_evaluations
    if type(budget) is not int or budget < 1:
        raise ValueError('Evaluation budget must be a positive integer')
    seed_budget = max(1, budget//2)
    def record(name,plan,history=None,evaluations=0,search=None):
        metrics,rows=evaluate(s,plan);audit(s,plan,rows)
        runs[name]=dict(metrics=metrics,plan=plan,flights=rows,history=history or [],evaluations=evaluations,
                       search=search or {})
    record('BASELINE',[0]*(2*len(s['flights'])))
    record('FCFS_GROUND',heuristic(s));record('FCFS_MIXED',heuristic(s,True))
    for seed in seeds:
        ground_stats = {}
        ground, history, ground_count = optimize(s, 'ground', seed, population, generations,
                                                max_evaluations=seed_budget, diagnostics=ground_stats)
        ground_stats.update(preparation_evaluations=0, total_evaluations=ground_count,
                            total_elapsed_s=ground_stats['search_elapsed_s'], total_budget=seed_budget)
        record(f'GA_GROUND_{seed}', ground, history, ground_count, ground_stats)
        # Reuse the same seed's incumbent and debit ALL of its search cost.
        # If ground used the full allowance, mixed simply retains that plan.
        remaining = budget-ground_count
        for mode, label in [('ground', 'GA_CONTINUED_GROUND'), ('mixed', 'GA_MIXED')]:
            search_stats = {}
            if remaining:
                plan, history, count = optimize(s, mode, seed+1000, population, generations,
                    incumbent=ground, max_evaluations=remaining, diagnostics=search_stats)
            else:
                plan, count = ground[:], 0
                objective = runs[f'GA_GROUND_{seed}']['metrics']['objective']
                history = [dict(generation=0, objective=objective, evaluations=0)]
                search_stats.update(search_evaluations=0, max_evaluations=0, search_elapsed_s=0,
                                    stop_reason='incumbent_used_budget', generations_completed=0,
                                    incumbent_objective=objective)
            search_stats.update(preparation_evaluations=ground_count,
                                total_evaluations=ground_count+count,
                                total_elapsed_s=ground_stats['search_elapsed_s']+search_stats['search_elapsed_s'],
                                total_budget=budget, incumbent_method=f'GA_GROUND_{seed}',
                                refinement_seed=seed+1000)
            record(f'{label}_{seed}', plan, history, count, search_stats)
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
        exact_checks=small_case_benchmark(),
        settings=dict(seeds=list(seeds),population=population,generations=generations,
                      max_evaluations=budget, incumbent_max_evaluations=seed_budget,
                      matched_methods=['GA_CONTINUED_GROUND', 'GA_MIXED'],
                      budget_basis='unique fitness evaluations, including heuristic preparation and ground incumbent search',
                      optimizer_version='paired-mutation-incumbent-v1'),elapsed_s=time.perf_counter()-start,
        limitations=['Synthetic arrival-entry flow model; no validated VVTS capacity or 4D separation.',
        'Speed absorption over a hypothetical upstream 100 NM segment: 300 to 250 kt ground speed, no wind/fuel model.',
        'Replay is visualization of optimized event times, not independent kinematic validation.',
        'Frozen-plan ETA stress and weight re-scoring only; not robust optimization.',
        'Exact checks cover small integer-minute grids using the same flow evaluator, not independent trajectory validation.'])
