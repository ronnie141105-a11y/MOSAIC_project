"""Execute the preregistered ten-seed native comparison for one case."""
from pathlib import Path
import argparse
import json
import hashlib
import pickle
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from astra.optimization.full_route_cases import experiment, export_comparison, FullRouteEvaluator, VERSION

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('case_id');args=parser.parse_args()
    protocol=json.loads((ROOT/'output/scenario_revision_20261031/protocol.json').read_text())
    progress=lambda p:print(json.dumps(p),flush=True)
    base=ROOT/'scenarios/synthetic/vvts_workbook_cases'/args.case_id
    digest=hashlib.sha256((VERSION+str((base/'manifest.json').stat().st_mtime_ns)).encode()).hexdigest()[:16]
    cache=ROOT/'tmp'/f'{args.case_id}_{digest}_tables.pkl'
    reused=cache.exists()
    if reused:
        with cache.open('rb') as stream:e=pickle.load(stream)
        if any(hashlib.sha256((base/name).read_bytes()).hexdigest()!=value for name,value in e.input_sha256.items()):
            raise ValueError('Cached trajectory inputs changed; remove this task-local cache and rebuild')
        print('Reusing local trajectory tables',flush=True)
    else:
        e=FullRouteEvaluator(args.case_id,expanded=True,progress=progress)
        with cache.open('wb') as stream:pickle.dump(e,stream,protocol=pickle.HIGHEST_PROTOCOL)
    e.trajectory_tables_cache_reused=reused
    result=experiment(args.case_id,seeds=protocol['seeds'],population=protocol['population'],
        generations=protocol['generations'],max_evaluations=protocol['max_evaluations'],
        progress=progress,evaluator=e)
    print(json.dumps(dict(run_id=result['run_id'],native_summary=result['native_summary'])),flush=True)
    try:export_comparison()
    except ValueError:pass # the other case can still be on its old input version
