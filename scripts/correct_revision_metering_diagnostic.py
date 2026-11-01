"""Align the auxiliary metering diagnostic with the new fixed-ready clock.

Primary delays, objectives, plans and all simulation measurements are unchanged.
The old diagnostic subtracted only gene levels and counted embedded reference
waiting as extra native metering for committed/no-action departures.
"""
from pathlib import Path
import csv
import json
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from astra.optimization.full_route_cases import saved_folder,summarize_native,epoch
from astra.optimization.teammate_cases import export_tables
from astra.studies.workbook_cases import ROOT as CASE_ROOT,csv_bytes,json_bytes

for case in ('workbook_low_20','workbook_peak_50'):
    folder=saved_folder(case)
    result=json.loads((folder/'results.json').read_text(encoding='utf-8'))
    baseline=json.loads((CASE_ROOT/case/'manifest.json').read_text(encoding='utf-8'))
    metadata={f['callsign']:f for f in baseline['flights']}
    fixed={}
    for p in folder.rglob('execution_flights.csv'):
        mpath=p.parent/'manifest.json'
        if not mpath.exists():continue
        m=json.loads(mpath.read_text(encoding='utf-8'))
        metrics=m['optimization_metrics'];meter=metrics['airborne_holding_delay_min']
        with p.open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.DictReader(stream))
        for row in rows:
            if row['direction']!='departure':continue
            old=metadata[row['callsign']]
            anchor=epoch(old['simulated_slot_utc'])
            if int(row['proposed_measure'])==1:
                if old['origin_status_at_planning']=='PARKED':anchor=epoch(old['requested_event_utc'])
                anchor+=float(row['proposed_level'])*60
            meter+=max(0,(epoch(row['executed_runway_utc'])-anchor)/60)
        metrics['safety_metering_delay_min']=meter
        mpath.write_bytes(json_bytes(m));fixed[p.parent.resolve()]=meter
    for t in result['native_trials']:
        t['metrics']['safety_metering_delay_min']=fixed[(folder/'native_trials'/t['run'].lower()).resolve()]
    for b in result['fcfs_benchmarks']:
        b['metrics']['safety_metering_delay_min']=fixed[(folder/'fcfs_benchmarks'/b['method'].lower()).resolve()]
    for check in result['post_validation']['checks'].values():
        actual=next(t['metrics'] for t in result['native_trials'] if t['run']==check['selected_run'])
        check['native_execution_metrics']=actual
    result['native_summary']=summarize_native(result['native_trials'])
    result['diagnostic_corrections']=['Auxiliary safety metering excludes embedded reference waiting; primary metrics and selected plans unchanged.']
    export_tables(folder,result)
    (folder/'native_trials.json').write_bytes(json_bytes(result['native_trials']))
    (folder/'native_summary.csv').write_bytes(csv_bytes(list(result['native_summary'][0]),result['native_summary']))
    flat=[dict(method=t['method'],run=t['run'],seed=t['seed'],**{k:v for k,v in t['metrics'].items() if not isinstance(v,dict)}) for t in result['native_trials']]
    (folder/'native_trials.csv').write_bytes(csv_bytes(list(flat[0]),flat))
    print('Corrected auxiliary metering diagnostic',case,flush=True)
