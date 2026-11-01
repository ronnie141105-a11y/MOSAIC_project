"""Promote regional GDP cohorts while preserving old airborne initial states."""
from pathlib import Path
import json
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from astra.studies.operational_cases import build
from astra.studies.workbook_cases import ROOT as CASE_ROOT

archive=ROOT/'output/gate_flow_revision_20261101'
for case in ('workbook_low_20','workbook_peak_50'):
    folder=CASE_ROOT/case;backup=archive/'previous_inputs'/case;backup.mkdir(parents=True,exist_ok=True)
    for p in folder.iterdir():
        if p.is_file() and not (backup/p.name).exists():shutil.copy2(p,backup/p.name)
    manifest=json.loads((backup/'manifest.json').read_text(encoding='utf-8'))
    records=json.loads((backup/'source_rows.json').read_text(encoding='utf-8'))
    print('BUILDING',case,flush=True)
    files=build(case,records,manifest['source']['sha256'])
    if json.loads(files['manifest.json'])['flow_audit']['violating_pairs']:
        raise ValueError('Gate programme failed validation; preserve the current inputs')
    staged=archive/'staged'/case;staged.mkdir(parents=True,exist_ok=True)
    for name,data in files.items():(staged/name).write_bytes(data)
    for name in files:shutil.copy2(staged/name,folder/name)
    print('PROMOTED',case,json.loads(files['manifest.json'])['counts'],flush=True)
