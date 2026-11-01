"""Publish a reproducible, native-validated fixed-order gate-flow study."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from astra.optimization.full_route_cases import experiment,FullRouteEvaluator,VERSION
import gzip
import pickle
import hashlib

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case',choices=['workbook_low_20','workbook_peak_50'])
    parser.add_argument('--seeds',type=int,nargs='+',default=[11])
    parser.add_argument('--evaluations',type=int,default=2000)
    parser.add_argument('--cache-evaluator',action='store_true',help='Reuse trusted local tables only when input hashes and evaluator version match')
    args=parser.parse_args()
    progress=lambda row:print(json.dumps(row),flush=True)
    evaluator=None
    if args.cache_evaluator:
        from astra.studies.workbook_cases import ROOT
        cache=Path(__file__).resolve().parents[1]/'tmp'/('evaluator_'+args.case+'.pkl.gz')
        if cache.exists():
            with gzip.open(cache,'rb') as stream:version,candidate=pickle.load(stream)
            if version==VERSION and all(hashlib.sha256((ROOT/args.case/n).read_bytes()).hexdigest()==v for n,v in candidate.input_sha256.items()):
                evaluator=candidate;progress(dict(phase='reused_local_tables'))
        if evaluator is None:
            evaluator=FullRouteEvaluator(args.case,progress=progress,expanded=True)
            temporary=cache.with_suffix('.tmp')
            with gzip.open(temporary,'wb',compresslevel=1) as stream:pickle.dump((VERSION,evaluator),stream,protocol=pickle.HIGHEST_PROTOCOL)
            temporary.replace(cache)
    result=experiment(args.case,seeds=tuple(args.seeds),population=20,generations=30,
        max_evaluations=args.evaluations,progress=progress,evaluator=evaluator)
    print(json.dumps(dict(run_id=result['run_id'],native_summary=result['native_summary']),ensure_ascii=False),flush=True)
