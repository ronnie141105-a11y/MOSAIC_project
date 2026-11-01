"""Archive the previous evidence, freeze the protocol, rebuild the overload case."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def archive():
    dest=ROOT/'output/scenario_revision_20261031'
    if (dest/'protocol.json').exists():
        return dest
    base=ROOT/'scenarios/synthetic/vvts_workbook_cases'
    for case in ('workbook_low_20','workbook_peak_50'):
        target=dest/'original_inputs'/case
        target.mkdir(parents=True,exist_ok=True)
        for src in (base/case).iterdir():
            if src.is_file():shutil.copy2(src,target/src.name)
        latest=base/case/'variants/full_route_ga/latest.json'
        shutil.copy2(latest,target/'old_latest.json')
    doc=ROOT/'output/thesis_ch45/Chuong_4_5_GA_Tan_Son_Nhat.docx'
    if doc.exists():shutil.copy2(doc,dest/doc.name)
    protocol=dict(version='controllable-bank-1',seeds=list(range(11,111,11)),
        population=60,generations=120,max_evaluations=6000,native_checks_per_seed=4,
        nominal='Preserve the existing 20-aircraft input files byte for byte.',
        overload_counts=dict(arrivals=36,departures=24),
        routes='Retain the existing route-family distributions and capacities.',
        arrival_initial_state='All moving upstream; minimum 20 min additional upstream lead; no circular holds.',
        arrival_capacity='Arrival-only paths must remain within sector capacities.',
        departure_ready_bank='Physical rank 0: 180 s; ranks 1..12: 1200+(rank-1)*90 s; ranks 13..23: 3000+(rank-13)*180 s.',
        acceptance='One-second physical safety, unchanged limits, arrival-only excess zero, combined reference excess positive. No acceptance criterion depends on GA results.',
        control_clock='Parked departure target CTOT = fixed requested ready-event + 0..60 min; no action retains reference. Committed surface aircraft cannot advance.',
        delay_clock='Departure: fixed requested ready-event; arrival: uncontrolled touchdown from the identical initial airborne state.',
        fcfs='Report both 1-min and 5-min action grids and use the lower native objective as the main FCFS comparator.',
        reporting='All 10 seeds, mean and sample SD; initialization gains separated from subsequent evolution; native 1-s execution determines final comparisons.')
    (dest/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
    return dest

def rebuild(dest):
    from astra.studies.operational_cases import build
    base=ROOT/'scenarios/synthetic/vvts_workbook_cases/workbook_peak_50'
    old=json.loads((base/'manifest.json').read_text(encoding='utf-8'))
    records=json.loads((base/'source_rows.json').read_text(encoding='utf-8'))
    files=build('workbook_peak_50',records,old['source']['sha256'])
    m=json.loads(files['manifest.json'])
    if m['case_design']['arrival_only_excess_aircraft_seconds']!=0:raise ValueError('Frozen arrival traffic already overloaded')
    staging=dest/'rebuilt_overload';staging.mkdir(exist_ok=True)
    for name,data in files.items():(staging/name).write_bytes(data)
    hashes={name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
    (dest/'frozen_overload_sha256.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
    for name in files:shutil.copy2(staging/name,base/name)
    print(json.dumps(dict(design=m['case_design'],occupancy=m['sector_occupancy']),indent=2),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--rebuild',action='store_true');args=parser.parse_args()
    dest=archive()
    if args.rebuild:rebuild(dest)
