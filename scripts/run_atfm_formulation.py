"""Reproducible Chapter 3 experiments; no external accounts/data required."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from astra.optimization.atfm import metric_rows
from astra.optimization.formulation import CASES, DEFAULT_SEEDS, Evaluator, exact_optimize, experiment, make_scenario, optimize


def exact_checks():
    rows = []
    for case in ('low_demand', 'conflict', 'fixed_airborne'):
        s = make_scenario('nominal')
        s['flights'] = s['flights'][1:3]
        for i, f in enumerate(s['flights']):
            eta = 10+i*(30 if case == 'low_demand' else .5)
            takeoff = -70 if case == 'fixed_airborne' and i == 1 else -30
            f.update(gate='G_N', eta_min=eta, reference_takeoff_min=takeoff,
                     travel_to_entry_min=eta-takeoff, ground_eligible=takeoff >= s['decision_min'])
        e = Evaluator(s)
        for mode in ('ground', 'mixed'):
            exact, objective, count = exact_optimize(e, mode)
            for seed in (11, 22, 33):
                plan, _, search = optimize(e, mode, seed, 20, 50, 1000)
                actual = e.evaluate(plan)[0]['objective']
                rows.append(dict(case=case, mode=mode, seed=seed, exact_objective=objective,
                    ga_objective=actual, absolute_gap=actual-objective, exact_evaluations=count,
                    ga_evaluations=search['total_evaluations'], exact_plan=exact, ga_plan=plan))
    return rows


def export_result(out, result):
    out.mkdir(parents=True, exist_ok=True)
    (out/'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (out/'scenario.json').write_text(json.dumps(result['scenario'], ensure_ascii=False, indent=2), encoding='utf-8')
    def csvfile(name, rows):
        if not rows:
            return
        with (out/name).open('w', encoding='utf-8-sig', newline='') as target:
            writer = csv.DictWriter(target, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    csvfile('metrics.csv', metric_rows(result))
    csvfile('summary.csv', result['summary'])
    csvfile('cost_table.csv', result['cost_table'])
    csvfile('penalty_sensitivity.csv', result['sensitivity'])
    csvfile('exact_checks.csv', result['exact_checks'])
    csvfile('convergence.csv', [dict(method=name, **h,
        total_evaluations=h['evaluations']+r['search'].get('preparation_evaluations', 0))
        for name, r in result['runs'].items() for h in r['history']])
    for name, run in result['runs'].items():
        csvfile(name+'_flights.csv', run['flights'])
    for name, report in result['pipeline_validation'].items():
        csvfile(name+'_complexity.csv', report['samples'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=(*CASES, 'all'), default='existing')
    parser.add_argument('--scenario', type=Path, help='Explicit Chapter 3 JSON inputs, e.g. an exported scenario.json')
    parser.add_argument('--out', type=Path, default=Path('output/atfm_formulation'))
    parser.add_argument('--population', type=int, default=60)
    parser.add_argument('--generations', type=int, default=150)
    parser.add_argument('--max-evaluations', type=int, default=6000)
    parser.add_argument('--seeds', type=int, nargs='+', default=DEFAULT_SEEDS)
    parser.add_argument('--penalty-lambda', type=float, default=1000)
    parser.add_argument('--penalty-power', type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    if args.scenario and args.case == 'all':
        parser.error('--scenario cannot be combined with --case all')
    source = json.loads(args.scenario.read_text(encoding='utf-8-sig')) if args.scenario else None
    checks = exact_checks()
    cases = CASES if args.case == 'all' else (args.case,)
    for case in cases:
        result = experiment(case, seeds=args.seeds, population=args.population, generations=args.generations,
                            max_evaluations=args.max_evaluations, penalty_lambda=args.penalty_lambda,
                            penalty_power=args.penalty_power, scenario_input=source)
        result['exact_checks'] = checks
        original = Path('docs/sources/bai_toan_toi_uu.md')
        if original.exists():
            result['formulation_source'] = dict(path=str(original), sha256=hashlib.sha256(original.read_bytes()).hexdigest())
        out = args.out/case if args.case == 'all' else args.out
        export_result(out, result)
        print(json.dumps(dict(case=case, summary=result['summary'], best_methods=result['best_methods'],
                              elapsed_s=result['elapsed_s']), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
