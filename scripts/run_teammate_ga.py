"""Run the reviewed teammate GA on MOSAIC's two video cases and publish replays."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from astra.optimization.teammate_cases import experiment, export_tables
from astra.optimization.video_cases import SEEDS


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=['all','nominal','holiday_peak'],default='all')
    parser.add_argument('--seeds',nargs='+',type=int,default=SEEDS)
    parser.add_argument('--population',type=int,default=80)
    parser.add_argument('--generations',type=int,default=150)
    parser.add_argument('--max-evaluations',type=int,default=6000)
    parser.add_argument('--no-legacy-comparison',action='store_true')
    parser.add_argument('--out',type=Path,default=ROOT/'output/teammate_ga')
    args=parser.parse_args()
    for case in ('nominal','holiday_peak') if args.case=='all' else (args.case,):
        def progress(update):
            print(case,json.dumps(update),flush=True)
        result=experiment(case,args.seeds,args.population,args.generations,args.max_evaluations,
                          compare_legacy=not args.no_legacy_comparison,progress=progress)
        target=args.out/result['run_id']/case
        export_tables(target,result)
        print(json.dumps(dict(case=case,run_id=result['run_id'],summary=result['summary'],
                              output=str(target)),ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    main()
