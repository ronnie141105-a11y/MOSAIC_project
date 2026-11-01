"""Run the same ATFM experiment used by the dashboard without starting HTTP."""
import argparse,csv,json
from pathlib import Path
from astra.optimization.atfm import experiment,metric_rows

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=Path('output/atfm_lab'))
    p.add_argument('--generations',type=int,default=100);p.add_argument('--population',type=int,default=60)
    p.add_argument('--max-evaluations',type=int,default=None,
                   help='Total fitness budget per seed, including the ground incumbent used by mixed GA')
    a=p.parse_args();result=experiment(population=a.population,generations=a.generations,max_evaluations=a.max_evaluations)
    a.out.mkdir(parents=True,exist_ok=True)
    (a.out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    def csvfile(name,rows):
        if not rows:return
        with (a.out/name).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    csvfile('metrics.csv',metric_rows(result))
    csvfile('exact_checks.csv',result['exact_checks'])
    csvfile('convergence.csv',[dict(method=name,**h,
        total_evaluations=h['evaluations']+r['search'].get('preparation_evaluations',0))
        for name,r in result['runs'].items() for h in r['history']])
    csvfile('eta_stress.csv',result['stress']);csvfile('weight_sensitivity.csv',result['sensitivity'])
    for name,r in result['runs'].items():csvfile(name+'_flights.csv',r['flights'])
    print(json.dumps({name:r['metrics'] for name,r in result['runs'].items()},indent=2))
    print('Elapsed seconds:',result['elapsed_s'])
if __name__=='__main__':main()
