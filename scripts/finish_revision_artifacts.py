"""Build report artifacts only after the specified final study is published."""
from pathlib import Path
import json
import os
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
expected='20261031T023600Z-dbf5f3f6'
base=ROOT/'scenarios/synthetic/vvts_workbook_cases'
deadline=time.monotonic()+7200
print('Waiting for the complete validated ten-seed result',flush=True)
while True:
    try:
        parent=base/'workbook_peak_50/variants/full_route_ga'
        rid=json.loads((parent/'latest.json').read_text())['run_id']
        result=json.loads((parent/rid/'results.json').read_text(encoding='utf-8'))
        if rid==expected and len(result.get('native_trials',[]))==22:
            assert all(r['search']['optimizer_version']=='hybrid-ready-sequence-ga-3' for n,r in result['runs'].items() if n.startswith('TEAM_'))
            break
    except FileNotFoundError:pass
    if time.monotonic()>deadline:raise TimeoutError('Final study has not published; preserve the previous document')
    time.sleep(10)

venv=ROOT/'.venv/Scripts/python.exe'
bundled=Path('C:/Users/Lenovo/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe')
steps=[(venv,'scripts/correct_revision_metering_diagnostic.py'),(venv,'scripts/report_fcfs_ga_comparison.py'),(venv,'scripts/prepare_thesis_summary.py'),
    (bundled,'tmp/thesis_ch45/prepare_evidence.py'),(bundled,'tmp/thesis_ch45/revise_manuscript.py'),
    (bundled,'tmp/thesis_ch45/build_document.py')]
env=os.environ.copy();env['PYTHONIOENCODING']='utf-8'
for runtime,script in steps:
    print('Building '+script,flush=True)
    subprocess.run([str(runtime),script],cwd=ROOT,env=env,check=True)
print('ARTIFACT_READY_FOR_RENDER',flush=True)
