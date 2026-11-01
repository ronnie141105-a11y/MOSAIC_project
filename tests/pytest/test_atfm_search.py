"""Search quality, inclusive budgets and exact small-instance checks."""
import math

import pytest

from astra.optimization import atfm


def tiny_scenario(eligible=True):
    s = atfm.scenario()
    s.update(max_ground_delay_min=2, max_speed_delay_min=2,
             entry_capacity_15min=[1]*8, tail_capacity_15min=1, occupancy_limit=1)
    s['flights'] = s['flights'][:1]
    s['flights'][0].update(eta_min=1, dwell_min=4, ground_eligible=eligible,
                          reference_takeoff_min=-10 if eligible else -70,
                          travel_to_entry_min=11 if eligible else 71)
    return s


def test_exact_single_slot_matches_hand_calculated_cost():
    # First usable slot is minute 15, so total arrival delay is always 14.
    # Ground 2 + speed 2 + holding 10: J = 2 + 4 + 40 + .2*14.
    plan, optimum, count = atfm.exact_optimize(tiny_scenario())
    assert plan == [2, 2]
    assert optimum == pytest.approx(48.8)
    assert count == 9
    plan, optimum, count = atfm.exact_optimize(tiny_scenario(), 'ground')
    assert plan == [2, 0]
    assert optimum == pytest.approx(52.8)
    assert count == 3


def test_exact_airborne_flight_cannot_receive_ground_delay():
    plan, optimum, count = atfm.exact_optimize(tiny_scenario(False))
    assert plan == [0, 2]
    assert optimum == pytest.approx(54.8)
    assert count == 3


def test_enumeration_refuses_large_grid_before_evaluating(monkeypatch):
    def unexpected(*args):
        pytest.fail('Large exact search started evaluating')
    monkeypatch.setattr(atfm, 'evaluate', unexpected)
    with pytest.raises(ValueError, match='combinations'):
        atfm.exact_optimize(atfm.scenario())


@pytest.mark.parametrize('mode', ['ground', 'mixed'])
def test_ga_reaches_known_small_optimum(mode):
    s = tiny_scenario()
    _, optimum, _ = atfm.exact_optimize(s, mode)
    for seed in (11, 22, 33):
        plan, history, _ = atfm.optimize(s, mode, seed, 12, 20)
        metrics, rows = atfm.evaluate(s, plan)
        assert atfm.audit(s, plan, rows)
        assert metrics['objective'] == pytest.approx(optimum)
        assert all(b['objective'] <= a['objective'] for a, b in zip(history, history[1:]))


def test_transfer_preserves_request_and_entry_times_but_changes_cost():
    s = tiny_scenario()
    original = [0, 2]
    shifted = atfm.transfer_delay(s, original, 0, -2)
    before, rows_before = atfm.evaluate(s, original)
    after, rows_after = atfm.evaluate(s, shifted)
    assert original == [0, 2]  # Caller-owned plan is not mutated.
    assert shifted == [2, 0]
    for key in ('request_min', 'entry_min', 'exit_min', 'total_delay_min', 'airborne_delay_min'):
        assert rows_before[0][key] == rows_after[0][key]
    assert before['objective']-after['objective'] == pytest.approx(2)


@pytest.mark.parametrize('eligible,plan,amount', [
    (False, [0, 1], -1), (True, [2, 0], -1),
    (True, [0, 2], 1), (True, [1, 1], math.nan),
])
def test_invalid_transfer_rejected(eligible, plan, amount):
    with pytest.raises(ValueError):
        atfm.transfer_delay(tiny_scenario(eligible), plan, 0, amount)


@pytest.mark.parametrize('budget', [1, 2, 3, 9])
def test_fitness_budget_includes_bootstrap_evaluations(monkeypatch, budget):
    s = tiny_scenario()
    actual = atfm.evaluate
    calls = []
    def observed(scenario, plan):
        calls.append(tuple(plan))
        return actual(scenario, plan)
    monkeypatch.setattr(atfm, 'evaluate', observed)
    stats = {}
    plan, history, count = atfm.optimize(s, 'mixed', 11, 12, 20,
                                      max_evaluations=budget, diagnostics=stats)
    assert len(calls) == count == stats['search_evaluations'] <= budget
    assert actual(s, plan)[0]['objective'] == history[-1]['objective']


def test_incumbent_survives_one_evaluation_budget():
    s = tiny_scenario()
    ground, _, _ = atfm.optimize(s, 'ground', 11, 12, 20)
    mixed, _, count = atfm.optimize(s, 'mixed', 22, 12, 20,
                                   incumbent=ground, max_evaluations=1)
    assert mixed == ground and count == 1


def test_incumbent_shape_and_measure_set_are_validated():
    s = tiny_scenario()
    for plan in ([1], [3, 0], [0, math.nan]):
        with pytest.raises(ValueError):
            atfm.optimize(s, incumbent=plan)
    with pytest.raises(ValueError, match='measure set'):
        atfm.optimize(s, 'ground', incumbent=[0, 1])


@pytest.mark.parametrize('budget', [1, 4, 16, 64])
def test_experiment_debits_ground_preparation_and_retains_incumbent(monkeypatch, budget):
    s = tiny_scenario()
    monkeypatch.setattr(atfm, 'scenario', lambda: s)
    monkeypatch.setattr(atfm, 'small_case_benchmark', lambda: [])
    result = atfm.experiment(seeds=(11,), population=12, generations=8,
                             max_evaluations=budget)
    g, m = result['runs']['GA_GROUND_11'], result['runs']['GA_MIXED_11']
    continued = result['runs']['GA_CONTINUED_GROUND_11']
    assert m['metrics']['objective'] <= g['metrics']['objective']
    assert m['search']['preparation_evaluations'] == g['evaluations']
    assert m['search']['total_evaluations'] == g['evaluations']+m['evaluations'] <= budget
    assert m['search']['total_elapsed_s'] >= g['search']['total_elapsed_s']
    assert g['search']['total_evaluations'] <= budget
    assert continued['search']['total_budget'] == m['search']['total_budget'] == budget
    assert continued['search']['total_evaluations'] <= budget
    assert continued['metrics']['objective'] <= g['metrics']['objective']
    exported = {r['method']: r for r in atfm.metric_rows(result)}
    assert exported['GA_MIXED_11']['total_evaluations'] == m['search']['total_evaluations']


def test_small_case_benchmark_reports_zero_gaps():
    checks = atfm.small_case_benchmark()
    assert len(checks) == 18
    assert all(r['absolute_gap'] == 0 for r in checks)
    assert {r['case'] for r in checks} == {'single_slot', 'mixed_eligibility', 'low_demand'}


def test_legacy_exports_leave_unknown_inclusive_costs_blank():
    metrics, rows = atfm.evaluate(tiny_scenario(), [0, 0])
    exported = atfm.metric_rows({'runs': {'OLD': {'metrics': metrics, 'evaluations': 7}}})[0]
    assert exported['search_evaluations'] == 7
    assert exported['total_evaluations'] is None
    assert exported['total_elapsed_s'] is None
