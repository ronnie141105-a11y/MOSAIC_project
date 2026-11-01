"""Run both complete synthetic full-route studies and save GA replays/results."""
import argparse
import json
from pathlib import Path
import sys

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from astra.optimization.full_route_cases import experiment, export_comparison
from astra.studies.workbook_cases import CASES, ROOT


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=['all',*CASES],default='all')
    parser.add_argument('--seeds',nargs='+',type=int,default=list(range(11,111,11)))
    parser.add_argument('--population',type=int,default=60)
    parser.add_argument('--generations',type=int,default=120)
    parser.add_argument('--max-evaluations',type=int,default=6000)
    parser.add_argument('--root',type=Path,default=ROOT)
    args=parser.parse_args()
    for case_id in CASES if args.case=='all' else [args.case]:
        def progress(value):
            print(json.dumps(dict(case_id=case_id,**value)),flush=True)
        result=experiment(case_id,args.seeds,args.population,args.generations,args.max_evaluations,args.root,progress=progress)
        print(json.dumps(dict(case_id=case_id,run_id=result['run_id'],baseline=result['baseline'],
            selected={m:r.get('native_execution_metrics',r['metrics']) for m,r in result['post_validation']['checks'].items()},elapsed_s=result['elapsed_s'])),flush=True)
    if args.case=='all':
        print('Comparison: '+str(export_comparison(args.root)),flush=True)


if __name__=='__main__':
    main()
