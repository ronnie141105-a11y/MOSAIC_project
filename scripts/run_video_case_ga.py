"""Run the categorical MOSAIC GA on the two reviewed video scenarios."""
import argparse
import csv
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from astra.optimization.video_cases import SEEDS, experiment


def export(root,result):
    root.mkdir(parents=True,exist_ok=True)
    (root/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    def table(name,rows):
        with (root/name).open('w',newline='',encoding='utf-8-sig') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    table('summary.csv',result['summary'])
    table('metrics.csv',[dict(method=name,**r['metrics']) for name,r in result['runs'].items()])
    table('convergence.csv',[dict(method=name,**h) for name,r in result['runs'].items() for h in r['history']])
    for method,name in result['best_methods'].items():table(method+'_flights.csv',result['runs'][name]['flights'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=['all','nominal','holiday_peak'],default='all')
    parser.add_argument('--out',type=Path,default=ROOT/'output/video_case_ga/2026-10-13')
    parser.add_argument('--seeds',nargs='+',type=int,default=SEEDS)
    parser.add_argument('--population',type=int,default=80)
    parser.add_argument('--generations',type=int,default=160)
    parser.add_argument('--max-evaluations',type=int,default=6000)
    args=parser.parse_args()
    for case in ('nominal','holiday_peak') if args.case=='all' else (args.case,):
        result=experiment(case,args.seeds,args.population,args.generations,args.max_evaluations)
        export(args.out/case,result)
        print(json.dumps(dict(case=case,baseline=result['baseline'],summary=result['summary'],elapsed_s=result['elapsed_s']),ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
