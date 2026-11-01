"""Record the common final traffic inputs used by every compared method."""
from pathlib import Path
import hashlib
import json
ROOT=Path(__file__).resolve().parents[1]
base=ROOT/'scenarios/synthetic/vvts_workbook_cases'
dest=ROOT/'output/scenario_revision_20261031'
names=('manifest.json','tracks.csv','ground_tracks.json.gz','planning.csv','capacity.csv','fpl.csv')
snapshot={case:{name:hashlib.sha256((base/case/name).read_bytes()).hexdigest() for name in names}
    for case in ('workbook_low_20','workbook_peak_50')}
(dest/'final_frozen_inputs_sha256.json').write_text(json.dumps(snapshot,indent=2),encoding='utf-8')
print('Recorded final input hashes for both cases')
