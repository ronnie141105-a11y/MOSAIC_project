"""Finite-scenario ETA/capacity optimization for the synthetic ATFM queue.

Training scenarios select plans; disjoint test scenarios only evaluate frozen
plans. These assumed distributions are not calibrated VVTS uncertainty models.
"""
from copy import deepcopy
import math
import random
import statistics
import time

from . import atfm


def _number(value, name, minimum=0, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be finite')
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f'{name} is outside its valid range')
    return value


def _seeds(values, name):
    try:
        values = tuple(values)
    except TypeError as exc:
        raise ValueError(f'{name} must be an iterable of integer seeds') from exc
    if not values or any(type(v) is not int for v in values) or len(set(values)) != len(values):
        raise ValueError(f'{name} must contain unique integer seeds and cannot be empty')
    return values


def _validate_scenario(s):
    """Reject invalid/infinite service resources before queue simulation."""
    for value in (*s['entry_capacity_15min'], s['tail_capacity_15min'], s['occupancy_limit']):
        if type(value) is not int or value < 1:
            raise ValueError('Capacities and occupancy must be positive integers')
    if not s['entry_capacity_15min']:
        raise ValueError('At least one capacity window is required')
    _number(s['decision_min'], 'Decision time', minimum=-float('inf'))
    _number(s['upstream_segment_min'], 'Upstream segment', minimum=1e-12)
    _number(s['nominal_ground_speed_kt'], 'Nominal speed', minimum=1e-12)
    _number(s['max_ground_delay_min'], 'Ground delay limit')
    _number(s['max_speed_delay_min'], 'Speed delay limit')
    for name in ('ground', 'speed', 'airborne', 'max_delay'):
        _number(s['weights'][name], f'{name} weight')
    if type(s['synthetic']) is not bool:
        raise ValueError('Synthetic flag must be boolean')
    ids = [flight['id'] for flight in s['flights']]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Flight IDs must be unique nonempty strings')
    for flight in s['flights']:
        for name in ('eta_min', 'reference_takeoff_min'):
            _number(flight[name], name, minimum=-float('inf'))
        _number(flight['travel_to_entry_min'], 'Travel time', minimum=1e-12)
        _number(flight['dwell_min'], 'Dwell time', minimum=1e-12)
        if type(flight['ground_eligible']) is not bool:
            raise ValueError('Ground eligibility must be boolean')
        if not math.isclose(flight['reference_takeoff_min']+flight['travel_to_entry_min'],
                            flight['eta_min'], rel_tol=0, abs_tol=1e-6):
            raise ValueError('ETA does not match departure and travel time')
        eligible = flight['reference_takeoff_min'] >= s['decision_min']
        if flight['ground_eligible'] != eligible:
            raise ValueError('Ground eligibility is inconsistent with decision time')
        if flight['eta_min']-s['upstream_segment_min'] < s['decision_min']:
            raise ValueError('Upstream segment starts before the decision time')


def make_realizations(s, seeds, *, eta_jitter_min=2, capacity_drop=1,
                      capacity_drop_probability=.25, include_nominal=False):
    """Sample travel-time jitter and independently reduced capacity windows.

    Departure/readiness times and ground eligibility remain fixed. Tail
    capacity is sampled too and stays positive, so all demand is completed.
    Reject unsafe jitter ranges rather than silently truncating the samples.
    """
    seeds = _seeds(seeds, 'Realization seeds')
    _number(eta_jitter_min, 'ETA jitter')
    if type(capacity_drop) is not int or capacity_drop < 0:
        raise ValueError('Capacity drop must be a nonnegative integer')
    _number(capacity_drop_probability, 'Capacity drop probability', maximum=1)
    if type(include_nominal) is not bool:
        raise ValueError('include_nominal must be boolean')
    _validate_scenario(s)
    for flight in s['flights']:
        margin = flight['eta_min']-s['upstream_segment_min']-s['decision_min']
        if flight['travel_to_entry_min'] <= eta_jitter_min or margin < eta_jitter_min:
            raise ValueError('ETA jitter can make travel or the speed segment infeasible')
    scenarios = []
    if include_nominal:
        nominal = deepcopy(s)
        nominal['realization_seed'] = None
        nominal['eta_offsets_min'] = {f['id']: 0 for f in s['flights']}
        scenarios.append(nominal)
    for seed in seeds:
        rng = random.Random(seed)
        realized = deepcopy(s)
        realized['realization_seed'] = seed
        offsets = {}
        for flight in realized['flights']:
            jitter = rng.uniform(-eta_jitter_min, eta_jitter_min)
            flight['eta_min'] += jitter
            flight['travel_to_entry_min'] += jitter
            offsets[flight['id']] = jitter
        realized['eta_offsets_min'] = offsets
        realized['entry_capacity_15min'] = [
            max(1, c-capacity_drop) if rng.random() < capacity_drop_probability else c
            for c in s['entry_capacity_15min']]
        realized['tail_capacity_15min'] = (
            max(1, s['tail_capacity_15min']-capacity_drop)
            if rng.random() < capacity_drop_probability else s['tail_capacity_15min'])
        _validate_scenario(realized)
        scenarios.append(realized)
    return scenarios


def _summarize(metrics, risk_weight):
    _number(risk_weight, 'Risk weight', maximum=1)
    if not metrics:
        raise ValueError('At least one realization is required')
    mean = statistics.mean(m['objective'] for m in metrics)
    worst = max(m['objective'] for m in metrics)
    return dict(count=len(metrics), mean_objective=mean, worst_objective=worst,
                risk_objective=(1-risk_weight)*mean+risk_weight*worst,
                mean_total_delay_min=statistics.mean(m['total_delay_min'] for m in metrics),
                mean_airborne_holding_min=statistics.mean(m['airborne_holding_min'] for m in metrics),
                mean_airborne_extra_min=statistics.mean(m['airborne_extra_min'] for m in metrics))


def _evaluate_samples(realizations, plan, risk_weight):
    if not realizations:
        raise ValueError('At least one realization is required')
    metrics, nominal_rows = [], None
    for i, realized in enumerate(realizations):
        value, rows = atfm.evaluate(realized, plan)
        atfm.audit(realized, plan, rows)
        metrics.append(value)
        if i == 0:
            nominal_rows = rows
    return _summarize(metrics, risk_weight), metrics, nominal_rows


def summarize_realizations(realizations, plan, risk_weight=.25):
    """Audit a frozen plan on every realization, then aggregate costs."""
    _number(risk_weight, 'Risk weight', maximum=1)
    return _evaluate_samples(realizations, plan, risk_weight)[0]


def uncertainty_experiment(seeds=(11,22,33,44,55), population=40, generations=60,
                           max_evaluations=6000, risk_weight=.25,
                           eta_jitter_min=2, capacity_drop=1,
                           training_seeds=(201,202,203,204),
                           test_seeds=tuple(range(1001,1013)),
                           capacity_drop_probability=.25):
    """Matched rollout budgets and paired, unseen evaluation of frozen plans."""
    started = time.perf_counter()
    seeds = _seeds(seeds, 'GA seeds')
    training_seeds = _seeds(training_seeds, 'Training seeds')
    test_seeds = _seeds(test_seeds, 'Test seeds')
    if set(training_seeds) & set(test_seeds):
        raise ValueError('Training and test seeds must be disjoint')
    _number(risk_weight, 'Risk weight', maximum=1)
    if type(population) is not int or not 4 <= population <= 100:
        raise ValueError('Population must be 4 to 100')
    if type(generations) is not int or not 0 <= generations <= 200:
        raise ValueError('Generations must be 0 to 200')
    training_count = len(training_seeds)+1
    if type(max_evaluations) is not int or max_evaluations < training_count+1:
        raise ValueError('Budget must cover one incumbent and one training ensemble')
    s = atfm.scenario()
    parameters = dict(eta_jitter_min=eta_jitter_min, capacity_drop=capacity_drop,
                      capacity_drop_probability=capacity_drop_probability)
    training = make_realizations(s, training_seeds, include_nominal=True, **parameters)
    test = make_realizations(s, test_seeds, **parameters)
    seed_budget = min(max(1, max_evaluations//5), max_evaluations-training_count)
    nominal_generations = min(200, generations*training_count)
    runs, incumbents = {}, {}

    def record(name, plan, history=None, evaluations=0, search=None):
        # Replay and this KPI table always use the nominal scenario.
        metrics, rows = atfm.evaluate(s, plan)
        atfm.audit(s, plan, rows)
        runs[name] = dict(metrics=metrics, plan=plan, flights=rows,
                          history=history or [], evaluations=evaluations,
                          search=search or {}, replay_context='nominal')

    record('BASELINE', [0]*(2*len(s['flights'])))
    record('FCFS_GROUND', atfm.heuristic(s))
    record('FCFS_MIXED', atfm.heuristic(s, True))

    def training_fitness(plan):
        summary, _, nominal_rows = _evaluate_samples(training, plan, risk_weight)
        return summary['risk_objective'], nominal_rows

    # Selection uses nominal/training inputs only. The test ensemble is never
    # supplied to this loop, its fitness callbacks or incumbent construction.
    for seed in seeds:
        seed_stats = {}
        incumbent, _, preparation_count = atfm.optimize(
            s, 'ground', seed, population, generations,
            max_evaluations=seed_budget, diagnostics=seed_stats)
        incumbents[str(seed)] = dict(plan=incumbent, search=seed_stats)
        remaining = max_evaluations-preparation_count
        for label, fitness, cost, limit in (
            ('GA_DETERMINISTIC', None, 1, nominal_generations),
            ('GA_UNCERTAINTY', training_fitness, training_count, generations)):
            search = {}
            plan, history, count = atfm.optimize(
                s, 'mixed', seed+1000, population, limit,
                incumbent=incumbent, max_evaluations=remaining, diagnostics=search,
                fitness=fitness, evaluation_cost=cost)
            search.update(preparation_evaluations=preparation_count,
                          total_evaluations=preparation_count+search['simulation_evaluations'],
                          total_elapsed_s=seed_stats['search_elapsed_s']+search['search_elapsed_s'],
                          total_budget=max_evaluations,
                          objective_context='training_risk' if fitness else 'nominal',
                          incumbent_seed=seed, refinement_seed=seed+1000)
            record(f'{label}_{seed}', plan, history, count, search)

    summaries, held_out = [], []
    for name, run in runs.items():
        for split, realizations in (('training', training), ('test', test)):
            summary, sample_metrics, _ = _evaluate_samples(realizations, run['plan'], risk_weight)
            summaries.append(dict(method=name, split=split, **summary))
            if split == 'test':
                held_out.extend(dict(method=name, noise_seed=realized['realization_seed'],
                                     split='test', **metrics)
                                for realized, metrics in zip(realizations, sample_metrics))
    return dict(
        scenario=s, runs=runs, stress=held_out, sensitivity=[], exact_checks=[],
        uncertainty_summary=summaries, incumbents=incumbents,
        uncertainty=dict(risk_weight=risk_weight, **parameters,
                         training_seeds=list(training_seeds), test_seeds=list(test_seeds),
                         training_count=len(training), test_count=len(test),
                         training_realizations=training, test_realizations=test),
        settings=dict(seeds=list(seeds), population=population, generations=generations,
                      max_evaluations=max_evaluations, incumbent_max_evaluations=seed_budget,
                      nominal_refinement_generations=nominal_generations,
                      uncertainty_refinement_generations=generations,
                      mode='uncertainty', optimizer_version='finite-ensemble-v1',
                      budget_basis='underlying scenario simulations including nominal incumbent preparation',
                      reporting_simulations=len(runs)*(1+len(training)+len(test)),
                      baseline_preparation_simulations=3,
                      selection_simulations=sum(i['search']['simulation_evaluations'] for i in incumbents.values())
                          +sum(r['search'].get('simulation_evaluations', 0) for r in runs.values()),
                      test_selection=False),
        elapsed_s=time.perf_counter()-started,
        limitations=[
            'Synthetic arrival-entry flow model, not validated VVTS capacity or 4D separation.',
            'Independent uniform ETA jitter and capacity drops are study assumptions, not calibrated forecast distributions.',
            'Worst means worst of the finite sampled ensemble, not a guarantee for all possible conditions.',
            'The same test realizations are paired across methods and GA seeds; they are not independent new samples per method.',
            'Nominal replay illustrates optimized event times and does not validate dynamics.',
            'Reported held-out results never select plans; nominal cost can increase when training risk is minimized.'])
