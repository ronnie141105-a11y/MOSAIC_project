"""Prepare/analyze the three windows in the user's VVTS data request, offline."""
import argparse
import csv
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import re
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from astra.studies.vvts_cases import DEFAULT_ROOT, TABLES, WINDOWS, export_suite, init_package, import_noaa_weather, run_suite, seed_saved_weather_case


def import_track(path, folder, *, callsign=None, aircraft_type=None, adep='', ades=''):
    """Canonical, AirNav CSV or FR24 CSV. UTC epoch is authoritative for FR24."""
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        columns = set(reader.fieldnames or [])
        rows = list(reader)
    output = []
    if set(TABLES['tracks.csv']) <= columns:
        output = rows
    else:
        if not callsign or not aircraft_type:
            raise ValueError('Provider track exports require --callsign and --aircraft-type metadata')
        airnav = {'Date/Time (UTC)','Latitude','Longitude','Altitude (ft)','Ground Speed (kts)','Heading'} <= columns
        fr24 = {'Timestamp','Callsign','Position','Altitude','Speed','Direction'} <= columns
        if not airnav and not fr24:
            raise ValueError('Unrecognized track CSV; use the canonical tracks.csv template')
        for row in rows:
            base = dict(flight_id=callsign, callsign=callsign, aircraft_type=aircraft_type,
                        adep=adep, ades=ades, on_ground='')
            if airnav:
                stamp = datetime.strptime(row['Date/Time (UTC)'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                base.update(time_utc=stamp.isoformat(), lat=row['Latitude'], lon=row['Longitude'],
                    altitude_ft=row['Altitude (ft)'], ground_speed_kt=row['Ground Speed (kts)'],
                    heading_deg=row['Heading'], vertical_speed_fpm=row.get('Vertical Speed (ft/min)',''), source='AirNav track CSV')
            else:
                if row['Callsign'].strip().upper() not in ('', callsign.upper()):
                    raise ValueError('FR24 callsign differs from supplied identity')
                stamp = datetime.fromtimestamp(float(row['Timestamp']), timezone.utc)
                if row.get('UTC'):
                    shown = datetime.fromisoformat(row['UTC'].replace('Z','+00:00'))
                    if shown.tzinfo is None:
                        shown = shown.replace(tzinfo=timezone.utc) # Explicitly named UTC column.
                    if abs((stamp-shown).total_seconds())>1:
                        raise ValueError('FR24 epoch and UTC columns disagree')
                lat, lon = row['Position'].strip(' ()[]').split(',')
                base.update(time_utc=stamp.isoformat(),lat=lat.strip(),lon=lon.strip(),
                    altitude_ft=row['Altitude'],ground_speed_kt=row['Speed'],heading_deg=row['Direction'],
                    vertical_speed_fpm='',source='Flightradar24 track CSV')
            output.append(base)
    target = Path(folder)/'tracks.csv'
    existing = []
    if target.exists():
        with target.open(encoding='utf-8-sig',newline='') as stream:
            existing = list(csv.DictReader(stream))
    keys = {(r['flight_id'],r['time_utc']) for r in existing}
    output = existing+[r for r in output if (r['flight_id'],r['time_utc']) not in keys]
    with target.open('w',encoding='utf-8-sig',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=TABLES['tracks.csv'])
        writer.writeheader();writer.writerows(output)
    return len(output)-len(existing)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir',type=Path,default=DEFAULT_ROOT)
    p.add_argument('--out',type=Path,default=Path('output/vvts_three_cases'))
    p.add_argument('--init',action='store_true',help='Create input templates and seed the archived 7 October observations')
    p.add_argument('--audit-only',action='store_true',help='Inspect inputs without running the trajectory/complexity pipeline')
    p.add_argument('--sample-interval-s',type=int,default=30)
    p.add_argument('--import-airnav',nargs=2,metavar=('CASE','JSON'))
    p.add_argument('--import-track',nargs=2,metavar=('CASE','CSV'))
    p.add_argument('--import-noaa-weather',type=Path,help='Import an archived NOAA observation bundle, without fetching')
    p.add_argument('--callsign');p.add_argument('--aircraft-type');p.add_argument('--adep',default='');p.add_argument('--ades',default='')
    a=p.parse_args()
    try:
        init_package(a.data_dir)
        if a.init:
            seed_saved_weather_case(a.data_dir)
        if a.import_noaa_weather:
            print('Added NOAA observations:',import_noaa_weather(a.import_noaa_weather,a.data_dir))
        valid={w['id'] for w in WINDOWS}
        for item in (a.import_airnav,a.import_track):
            if item and item[0] not in valid:
                raise ValueError('Case must be bad_weather, nominal, or holiday_peak')
        if a.import_airnav:
            case,path=a.import_airnav
            payload=json.loads(Path(path).read_text(encoding='utf-8'))
            if payload.get('success') is False or not isinstance(payload.get('flights'),list):
                raise ValueError('Expected a successful AirNav flight-search response')
            safe=json.dumps(payload)
            safe=re.sub(r'([?&]token=)[^&\s"\\]+',r'\1REDACTED',safe,flags=re.I)
            # Retain flight content only; credential-bearing transport fields are unnecessary.
            payload=json.loads(safe)
            content=json.dumps(dict(success=True,flights=payload['flights']),indent=2)
            target=a.data_dir/case/('observations_airnav_'+hashlib.sha256(content.encode()).hexdigest()[:12]+'.json')
            if not target.exists():
                target.write_text(content,encoding='utf-8')
        if a.import_track:
            case,path=a.import_track
            print('Imported track rows:',import_track(path,a.data_dir/case,callsign=a.callsign,
                aircraft_type=a.aircraft_type,adep=a.adep,ades=a.ades))
        result=run_suite(a.data_dir,sample_interval_s=a.sample_interval_s,run_pipeline=not a.audit_only)
        export_suite(result,a.out)
    except (ValueError,KeyError,OSError) as exc:
        p.exit(1,str(exc)+'\n')
    for c in result['cases']:
        print(c['id'],c['status'],'tracked flights:',c['recorded_flights'],'window samples:',c['source_samples_in_window'])
    print('Outputs:',a.out.resolve())


if __name__=='__main__':
    main()
