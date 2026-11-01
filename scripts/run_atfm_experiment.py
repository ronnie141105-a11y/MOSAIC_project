"""Run the same ATFM experiment used by the dashboard without starting HTTP."""
import argparse,csv,json,math
from pathlib import Path
from astra.optimization.atfm import experiment,metric_rows
from astra.optimization.uncertainty import uncertainty_experiment

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=None,
        help='Defaults to output/atfm_uncertainty with --uncertainty, otherwise output/atfm_lab')
    p.add_argument('--generations',type=int,default=None);p.add_argument('--population',type=int,default=None)
    p.add_argument('--max-evaluations',type=int,default=None,
                   help='Total search budget per seed, including incumbent preparation; uncertainty counts scenario rollouts')
    p.add_argument('--uncertainty',action='store_true',help='Optimize on training ETA/capacity realizations and evaluate frozen plans on a separate test set')
    p.add_argument('--risk-weight',type=float,default=.25,help='Weight on worst training objective, from 0 to 1 (default: .25)')
    p.add_argument('--eta-jitter-min',type=float,default=2,help='Maximum absolute ETA perturbation in minutes, from 0 to 10')
    p.add_argument('--capacity-drop',type=int,choices=(0,1,2),default=1,help='Maximum synthetic entry-capacity reduction per 15-minute bin')
    a=p.parse_args()
    if a.out is None:a.out=Path('output/atfm_uncertainty' if a.uncertainty else 'output/atfm_lab')
    population=a.population if a.population is not None else (40 if a.uncertainty else 60)
    generations=a.generations if a.generations is not None else (60 if a.uncertainty else 100)
    if not 4<=population<=100 or not 1<=generations<=200:
        p.error('population must be 4–100 and generations 1–200')
    if a.uncertainty:
        budget=a.max_evaluations if a.max_evaluations is not None else 6000
        if not 50<=budget<=20000:p.error('uncertainty max-evaluations must be 50–20000')
        for name,value,upper in [('risk-weight',a.risk_weight,1),('eta-jitter-min',a.eta_jitter_min,10)]:
            if not math.isfinite(value) or not 0<=value<=upper:p.error(f'{name} must be finite and between 0 and {upper}')
        result=uncertainty_experiment(population=population,generations=generations,max_evaluations=budget,
                                     risk_weight=a.risk_weight,eta_jitter_min=a.eta_jitter_min,capacity_drop=a.capacity_drop)
    else:
        result=experiment(population=population,generations=generations,max_evaluations=a.max_evaluations)
    a.out.mkdir(parents=True,exist_ok=True)
    (a.out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    def csvfile(name,rows):
        if not rows:return
        with (a.out/name).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    csvfile('metrics.csv',metric_rows(result))
    csvfile('exact_checks.csv',result['exact_checks'])
    csvfile('convergence.csv',[dict(method=name,objective_context=r['search'].get('objective_context','nominal'),**h,
        total_evaluations=h['evaluations']+r['search'].get('preparation_evaluations',0))
        for name,r in result['runs'].items() for h in r['history']])
    csvfile('held_out_realizations.csv' if a.uncertainty else 'eta_stress.csv',result['stress'])
    csvfile('weight_sensitivity.csv',result['sensitivity'])
    if result.get('uncertainty'):
        csvfile('uncertainty_summary.csv',result['uncertainty_summary'])
        (a.out/'uncertainty_realizations.json').write_text(json.dumps(result['uncertainty'],ensure_ascii=False,indent=2),encoding='utf-8')
    for name,r in result['runs'].items():csvfile(name+'_flights.csv',r['flights'])
    print(json.dumps({name:r['metrics'] for name,r in result['runs'].items()},indent=2))
    if result.get('uncertainty_summary'):
        print('Held-out uncertainty evaluation:')
        print(json.dumps([row for row in result['uncertainty_summary'] if row['split']=='test'],indent=2))
    print('Elapsed seconds:',result['elapsed_s'])
if __name__=='__main__':main()
