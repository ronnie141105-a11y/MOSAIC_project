"""Three exact VVTS study windows, with observed inputs and explicit data gaps.

No provider requests, invented traffic, capacity inference, or applied clearances.
The package accepts recorded flight-search JSON and canonical CSV exports.
"""
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import csv
import hashlib
import json
from pathlib import Path
import re
import statistics

from astra.airspace import configure_profile
from astra.interface.airnav_replay import AirNavDataset, AirNavReplayConnector
from astra.pipeline import Pipeline
from astra.studies.airnav import forecast_errors
from astra.utils.config import ASTRAConfig
from astra.utils.geodesy import haversine_distance_nm

PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = PROJECT / 'scenarios/recorded/vvts_cases'
WINDOWS = (
    dict(id='bad_weather', label='Thời tiết xấu', local_start='2026-10-07T17:00:00+07:00',
         local_end='2026-10-07T19:00:00+07:00', target='TSRA / +TSRA; kiểm tra gió từ báo cáo quan trắc'),
    dict(id='nominal', label='Điều kiện bình thường', local_start='2026-10-08T09:00:00+07:00',
         local_end='2026-10-08T11:00:00+07:00', target='Thời tiết tốt và cấu hình đường băng phù hợp; cần xác minh'),
    dict(id='holiday_peak', label='Cao điểm Tết', local_start='2026-02-22T10:00:00+07:00',
         local_end='2026-02-22T12:00:00+07:00', target='Planned demand > declared capacity; cần xác minh'),
)
TABLES = {
    'tracks.csv': ['flight_id','callsign','aircraft_type','adep','ades','time_utc','lat','lon',
                   'altitude_ft','ground_speed_kt','heading_deg','vertical_speed_fpm','on_ground','source'],
    'flights.csv': ['flight_id','callsign','aircraft_type','adep','ades','status',
                    'scheduled_departure_utc','scheduled_arrival_utc','actual_takeoff_utc',
                    'actual_landing_utc','actual_offblock_utc','actual_inblock_utc','runway','source'],
    'fpl.csv': ['flight_id','callsign','aircraft_type','adep','ades','eobt_utc','eet_min',
                'filed_route','issued_at_utc','raw_fpl','source'],
    'weather.csv': ['report_type','observation_utc','issue_utc','valid_from_utc','valid_to_utc','raw','source'],
    'capacity.csv': ['start_utc','end_utc','resource','flights_per_interval','evidence','source'],
    'demand.csv': ['start_utc','end_utc','resource','flights_per_interval','evidence','source'],
    'measures.csv': ['measure_id','type','issued_at_utc','start_utc','end_utc','reason','source'],
    'ctot.csv': ['flight_id','callsign','revision_utc','eobt_utc','ctot_utc','atfm_delay_min','source'],
}


def utc(value):
    stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Timestamps must include UTC Z or an explicit timezone offset')
    return stamp.astimezone(timezone.utc)


def _write_csv(path, fields, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path):
    if not path.exists():
        return []
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    return [row for row in rows if any(v and v.strip() for v in row.values())]


def init_package(root=DEFAULT_ROOT):
    root = Path(root)
    for spec in WINDOWS:
        folder = root / spec['id']
        folder.mkdir(parents=True, exist_ok=True)
        metadata = folder / 'coverage.json'
        if not metadata.exists():
            metadata.write_text(json.dumps(dict(complete_airport_traffic=False, complete_fpl=False,
                weather_complete=False, declared_capacity_verified=False, planned_demand_complete=False,
                analysis_resource='VVTS_ARRIVAL_RUNWAY', notes=[]), indent=2), encoding='utf-8')
        for name, fields in TABLES.items():
            if not (folder / name).exists():
                _write_csv(folder / name, fields, [])
    manifest = root / 'study.json'
    if not manifest.exists():
        manifest.write_text(json.dumps(dict(schema_version=1, airport='VVTS', timezone='UTC+07:00',
            source_request='D:/VVTS_ATFM_data_request.pdf', holiday_window_confirmed_by_user=True,
            windows=WINDOWS), ensure_ascii=False, indent=2), encoding='utf-8')
    return root


def seed_saved_weather_case(root=DEFAULT_ROOT, source_dir=None):
    """Reuse archived observations. Seed only absent/empty files; retain user data."""
    source_dir = Path(source_dir or PROJECT / 'output/weather_capture/2026-10-07')
    root = init_package(root)
    folder = root / 'bad_weather'
    if not source_dir.exists():
        return
    board = json.loads((source_dir / 'traffic_board.json').read_text(encoding='utf-8'))
    types = {r['cells'][0]: r['cells'][1] for r in board['rows'] if len(r['cells']) >= 2}
    observations = folder / 'observations.json'
    if not observations.exists():
        flights, sources = [], []
        for path in sorted(source_dir.glob('*_track.json')):
            track = json.loads(path.read_text(encoding='utf-8'))
            identity = re.search(r'/history/\d{8}/[^/]+/([^/]+)/([^/]+)', track['source_url'])
            positions = [dict(timestamp=p['time_utc'], latitude=p['lat'], longitude=p['lon'],
                altitude=p.get('altitude_ft'), groundSpeed=p.get('groundspeed_kt'),
                heading=p.get('course_deg'), verticalRate=None) for p in track['samples']]
            flights.append(dict(callsign=track['callsign'], aircraftType=types[track['callsign']],
                depAirportIcao=identity[1] if identity else None,
                arrAirportIcao=identity[2] if identity else None, positions=positions))
            sources.append(dict(file=str(path.relative_to(PROJECT)), url=track['source_url'],
                retrieved_at_utc=track['retrieved_at_utc'], sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        observations.write_text(json.dumps(dict(success=True, flights=flights), indent=2), encoding='utf-8')
        (folder / 'sources.json').write_text(json.dumps(dict(provider='FlightAware', tracks=sources,
            caveats=['Selected flights only; not the full arrival/departure population.',
                'Tracks end at the source capture cutoff, before the 19:00 end of the requested window.',
                'Vertical speed is absent in source rows; recovery uses past altitude only.',
                'Circling does not establish a holding clearance, fix assignment, or delay cause.',
                'VJC211 diversion remains unconfirmed.']), indent=2), encoding='utf-8')
    if not _read_csv(folder / 'weather.csv'):
        record = json.loads((source_dir / 'metar_6h.json').read_text(encoding='utf-8'))
        weather = [dict(report_type=p.get('metarType','METAR'),
            observation_utc=datetime.fromtimestamp(p['obsTime'], timezone.utc).isoformat(),
            issue_utc='', valid_from_utc='', valid_to_utc='', raw=p['rawOb'], source=record['source_url'])
            for p in json.loads(record['body'])]
        taf_record = json.loads((source_dir / 'taf.json').read_text(encoding='utf-8'))
        for p in json.loads(taf_record['body']):
            def stamp(key):
                value = p.get(key)
                return datetime.fromtimestamp(value, timezone.utc).isoformat() if isinstance(value,(int,float)) else value or ''
            weather.append(dict(report_type='TAF', observation_utc='', issue_utc=stamp('issueTime'),
                valid_from_utc=stamp('validTimeFrom'), valid_to_utc=stamp('validTimeTo'),
                raw=p['rawTAF'], source=taf_record['source_url']))
        _write_csv(folder / 'weather.csv', TABLES['weather.csv'], weather)
    unverified = folder / 'ctot_unverified.json'
    if not unverified.exists() and (source_dir / 'vatm_ctot.json').exists():
        unverified.write_bytes((source_dir / 'vatm_ctot.json').read_bytes())


def dataset_for_case(folder):
    folder = Path(folder)
    flights = []
    contents = []
    for path in sorted(folder.glob('observations*.json')):
        payload = json.loads(path.read_text(encoding='utf-8'))
        if payload.get('success') is False or not isinstance(payload.get('flights'),list):
            raise ValueError('Expected a successful flight-search recording')
        by_callsign = {f.get('callsign') or f.get('flightNumberIcao') or f.get('flightNumberIata'):f for f in flights}
        for flight in payload['flights']:
            key = flight.get('callsign') or flight.get('flightNumberIcao') or flight.get('flightNumberIata')
            previous = by_callsign.get(key)
            if previous is None:
                flights.append(flight);by_callsign[key]=flight
            else:
                if previous.get('aircraftType') != flight.get('aircraftType'):
                    raise ValueError('Conflicting aircraft type for the same callsign across recordings')
                merged = dict(previous)
                merged.update({k:v for k,v in flight.items() if k!='positions' and v is not None})
                merged['positions'] = previous.get('positions',[])+flight.get('positions',[])
                previous.clear();previous.update(merged)
        contents.append(path.read_bytes())
    rows = _read_csv(folder / 'tracks.csv')
    if rows:
        groups = {}
        for row in rows:
            key = row.get('flight_id') or row['callsign']
            if not row.get('callsign') or not row.get('aircraft_type'):
                raise ValueError('Track CSV requires callsign and aircraft_type; use FPL/flight metadata')
            group = groups.setdefault(key, dict(callsign=row['callsign'], aircraftType=row['aircraft_type'],
                depAirportIcao=row.get('adep'), arrAirportIcao=row.get('ades'), positions=[]))
            if (group['callsign'],group['aircraftType']) != (row['callsign'],row['aircraft_type']):
                raise ValueError('Conflicting identity within a flight_id')
            group['positions'].append(dict(timestamp=utc(row['time_utc']).isoformat(), latitude=row['lat'],
                longitude=row['lon'], altitude=row.get('altitude_ft'), groundSpeed=row.get('ground_speed_kt'),
                heading=row.get('heading_deg'), verticalRate=row.get('vertical_speed_fpm'),
                onGround=True if row.get('on_ground','').lower() == 'true' else None))
        by_callsign = {f.get('callsign') or f.get('flightNumberIcao'):f for f in flights}
        for group in groups.values():
            existing = by_callsign.get(group['callsign'])
            if existing is None:
                flights.append(group)
                by_callsign[group['callsign']] = group
            else:
                if existing.get('aircraftType') != group['aircraftType']:
                    raise ValueError('Conflicting aircraft type between recording and imported CSV')
                existing.setdefault('positions',[]).extend(group['positions'])
        contents.append((folder / 'tracks.csv').read_bytes())
    return AirNavDataset(flights,source_hash=hashlib.sha256(b'\0'.join(contents)).hexdigest()) if flights else None


def import_noaa_weather(path, root=DEFAULT_ROOT):
    """Append archived NOAA observations with full dates; retain distinct revisions."""
    record = json.loads(Path(path).read_text(encoding='utf-8'))
    source = record['source_url']
    counts = {}
    for spec in WINDOWS:
        start,end = utc(spec['local_start']),utc(spec['local_end'])
        folder = Path(root)/spec['id']
        rows = _read_csv(folder/'weather.csv')
        keys = {(r['report_type'],r['observation_utc'],r['raw']) for r in rows}
        added = 0
        for report in record['observations']:
            stamp = datetime.fromtimestamp(report['obsTime'],timezone.utc)
            if report.get('icaoId')!='VVTS' or not start <= stamp < end:
                continue
            row = dict(report_type=report.get('metarType','METAR'),observation_utc=stamp.isoformat(),
                issue_utc='',valid_from_utc='',valid_to_utc='',raw=report['rawOb'],source=source)
            key = (row['report_type'],row['observation_utc'],row['raw'])
            if key not in keys:
                rows.append(row);keys.add(key);added+=1
        if added:
            _write_csv(folder/'weather.csv',TABLES['weather.csv'],rows)
        counts[spec['id']] = added
    return counts


def _interval_count(rows, start, end, resource, evidence):
    matches = [r for r in rows if r.get('resource')==resource and r.get('evidence') in evidence
               and r.get('source') and utc(r['start_utc'])==start and utc(r['end_utc'])==end]
    if len(matches)>1:
        raise ValueError('Ambiguous duplicate demand/capacity interval; keep one applicable revision')
    if not matches:
        return None
    count = float(matches[0]['flights_per_interval'])
    if count < 0 or not count.is_integer():
        raise ValueError('Demand/capacity interval counts must be non-negative integers')
    return int(count)


def analyze_case(spec, root=DEFAULT_ROOT, *, sample_interval_s=30, run_pipeline=True):
    if type(sample_interval_s) is not int or not 15 <= sample_interval_s <= 300:
        raise ValueError('Sample interval must be an integer from 15 to 300 seconds')
    folder = Path(root) / spec['id']
    start, end = utc(spec['local_start']), utc(spec['local_end'])
    if end <= start:
        raise ValueError('Case end must follow its start')
    coverage_path = folder / 'coverage.json'
    coverage = json.loads(coverage_path.read_text(encoding='utf-8')) if coverage_path.exists() else {}
    dataset = dataset_for_case(folder)
    config = replace(configure_profile(ASTRAConfig(), 'tsn_tma'), prediction_horizons_min=[1,2,5],
        max_prediction_horizon_min=5, terminal_prediction_step_s=60, resolution_max_tracks_per_cycle=1)
    volume = config.assessment_volume
    points = {} if dataset is None else {cs:[p for p in ps if start.timestamp() <= p.epoch_s < end.timestamp()]
                                         for cs,ps in dataset.points.items()}
    active_ids = [cs for cs,ps in points.items() if any(p.state for p in ps)]
    errors = [dict(callsign=cs, **row) for cs in active_ids for row in forecast_errors(points[cs])]
    frames = []
    if active_ids:
        connector = AirNavReplayConnector(dataset, start_epoch_s=start.timestamp(), end_epoch_s=end.timestamp())
        pipeline = Pipeline(config) if run_pipeline else None
        for t in range(0, int((end-start).total_seconds()), sample_interval_s):
            snapshot, provenance = connector.frame_at(t)
            terminal = [ac for ac in snapshot if volume.contains(ac)]
            upstream = [ac for ac in snapshot if haversine_distance_nm(volume.center_lat,volume.center_lon,ac.lat,ac.lon)<=120]
            result = pipeline.run_cycle(snapshot) if pipeline else None
            frames.append(dict(time_s=t, utc=(start+timedelta(seconds=t)).isoformat(),
                aircraft=[asdict(ac) for ac in snapshot], provenance=provenance,
                usable_aircraft=len(snapshot), tma_aircraft=len(terminal), upstream_aircraft=len(upstream),
                current_complexity=max((r.complexity_score for r in result.regions_by_horizon.get(0,[])),default=0) if result and len(snapshot) else None))
    weather = []
    for row in _read_csv(folder / 'weather.csv'):
        if row['report_type'] in ('METAR','SPECI') and row.get('observation_utc'):
            stamp = utc(row['observation_utc'])
            if start <= stamp < end:
                weather.append(row)
        elif row['report_type'] == 'TAF' and row.get('valid_from_utc') and row.get('valid_to_utc'):
            if utc(row['valid_from_utc']) < end and utc(row['valid_to_utc']) > start:
                weather.append(row)
    observations = [r for r in weather if r['report_type'] in ('METAR','SPECI')]
    fpl = _read_csv(folder / 'fpl.csv')
    flights = _read_csv(folder / 'flights.csv')
    for name in ('fpl.csv','flights.csv','capacity.csv','demand.csv','measures.csv','ctot.csv'):
        for row in _read_csv(folder/name):
            for key,value in row.items():
                if key.endswith('_utc') and value:
                    utc(value)  # Reject ambiguous naive timestamps, even in supplemental data.
    # A raw EOBT or scheduled gate arrival is never substituted for a runway event.
    missing = []
    if not coverage.get('complete_airport_traffic'):
        missing.append('Danh sách arrival/departure đầy đủ, gồm delayed/cancelled/diverted')
    if not fpl or not coverage.get('complete_fpl'):
        missing.append('FPL đầy đủ trong khung giờ: EOBT, EET, Item 15 và phiên bản')
    if not observations or not coverage.get('weather_complete'):
        missing.append('METAR/SPECI và TAF đầy đủ, đặc biệt phần cuối khung giờ')
    if not _read_csv(folder / 'capacity.csv') or not coverage.get('declared_capacity_verified'):
        missing.append('Declared capacity theo thời gian; không suy từ throughput quan trắc')
    if not _read_csv(folder / 'measures.csv') or not _read_csv(folder / 'ctot.csv'):
        missing.append('ATFM measures / CTOT có timezone và revision history để đối chiếu')
    available_times = [p.epoch_s for ps in points.values() for p in ps]
    last_sample = datetime.fromtimestamp(max(available_times),timezone.utc).isoformat() if available_times else None
    summaries = []
    for horizon in (30,60,120,300):
        selected = [r for r in errors if r['requested_horizon_s']==horizon]
        summaries.append(dict(horizon_s=horizon, matched_pairs=len(selected),
            mean_horizontal_nm=statistics.mean(r['horizontal_error_nm'] for r in selected) if selected else None,
            mean_altitude_ft=statistics.mean(r['altitude_error_ft'] for r in selected) if selected else None))
    bins = []
    demand_rows = _read_csv(folder/'demand.csv')
    capacity_rows = _read_csv(folder/'capacity.csv')
    resource = coverage.get('analysis_resource','VVTS_ARRIVAL_RUNWAY')
    if resource not in ('VVTS_ARRIVAL_RUNWAY','VVTS_DEPARTURE_RUNWAY','VVTS_RUNWAY_TOTAL'):
        raise ValueError('Specify the runway resource used for demand/capacity comparison')
    actual_events = set()
    for row in flights:
        for key,direction,airport_key in [('actual_landing_utc','arrival','ades'),('actual_takeoff_utc','departure','adep')]:
            if row.get(key) and row.get(airport_key)=='VVTS':
                actual_events.add((row.get('callsign') or row['flight_id'],direction,utc(row[key])))
    if dataset:
        for cs,row in dataset.metadata.items():
            for key,direction,airport_key in [('actualLanding','arrival','arrAirportIcao'),('actualTakeoff','departure','depAirportIcao')]:
                if row.get(key) and row.get(airport_key)=='VVTS':
                    actual_events.add((cs,direction,utc(row[key])))
    for index in range(int((end-start).total_seconds())//900):
        subset = [f for f in frames if index*900 <= f['time_s'] < (index+1)*900]
        have_data = [f for f in subset if f['usable_aircraft']]
        bin_start,bin_end = start+timedelta(minutes=15*index),start+timedelta(minutes=15*(index+1))
        planned = _interval_count(demand_rows,bin_start,bin_end,resource,('fpl','observed')) if coverage.get('planned_demand_complete') else None
        declared = _interval_count(capacity_rows,bin_start,bin_end,resource,('declared',)) if coverage.get('declared_capacity_verified') else None
        direction = None if resource=='VVTS_RUNWAY_TOTAL' else 'arrival' if resource=='VVTS_ARRIVAL_RUNWAY' else 'departure'
        actual = sum(bin_start <= stamp < bin_end and (direction is None or direct==direction)
                     for _,direct,stamp in actual_events) if coverage.get('complete_airport_traffic') else None
        bins.append(dict(start_utc=bin_start.isoformat(),
            sampled_frames_with_data=len(have_data), sampled_frames=len(subset),
            peak_tracked_subset=max((f['usable_aircraft'] for f in have_data),default=None),
            planned_demand=planned, observed_airport_throughput=actual, declared_capacity=declared))
    source_path = folder / 'sources.json'
    unverified_path = folder / 'ctot_unverified.json'
    unverified = json.loads(unverified_path.read_text(encoding='utf-8')) if unverified_path.exists() else None
    comparisons = [b for b in bins if b['planned_demand'] is not None and b['declared_capacity'] is not None]
    return dict(**spec, start_utc=start.isoformat(), end_utc=end.isoformat(), status='partial' if active_ids else 'missing',
        condition_verified=bool(observations and any('TSRA' in re.split(r'\s(?:TEMPO|BECMG|RMK)\s',r['raw'])[0] for r in observations)) if spec['id']=='bad_weather' else None,
        demand_exceeds_capacity=(True if any(b['planned_demand']>b['declared_capacity'] for b in comparisons)
            else False if comparisons and len(comparisons)==len(bins) else None),
        demand_capacity_resource=resource,
        recorded_flights=len(active_ids), source_samples_in_window=len(available_times), last_sample_utc=last_sample,
        frames=frames, forecast_summary=summaries, forecast_errors=errors, bins_15min=bins,
        weather=weather, fpl_records=len(fpl), flight_list_records=len(flights), missing_inputs=missing,
        coverage=coverage, source_quality=dataset.summary() if dataset else None,
        source=json.loads(source_path.read_text(encoding='utf-8')) if source_path.exists() else None,
        unverified_ctot=dict(rows=len(unverified.get('rows',[])),timezone=unverified.get('timezone'),
            usable_for_compliance=False) if unverified else None,
        assessment=dict(center_lat=volume.center_lat,center_lon=volume.center_lon,radius_nm=volume.radius_nm,
            lower_ft=volume.lower_altitude_ft,upper_ft=volume.upper_altitude_ft,upstream_context_radius_nm=120),
        max_complexity=max((f['current_complexity'] for f in frames if f['current_complexity'] is not None),default=None))


def run_suite(root=DEFAULT_ROOT, *, sample_interval_s=30, run_pipeline=True):
    return dict(schema_version=1, airport='VVTS', source_request='D:/VVTS_ATFM_data_request.pdf',
        evidence='Observed subset; incomplete cases remain missing. No synthetic substitute traffic.',
        cases=[analyze_case(w,root,sample_interval_s=sample_interval_s,run_pipeline=run_pipeline) for w in WINDOWS],
        sample_interval_s=sample_interval_s, pipeline_enabled=run_pipeline,
        limitations=['Danh sách track mẫu không đại diện toàn bộ planned demand hay airport throughput.',
            'Chưa có FPL/declared capacity đầy đủ: chưa xác nhận Demand > Capacity hoặc định lượng lợi ích ATFM thực tế.',
            'TMA dùng profile nghiên cứu 40 NM hiện có; track trong vòng 120 NM được giữ làm bối cảnh upstream.',
            'Khung Tết 10:00–12:00 đã được người dùng xác nhận; nhãn cao điểm còn cần dữ liệu xác minh.',
            'Không áp dụng clearance. Không suy CTOT, holding clearance, runway closure hay ATFM delay từ ADS-B.',
            'Thời tiết quan trắc và TAF được tách riêng. Không ngoại suy thời tiết tới phần chưa có báo cáo.'])


def export_suite(result, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    _write_csv(out_dir/'prediction_errors.csv', ['case_id','callsign','source_utc','truth_utc',
        'requested_horizon_s','actual_horizon_s','horizontal_error_nm','altitude_error_ft'],
        [dict(case_id=c['id'],**row) for c in result['cases'] for row in c['forecast_errors']])
    _write_csv(out_dir/'coverage_15min.csv', ['case_id','start_utc','sampled_frames_with_data','sampled_frames',
        'peak_tracked_subset','planned_demand','observed_airport_throughput','declared_capacity'],
        [dict(case_id=c['id'],**row) for c in result['cases'] for row in c['bins_15min']])
    lines = ['# Ba kịch bản VVTS theo đơn xin dữ liệu', '',
        '| Kịch bản | Giờ Việt Nam | Tình trạng | Flights có track | Samples trong khung |',
        '|---|---|---|---:|---:|']
    for c in result['cases']:
        lines.append(f"| {c['label']} | {c['local_start']} – {c['local_end']} | {c['status']} | {c['recorded_flights']} | {c['source_samples_in_window']} |")
    for c in result['cases']:
        lines.extend(['',f"## {c['label']}",f"Mẫu track cuối trong khung: {c['last_sample_utc'] or 'Chưa có'}.",'',
                      *[f'- Cần bổ sung: {x}' for x in c['missing_inputs']]])
    lines.extend(['','## Giới hạn','',*[f'- {x}' for x in result['limitations']]])
    (out_dir/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
