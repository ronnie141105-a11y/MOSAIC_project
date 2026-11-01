"""Reproducible uncertainty ensembles, held-out evaluation and rollout budgets."""
from copy import deepcopy
import math

import pytest

from astra.optimization import atfm, uncertainty


def tiny_scenario(count=3):
    """Small synthetic case with both editable and already airborne flights."""
    flights = []
    for i in range(count):
        eligible = i != 1
        takeoff = -10 if eligible else -70
        eta = 1 + i
        flights.append(dict(id=f'TEST{i}', gate='G_N', aircraft_type='A320',
                            eta_min=eta, dwell_min=4, ground_eligible=eligible,
                            reference_takeoff_min=takeoff,
                            travel_to_entry_min=eta-takeoff))
    return dict(name='UNCERTAINTY_TEST', synthetic=True, decision_min=-60,
                note='Test assumptions only', demand_counts_15min=[count],
                entry_capacity_15min=[1, 2, 2], tail_capacity_15min=2,
                occupancy_limit=2, max_ground_delay_min=2,
                max_speed_delay_min=2, upstream_segment_min=20,
                nominal_ground_speed_kt=300,
                weights=dict(ground=1, speed=2, airborne=4, max_delay=.2),
                flights=flights)


def patch_experiment(monkeypatch):
    original = tiny_scenario()
    monkeypatch.setattr(uncertainty.atfm, 'scenario', lambda: deepcopy(original))
    monkeypatch.setattr(uncertainty.atfm, 'small_case_benchmark', lambda: [])
    return original


def quick_experiment(**kwargs):
    options = dict(seeds=(11,), population=8, generations=4,
                   max_evaluations=80, training_seeds=(201, 202),
                   test_seeds=(1001, 1002), eta_jitter_min=2,
                   capacity_drop=1, risk_weight=.25)
    options.update(kwargs)
    return uncertainty.uncertainty_experiment(**options)


def test_realizations_reproducible_and_caller_owned_data_unchanged():
    s = tiny_scenario()
    before = deepcopy(s)
    realizations = uncertainty.make_realizations(s, (11, 22), include_nominal=True)
    repeated = uncertainty.make_realizations(s, (11, 22), include_nominal=True)
    assert realizations == repeated
    assert s == before
    assert [r['realization_seed'] for r in realizations] == [None, 11, 22]
    assert realizations[0]['flights'] == s['flights']
    realizations[0]['flights'][0]['eta_min'] = 999
    realizations[1]['weights']['ground'] = 99
    assert s == before
    assert repeated[0]['flights'][0]['eta_min'] != 999
    assert realizations[2]['weights']['ground'] == s['weights']['ground']


def test_eta_travel_time_and_flight_identity_are_preserved_together():
    s = tiny_scenario()
    for realization in uncertainty.make_realizations(s, (11, 22, 33)):
        assert [f['id'] for f in realization['flights']] == [f['id'] for f in s['flights']]
        atfm.core.validate(realization)
        for original, perturbed in zip(s['flights'], realization['flights']):
            jitter = perturbed['eta_min']-original['eta_min']
            assert -2 <= jitter <= 2
            assert perturbed['travel_to_entry_min']-original['travel_to_entry_min'] == pytest.approx(jitter)
            for field in ('id', 'ground_eligible', 'reference_takeoff_min'):
                assert perturbed[field] == original[field]


def test_capacity_drop_is_bounded_and_includes_tail():
    s = tiny_scenario()
    r = uncertainty.make_realizations(s, (11,), eta_jitter_min=0,
                                     capacity_drop=8, capacity_drop_probability=1)[0]
    assert r['entry_capacity_15min'] == [1, 1, 1]
    assert r['tail_capacity_15min'] == 1
    assert s['entry_capacity_15min'] == [1, 2, 2]
    unchanged = uncertainty.make_realizations(s, (11,), eta_jitter_min=0,
        capacity_drop=8, capacity_drop_probability=0)[0]
    assert unchanged['entry_capacity_15min'] == s['entry_capacity_15min']
    assert unchanged['tail_capacity_15min'] == s['tail_capacity_15min']


@pytest.mark.parametrize('options', [
    dict(eta_jitter_min=-1), dict(eta_jitter_min=math.nan),
    dict(eta_jitter_min=True), dict(capacity_drop=-1),
    dict(capacity_drop=1.5), dict(capacity_drop=True),
    dict(capacity_drop_probability=-.01), dict(capacity_drop_probability=1.01),
    dict(capacity_drop_probability=math.nan),
])
def test_invalid_realization_config_rejected(options):
    with pytest.raises(ValueError):
        uncertainty.make_realizations(tiny_scenario(), (11,), **options)


def test_duplicate_realization_seeds_rejected():
    with pytest.raises(ValueError):
        uncertainty.make_realizations(tiny_scenario(), (11, 11))


def test_risk_aggregation_matches_hand_calculated_two_capacity_cases():
    low_capacity = tiny_scenario(count=1)
    high_capacity = deepcopy(low_capacity)
    low_capacity['realization_seed'] = 11
    high_capacity['realization_seed'] = 22
    high_capacity['entry_capacity_15min'][0] = 2
    summary = uncertainty.summarize_realizations([low_capacity, high_capacity],
                                                [2, 2], risk_weight=.25)
    # ETA=1, request=5; first usable slots 15 and 7.5. Ground=2, speed=2.
    # Cost = ground + 2*speed + 4*holding + .2*total arrival delay.
    assert summary['count'] == 2
    assert summary['mean_objective'] == pytest.approx((48.8+17.3)/2)
    assert summary['worst_objective'] == pytest.approx(48.8)
    assert summary['risk_objective'] == pytest.approx(.75*((48.8+17.3)/2)+.25*48.8)
    assert summary['mean_total_delay_min'] == pytest.approx((14+6.5)/2)
    assert summary['mean_airborne_holding_min'] == pytest.approx((10+2.5)/2)
    assert summary['mean_airborne_extra_min'] == pytest.approx((12+4.5)/2)


@pytest.mark.parametrize('weight', [0, .25, 1])
def test_risk_objective_endpoints_and_interpolation(weight):
    s = tiny_scenario(count=1)
    variations = uncertainty.make_realizations(s, (11, 22), include_nominal=True)
    summary = uncertainty.summarize_realizations(variations, [0, 0], risk_weight=weight)
    expected = (1-weight)*summary['mean_objective']+weight*summary['worst_objective']
    assert summary['risk_objective'] == pytest.approx(expected)


@pytest.mark.parametrize('weight', [-.01, 1.01, math.nan, True])
def test_invalid_risk_weight_rejected(weight):
    with pytest.raises(ValueError):
        uncertainty.summarize_realizations([tiny_scenario(count=1)], [0, 0], risk_weight=weight)


def test_empty_summary_rejected():
    with pytest.raises(ValueError):
        uncertainty.summarize_realizations([], [])


def test_every_realization_is_audited_and_fixed_flights_remain_eligible(monkeypatch):
    s = tiny_scenario()
    realizations = uncertainty.make_realizations(s, (11, 22, 33), include_nominal=True)
    actual_audit = atfm.audit
    audited = []
    def observed(realization, plan, rows):
        audited.append(realization['realization_seed'])
        assert all(r['ground_delay_min'] == 0 for r in rows if not r['ground_eligible'])
        return actual_audit(realization, plan, rows)
    monkeypatch.setattr(atfm, 'audit', observed)
    summary = uncertainty.summarize_realizations(realizations, [2, 0, 2, 1, 1, 1])
    assert summary['count'] == 4
    assert audited == [None, 11, 22, 33]
    with pytest.raises(ValueError, match='ground delay'):
        uncertainty.summarize_realizations(realizations, [2, 1, 2, 1, 1, 1])


def test_realization_audit_rejects_invalid_simulator_rows(monkeypatch):
    s = tiny_scenario(count=1)
    actual = atfm.evaluate
    def broken(realization, plan):
        metrics, rows = actual(realization, plan)
        rows[0]['id'] = 'MISSING_FLIGHT'
        return metrics, rows
    monkeypatch.setattr(atfm, 'evaluate', broken)
    with pytest.raises(ValueError, match='conservation'):
        uncertainty.summarize_realizations([s], [0, 0])


@pytest.mark.parametrize('budget', [3, 4, 9, 14])
def test_optimizer_charges_rollouts_and_incumbent_to_budget(budget):
    s = tiny_scenario(count=1)
    calls = []
    def ensemble_fitness(plan):
        calls.append(tuple(plan))
        metrics, rows = atfm.evaluate(s, plan)
        return metrics['objective'], rows
    stats = {}
    plan, history, count = atfm.optimize(s, seed=11, population=8, generations=10,
        incumbent=[2, 0], fitness=ensemble_fitness, evaluation_cost=3,
        max_evaluations=budget, diagnostics=stats)
    assert calls[0] == (2, 0)
    assert len(calls) == count == stats['search_evaluations']
    assert stats['simulation_evaluations'] == count*3 <= budget
    assert history[-1]['evaluations'] == count*3
    assert all(h['evaluations'] % 3 == 0 and h['evaluations'] <= budget for h in history)
    assert atfm.evaluate(s, plan)[0]['objective'] <= atfm.evaluate(s, [2, 0])[0]['objective']
    if budget < 6:
        assert plan == [2, 0] and count == 1


@pytest.mark.parametrize('cost,budget', [(0, 20), (-1, 20), (1.5, 20), (True, 20), (3, 2)])
def test_invalid_rollout_cost_or_too_small_budget_rejected(cost, budget):
    with pytest.raises(ValueError):
        atfm.optimize(tiny_scenario(), population=8, generations=2,
                      evaluation_cost=cost, max_evaluations=budget)


def test_custom_fitness_controls_selection_and_history():
    s = tiny_scenario(count=1)
    def fitness(plan):
        _, rows = atfm.evaluate(s, plan)
        return sum(plan), rows
    plan, history, _ = atfm.optimize(s, population=8, generations=4,
        incumbent=[2, 2], fitness=fitness, max_evaluations=40)
    assert plan == [0, 0]
    assert history[-1]['objective'] == 0
    assert atfm.evaluate(s, plan)[0]['objective'] > 0


@pytest.mark.parametrize('value', [math.nan, math.inf, -math.inf, 'invalid'])
def test_invalid_custom_fitness_score_rejected(value):
    s = tiny_scenario(count=1)
    def fitness(plan):
        return value, atfm.evaluate(s, plan)[1]
    with pytest.raises(ValueError, match='finite score'):
        atfm.optimize(s, fitness=fitness, population=8, generations=4)


def test_held_out_realizations_are_never_used_by_optimizer(monkeypatch):
    patch_experiment(monkeypatch)
    actual_optimize, actual_evaluate = atfm.optimize, atfm.evaluate
    active = [False]
    seen = []
    def observed_evaluate(s, plan):
        if active[0]:
            seen.append(s.get('realization_seed'))
        return actual_evaluate(s, plan)
    def observed_optimize(*args, **kwargs):
        active[0] = True
        try:
            return actual_optimize(*args, **kwargs)
        finally:
            active[0] = False
    monkeypatch.setattr(atfm, 'evaluate', observed_evaluate)
    monkeypatch.setattr(atfm, 'optimize', observed_optimize)
    quick_experiment()
    assert 201 in seen and 202 in seen and None in seen
    assert not ({1001, 1002} & set(seen))


def test_changing_only_test_ensemble_does_not_change_selected_plans(monkeypatch):
    patch_experiment(monkeypatch)
    first = quick_experiment(test_seeds=(1001,))
    second = quick_experiment(test_seeds=(1002, 1003))
    assert {name: r['plan'] for name, r in first['runs'].items()} == {
        name: r['plan'] for name, r in second['runs'].items()}
    training = lambda result: [r for r in result['uncertainty_summary'] if r['split'] == 'training']
    assert training(first) == training(second)
    assert all(r['count'] == 1 for r in first['uncertainty_summary'] if r['split'] == 'test')
    assert all(r['count'] == 2 for r in second['uncertainty_summary'] if r['split'] == 'test')


@pytest.mark.parametrize('options', [
    dict(training_seeds=(201,), test_seeds=(201,)),
    dict(training_seeds=()), dict(test_seeds=()),
    dict(training_seeds=(201, 201)), dict(test_seeds=(1001, 1001)),
    dict(max_evaluations=3), dict(risk_weight=math.nan),
])
def test_invalid_experiment_config_rejected_before_search(monkeypatch, options):
    patch_experiment(monkeypatch)
    def unexpected(*args, **kwargs):
        pytest.fail('Search started before invalid experiment configuration was rejected')
    monkeypatch.setattr(atfm, 'optimize', unexpected)
    with pytest.raises(ValueError):
        quick_experiment(**options)


def test_matched_refinements_share_incumbent_and_inclusive_budget(monkeypatch):
    patch_experiment(monkeypatch)
    actual = atfm.optimize
    refinements = []
    def observed(*args, **kwargs):
        if kwargs.get('incumbent') is not None:
            refinements.append(deepcopy(kwargs['incumbent']))
        return actual(*args, **kwargs)
    monkeypatch.setattr(atfm, 'optimize', observed)
    result = quick_experiment()
    assert len(refinements) == 2
    assert refinements[0] == refinements[1]
    assert refinements[0][3:] == [0, 0, 0]
    deterministic = result['runs']['GA_DETERMINISTIC_11']
    robust = result['runs']['GA_UNCERTAINTY_11']
    for run, multiplier in ((deterministic, 1), (robust, 3)):
        search = run['search']
        assert search['simulation_evaluations'] == search['search_evaluations']*multiplier
        assert search['total_evaluations'] == search['preparation_evaluations']+search['simulation_evaluations'] <= 80
        assert search['total_budget'] == 80
        assert run['history'][-1]['evaluations'] == search['simulation_evaluations']
    assert deterministic['search']['preparation_evaluations'] == robust['search']['preparation_evaluations']
    exported = {r['method']: r for r in atfm.metric_rows(result)}
    assert exported['GA_UNCERTAINTY_11']['total_evaluations'] == robust['search']['total_evaluations']


def test_experiment_diagnostics_match_actual_selection_simulations(monkeypatch):
    patch_experiment(monkeypatch)
    actual_optimize, actual_evaluate = atfm.optimize, atfm.evaluate
    calls = []
    active = [None]
    def observed_evaluate(s, plan):
        if active[0] is not None:
            calls[active[0]] += 1
        return actual_evaluate(s, plan)
    def observed_optimize(*args, **kwargs):
        active[0] = len(calls)
        calls.append(0)
        try:
            return actual_optimize(*args, **kwargs)
        finally:
            active[0] = None
    monkeypatch.setattr(atfm, 'evaluate', observed_evaluate)
    monkeypatch.setattr(atfm, 'optimize', observed_optimize)
    result = quick_experiment()
    assert len(calls) == 3  # Warm ground search, deterministic and uncertainty refinements.
    for method, observed in [('GA_DETERMINISTIC_11', calls[1]), ('GA_UNCERTAINTY_11', calls[2])]:
        search = result['runs'][method]['search']
        assert search['simulation_evaluations'] == observed
        assert search['preparation_evaluations'] == calls[0]
        assert search['total_evaluations'] == calls[0]+observed <= 80


def test_replay_rows_and_metrics_remain_nominal(monkeypatch):
    original = patch_experiment(monkeypatch)
    result = quick_experiment()
    assert result['scenario'] == original
    for run in result['runs'].values():
        metrics, rows = atfm.evaluate(original, run['plan'])
        assert run['metrics'] == metrics
        assert run['flights'] == rows
        assert atfm.audit(original, run['plan'], run['flights'])
    summaries = result['uncertainty_summary']
    assert {r['method'] for r in summaries} == set(result['runs'])
    assert all(r['count'] == 3 for r in summaries if r['split'] == 'training')
    assert all(r['count'] == 2 for r in summaries if r['split'] == 'test')
