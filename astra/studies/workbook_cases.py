"""Source-value ingestion and native full-cycle study package entry points.

Original workbook values remain evidence. New routes, schedules, ground
journeys and instantaneous sector limits are owned by operational_cases.
"""
from collections import Counter
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import posixpath
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2] / 'scenarios/synthetic/vvts_workbook_cases'
CASES = {
    'workbook_peak_50': dict(sheet='Peak_50',label='Sector overload · full airport / sector cycle',
        study_role='over_capacity',local_start='2026-10-21T07:00:00+07:00',
        local_end='2026-10-21T10:00:00+07:00',arrivals=24,departures=18,
        source_arrivals=29,source_departures=21,regional_arrivals=18,gate_flow=True),
    'workbook_low_20': dict(sheet='Low_20',label='Nominal · full airport / sector cycle',
        study_role='nominal',local_start='2026-10-21T07:00:00+07:00',
        local_end='2026-10-21T10:00:00+07:00',arrivals=8,departures=6,source_arrivals=11,source_departures=9,regional_arrivals=6,gate_flow=True),
}
TYPE_MAP={'B787-9':'B789','B737-800':'B738','A320':'A320','A321':'A321','A350':'A350'}
TRACK_FIELDS=['flight_id','callsign','aircraft_type','adep','ades','time_utc','lat','lon',
              'altitude_ft','ground_speed_kt','heading_deg','vertical_speed_fpm','on_ground','source']
NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def stamp(epoch):
    return datetime.fromtimestamp(float(epoch),timezone.utc).isoformat(timespec='milliseconds')


def json_bytes(value):
    return (json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')


def csv_bytes(fields,rows):
    stream=io.StringIO(newline='')
    writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n')
    writer.writeheader();writer.writerows(rows)
    return stream.getvalue().encode('utf-8')


def read_workbook(path):
    """Read values only using OOXML; never execute formulas, links or macros."""
    with ZipFile(path) as archive:
        shared = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            shared = [''.join(si.itertext()) for si in ET.fromstring(archive.read('xl/sharedStrings.xml'))]
        relationships = {r.attrib['Id']: r.attrib['Target']
                         for r in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        sheets = ET.fromstring(archive.read('xl/workbook.xml')).find('s:sheets', NS)
        result = {}
        for sheet in sheets:
            name = sheet.attrib['name']
            if name not in {spec['sheet'] for spec in CASES.values()}:
                continue
            rid = sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']
            target = relationships[rid]
            target = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
            rows = []
            for row in ET.fromstring(archive.read(target)).findall('s:sheetData/s:row', NS):
                values = {}
                for cell in row.findall('s:c', NS):
                    if cell.find('s:f', NS) is not None:
                        raise ValueError(f'{name}!{cell.attrib["r"]}: formulas are not scenario inputs')
                    column = ''.join(c for c in cell.attrib['r'] if c.isalpha())
                    kind = cell.attrib.get('t')
                    value = cell.find('s:v', NS)
                    raw = value.text if value is not None else None
                    if kind == 'inlineStr':
                        raw = ''.join(t.text or '' for t in cell.findall('.//s:t', NS))
                    elif kind == 's':
                        raw = shared[int(raw)]
                    elif raw is not None and kind not in ('str', 'e'):
                        raw = float(raw)
                        if not math.isfinite(raw):
                            raise ValueError('Nonfinite workbook input')
                        if raw.is_integer():
                            raw = int(raw)
                    values[column] = raw
                rows.append((int(row.attrib['r']), values))
            headers = rows[0][1]
            required = {'Callsign', 'AircraftType', 'WakeCategory', 'FlightType', 'Airport',
                        'EntryGate', 'Runway', 'OptimizedRoute', 'ScenarioWindowUTC', 'DataNature'}
            if not required.issubset(set(headers.values())):
                raise ValueError(f'Missing source columns in {name}')
            records = [dict(source_row=number, **{header: cells.get(col) for col, header in headers.items()})
                       for number, cells in rows[1:] if cells.get('A') is not None]
            result[name] = records
    if set(result) != {spec['sheet'] for spec in CASES.values()}:
        raise ValueError('Expected Peak_50 and Low_20 source sheets')
    return result



def build_case(case_id,records,source_hash):
    if case_id not in CASES:raise ValueError('Unknown synthetic study')
    spec=CASES[case_id]
    if dict(Counter(r['FlightType'] for r in records))!={'Arrival':spec.get('source_arrivals',spec['arrivals']),'Departure':spec.get('source_departures',spec['departures'])}:
        raise ValueError('Unexpected source population')
    if len({r['Callsign'] for r in records})!=len(records):
        raise ValueError('Duplicate source callsigns')
    if any(r['Airport']!='TSN' or r['AircraftType'] not in TYPE_MAP for r in records):
        raise ValueError('Unsupported airport or aircraft type')
    from astra.studies.operational_cases import build
    reference=None
    path=ROOT/case_id/'manifest.json'
    if path.is_file():
        saved=json.loads(path.read_text(encoding='utf-8'))
        if (saved.get('source',{}).get('sha256')==source_hash and
                saved.get('counts',{}).get('arrivals')==spec['arrivals'] and
                all(f.get('initial_airborne_spec') for f in saved['flights'] if f['direction']=='arrival')):
            reference=saved
    return build(case_id,records,source_hash,baseline_manifest=reference)


def build_packages(workbook):
    records=read_workbook(workbook)
    digest=hashlib.sha256(Path(workbook).read_bytes()).hexdigest()
    return {case_id:build_case(case_id,records[spec['sheet']],digest) for case_id,spec in CASES.items()}
