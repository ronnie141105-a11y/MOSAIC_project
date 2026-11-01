"""Revalidate frozen traffic after the common taxi-intersection correction."""
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from astra.studies.operational_cases import build

dest=ROOT/'output/scenario_revision_20261031'
p=dest/'protocol.json'
protocol=json.loads(p.read_text())
protocol['surface_correction']='A failed FCFS benchmark exposed a shared taxi-junction deadlock before overload GA runs. Apply the same intersection reservation to all methods; revalidate both references, preserving requested clocks, route mix and initial airborne geometry.'
protocol['nominal']='Preserve nominal demand, requested clocks, routes and initial airborne geometry; revalidate surface execution after the common intersection fix.'
p.write_text(json.dumps(protocol,indent=2),encoding='utf-8')
for case in ('workbook_low_20','workbook_peak_50'):
    folder=ROOT/'scenarios/synthetic/vvts_workbook_cases'/case
    m=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    rows=json.loads((folder/'source_rows.json').read_text(encoding='utf-8'))
    files=build(case,rows,m['source']['sha256'],baseline_manifest=m)
    new=json.loads(files['manifest.json'])
    for a,b in zip(m['flights'],new['flights']):
        if a['direction']=='arrival':
            assert all(a['initial_airborne_spec'][k]==b['initial_airborne_spec'][k] for k in ('lat','lon','altitude_ft'))
        else:assert a['requested_event_utc']==b['requested_event_utc']
    for name,data in files.items():(folder/name).write_bytes(data)
    print('Revalidated',case,new['sector_occupancy']['total_excess_aircraft_seconds'],flush=True)
