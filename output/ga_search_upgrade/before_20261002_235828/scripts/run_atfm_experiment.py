"""Run the same ATFM experiment used by the dashboard without starting HTTP."""
import argparse,csv,json
from pathlib import Path
from astra.optimization.atfm import experiment

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=Path('output/atfm_lab'))
    p.add_argument('--generations',type=int,default=100);p.add_argument('--population',type=int,default=60)
    a=p.parse_args();result=experiment(population=a.population,generations=a.generations)
    a.out.mkdir(parents=True,exist_ok=True)
    (a.out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    def csvfile(name,rows):
        with (a.out/name).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    csvfile('metrics.csv',[dict(method=name,**r['metrics']) for name,r in result['runs'].items()])
    csvfile('eta_stress.csv',result['stress']);csvfile('weight_sensitivity.csv',result['sensitivity'])
    for name,r in result['runs'].items():csvfile(name+'_flights.csv',r['flights'])
    print(json.dumps({name:r['metrics'] for name,r in result['runs'].items()},indent=2))
    print('Elapsed seconds:',result['elapsed_s'])
if __name__=='__main__':main()
