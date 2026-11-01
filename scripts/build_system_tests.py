"""Generate separated synthetic Centre/Approach/Tower test fixtures."""
from pathlib import Path
import json
import sys
import argparse
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from astra.studies.system_tests import CASES,build

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cases',nargs='*',choices=tuple(CASES),help='Default: rebuild every test')
    args=parser.parse_args()
    for case in args.cases or CASES:
        manifest=build(case)
        print(json.dumps(dict(case_id=case,counts=manifest['counts'],duration_s=manifest['duration_s'],
            violating_pairs=manifest['separation_audit']['violating_pairs'],
            minimum_transfer_gap_s=manifest['separation_audit']['minimum_arrival_transfer_gap_s'])),flush=True)
