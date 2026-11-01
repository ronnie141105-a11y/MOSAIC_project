from copy import deepcopy
import math

import pytest

from astra.optimization.formulation import Evaluator, exact_optimize, experiment, make_scenario, optimize
from astra.optimization.formulation_validation import frame, validate_runs


def small(etas=(10, 10.5), airborne=False):
    s = make_scenario('nominal')
    s['flights'] = s['flights'][1:len(etas)+1]
    for i, (f, eta) in enumerate(zip(s['flights'], etas)):
        departure = -70 if airborne and i == 1 else -30
        f.update(eta_min=eta, gate='G_N', reference_takeoff_min=departure,
                 travel_to_entry_min=eta-departure, ground_eligible=departure >= s['decision_min'])
    return s


def test_speed_percent_conversion_and_exclusive_actions():
    e = Evaluator(small())
    metrics, rows, _ = e.evaluate([[1, 15], [2, 10]])
    assert rows[0]['ground_delay_min'] == 15
    assert rows[0]['speed_delay_min'] == 0
    assert rows[1]['ground_delay_min'] == 0
    assert rows[1]['speed_delay_min'] == pytest.approx(20/.9-20)
    assert rows[1]['upstream_ground_speed_kt'] == 270
    assert metrics['converted_cost'] == pytest.approx(15+2*(20/.9-20))
    assert metrics['objective'] == pytest.approx(metrics['converted_cost']+1000*metrics['penalty'])
    assert metrics['fitness'] == pytest.approx(1/(1+metrics['objective']))
    assert metrics['total_delay_min'] == pytest.approx(15+20/.9-20)
    for r in rows:
        assert r['entry_min'] == r['request_min'] == r['eta_min']+r['total_delay_min']
        assert r['airborne_delay_min'] == 0


@pytest.mark.parametrize('plan', [[], [[1, 5], [1, 25]], [[0, 1], [0, 0]],
                                 [[2, 20], [0, 0]], [[True, 5], [0, 0]],
                                 [[1, 5, 2], [0, 0]], [[2, float('nan')], [0, 0]]])
def test_invalid_categorical_plans(plan):
    with pytest.raises(ValueError):
        Evaluator(small()).evaluate(plan)


def test_ground_readiness_and_technical_limits():
    s = small(airborne=True)
    s['flights'][0]['max_speed_reduction_pct'] = 5
    e = Evaluator(s)
    with pytest.raises(ValueError, match='unavailable'):
        e.evaluate([[0, 0], [1, 5]])
    with pytest.raises(ValueError, match='unavailable'):
        e.evaluate([[2, 10], [0, 0]])
    e.evaluate([[2, 5], [2, 15]])
    s['flights'][0]['upstream_segment_min'] = 100
    with pytest.raises(ValueError, match='unavailable'):
        Evaluator(s).evaluate([[2, 5], [0, 0]])


def test_capacity_half_open_bins_tail_and_no_implicit_queue():
    s = small((59.5, 60))
    s.update(capacity_interval_min=60, capacity_per_interval=[1], tail_capacity=1, hourly_capacity=42)
    e = Evaluator(s)
    m, rows, audit = e.evaluate([[0, 0], [0, 0]])
    assert m['capacity_excess_flights'] == 0
    assert [b['bin'] for b in audit['capacity_bins']] == [0, 1]
    m, rows, audit = e.evaluate([[1, 5], [0, 0]])
    assert m['capacity_excess_flights'] == 1
    assert not m['feasible_in_synthetic_tma']
    assert rows[0]['entry_min'] == 64.5
    s['penalty_power'] = 2
    assert Evaluator(s).evaluate([[1, 5], [0, 0]])[0]['capacity_penalty'] == 1


def test_user_confirmed_hourly_limit_and_penalty_double_counting():
    s = make_scenario('holiday_peak')
    e = Evaluator(s)
    m, _, _ = e.evaluate(e.decode([0]*e.n))
    assert m['hourly_excess_flights'] > 0
    assert m['capacity_penalty'] == m['hourly_excess_flights']
    s['penalty_power'] = 2
    squared = Evaluator(s).evaluate(e.decode([0]*e.n))[0]
    assert squared['capacity_penalty'] == m['hourly_excess_flights']**2
    diagnosis = e.domain_diagnostics()
    assert not diagnosis['proven_infeasible']
    assert diagnosis['hourly_bound']['excess_lower_bound'] == 0


def test_domain_capacity_certificate_does_not_depend_on_ga():
    e = Evaluator(make_scenario('existing'))
    diagnosis = e.domain_diagnostics()
    assert diagnosis['proven_infeasible']
    assert diagnosis['capacity_bound']['excess_lower_bound'] == 7
    assert diagnosis['capacity_bound']['forced_flights'] == 39
    assert diagnosis['capacity_bound']['capacity'] == 32


def test_continuous_separation_and_new_conflicts():
    e = Evaluator(small((10, 20)))
    m, _, _ = e.evaluate([[0, 0], [0, 0]])
    assert m['separation_conflict_pairs'] == 0
    m, _, audit = e.evaluate([[1, 10], [0, 0]])
    assert m['separation_conflict_pairs'] == m['new_conflict_pairs'] == 1
    assert m['penalty'] == 2
    assert audit['conflict_pairs'] == [['SYN002', 'SYN003']]
    # Distinct altitude profiles: no overlap in time implies no conflict.
    e = Evaluator(small((10, 40)))
    assert e.evaluate([[0, 0], [0, 0]])[0]['separation_conflict_pairs'] == 0


def test_occupancy_penalty_is_duration_weighted():
    s = small((10, 10))
    s['occupancy_limit'] = 1
    m, _, _ = Evaluator(s).evaluate([[0, 0], [0, 0]])
    assert m['peak_occupancy'] == 2
    assert m['occupancy_penalty'] == min(f['dwell_min'] for f in s['flights'])


@pytest.mark.parametrize('mode', ['ground', 'mixed'])
def test_ga_matches_small_exact_optimum_is_reproducible_and_budgeted(mode):
    e = Evaluator(small(airborne=True))
    exact, optimum, _ = exact_optimize(e, mode)
    p, history, search = optimize(e, mode, 11, 20, 60, 500)
    p2, history2, _ = optimize(e, mode, 11, 20, 60, 500)
    assert p == p2 and history == history2
    assert e.evaluate(p)[0]['objective'] == pytest.approx(optimum)
    assert search['total_evaluations'] <= 500
    assert all(b['objective'] <= a['objective'] for a, b in zip(history, history[1:]))
    if mode == 'ground':
        assert all(g[0] != 2 for g in p)
    with pytest.raises(ValueError):
        exact_optimize(Evaluator(make_scenario()), limit=100)


def test_incumbent_is_kept_even_with_one_evaluation():
    e = Evaluator(small())
    initial = [[1, 5], [0, 0]]
    p, h, stats = optimize(e, 'mixed', 11, 4, 10, 1, initial)
    assert p == initial
    assert stats['total_evaluations'] == 1
    assert h[-1]['objective'] == e.evaluate(initial)[0]['objective']


def test_feasible_zero_cost_stops_without_unnecessary_control():
    e = Evaluator(small((10, 40)))
    p, history, search = optimize(e, 'mixed', 11, 20, 60, 500)
    assert p == [[0, 0], [0, 0]]
    assert history[-1]['fitness'] == 1
    assert search['stop_reason'] == 'zero_cost_feasible'


def test_experiment_fair_paired_costs_and_statistics():
    s = small()
    original = deepcopy(s)
    result = experiment(seeds=(11, 22), population=12, generations=10, max_evaluations=100,
                        scenario_input=s, validate_pipeline=False)
    assert s == original
    for seed in (11, 22):
        g, m = (result['runs'][f'GA_{mode}_{seed}'] for mode in ('GROUND', 'MIXED'))
        assert g['search']['incumbent_plan'] == m['search']['incumbent_plan']
        assert g['search']['preparation_evaluations'] == m['search']['preparation_evaluations']
        assert all(r['search']['total_evaluations'] <= 100 for r in (g, m))
        assert m['metrics']['objective'] <= Evaluator(s).evaluate(m['search']['incumbent_plan'])[0]['objective']
    assert len(result['summary']) == 2
    assert all(r['seeds'] == 2 and r['std_objective'] >= 0 for r in result['summary'])


def test_replay_and_mosaic_diagnostics_conserve_all_flights():
    e = Evaluator(small())
    metrics, rows, audit = e.evaluate([[0, 0], [0, 0]])
    assert not frame(rows, 9.9)
    assert len(frame(rows, 11)) == 2
    assert not frame(rows, max(r['exit_min'] for r in rows))
    states = frame(rows, 10)
    assert states[0]['altitude_ft'] == 11000
    assert all(math.isfinite(s['ground_speed_kt']) for s in states)
    result = validate_runs({'NO_CONTROL': {'flights': rows, 'metrics': metrics}}, ['NO_CONTROL'], sample_min=5)
    assert result['NO_CONTROL']['new_hotspot_memberships'] == []
    assert result['NO_CONTROL']['frames'] > 1
    assert not result['NO_CONTROL']['accepted_in_study']


@pytest.mark.parametrize('key,value', [('penalty_lambda',float('nan')), ('penalty_power',True),
                                     ('hourly_capacity',0), ('capacity_interval_min',True),
                                     ('max_speed_reduction_pct',100), ('occupancy_limit',0)])
def test_invalid_inputs_rejected(key, value):
    s = small()
    s[key] = value
    with pytest.raises(ValueError):
        Evaluator(s)
