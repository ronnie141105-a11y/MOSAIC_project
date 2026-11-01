import csv
from datetime import timedelta
import json

import pytest
from flask import Flask

from astra.dashboard.vvts_case_routes import build_vvts_case_blueprint
from astra.studies.vvts_cases import WINDOWS, TABLES, analyze_case, dataset_for_case, export_suite, init_package, import_noaa_weather, run_suite, utc
from scripts.run_vvts_cases import import_track


def recording(root, case='bad_weather', callsign='TEST01', start='2026-10-07T10:00:00Z'):
    t=utc(start)
    flight=dict(callsign=callsign,aircraftType='A320',depAirportIcao='VVNB',arrAirportIcao='VVTS',
        positions=[dict(timestamp=(t+timedelta(seconds=i*20)).isoformat(),latitude=10.9,longitude=106.9+i*.01,
                        altitude=6000-i*200,groundSpeed=200,heading=90,verticalRate=None) for i in range(4)])
    (root/case/'observations.json').write_text(json.dumps(dict(success=True,flights=[flight])))
    return flight


def write_rows(path, rows):
    with path.open('w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.DictWriter(stream,fieldnames=TABLES[path.name]);writer.writeheader();writer.writerows(rows)


def test_exact_windows_follow_pdf_and_confirmed_holiday_hours():
    assert [(utc(w['local_start']).strftime('%Y-%m-%dT%H:%M'),utc(w['local_end']).strftime('%H:%M')) for w in WINDOWS]==[
        ('2026-10-07T10:00','12:00'),('2026-10-08T02:00','04:00'),('2026-02-22T03:00','05:00')]
    with pytest.raises(ValueError,match='timezone'):
        utc('2026-10-07T10:00:00')


def test_missing_cases_keep_unavailable_demand_capacity_and_errors_null(tmp_path):
    root=init_package(tmp_path)
    result=run_suite(root,run_pipeline=False)
    assert all(c['status']=='missing' and not c['frames'] for c in result['cases'])
    assert all(b['planned_demand'] is None and b['declared_capacity'] is None and b['observed_airport_throughput'] is None
               for c in result['cases'] for b in c['bins_15min'])
    assert all(r['mean_horizontal_nm'] is None for c in result['cases'] for r in c['forecast_summary'])
    export_suite(result,tmp_path/'out')
    assert json.loads((tmp_path/'out/report.json').read_text(encoding='utf-8'))['cases'][2]['demand_exceeds_capacity'] is None


def test_track_without_vertical_rate_bootstraps_from_past_altitude(tmp_path):
    root=init_package(tmp_path);recording(root)
    dataset=dataset_for_case(root/'bad_weather')
    assert dataset.points['TEST01'][0].state is None
    point=dataset.points['TEST01'][1]
    assert point.state.vertical_speed_fpm==-600
    assert point.field_sources['verticalRate']=='derived'
    assert dataset.point_at('TEST01',dataset.points['TEST01'][0].epoch_s+10) is None


def test_out_of_window_sample_is_not_a_nominal_case(tmp_path):
    root=init_package(tmp_path);recording(root,case='nominal',start='2026-10-08T00:00:00Z')
    case=analyze_case(WINDOWS[1],root,run_pipeline=False)
    assert case['recorded_flights']==0 and case['source_samples_in_window']==0 and case['status']=='missing'


def test_recording_end_and_long_gaps_are_not_extended_to_case_end(tmp_path):
    root=init_package(tmp_path);recording(root)
    case=analyze_case(WINDOWS[0],root,run_pipeline=False)
    assert case['recorded_flights']==1
    assert case['frames'][1]['usable_aircraft']==1
    assert case['frames'][4]['usable_aircraft']==0
    assert case['frames'][4]['current_complexity'] is None
    assert case['frames'][-1]['usable_aircraft']==0
    assert case['bins_15min'][1]['peak_tracked_subset'] is None


def test_noaa_import_uses_full_date_not_day_of_month_and_preserves_revisions(tmp_path):
    root=init_package(tmp_path/'inputs')
    path=tmp_path/'weather.json'
    rows=[dict(icaoId='VVTS',metarType='METAR',obsTime=int(utc(t).timestamp()),rawOb=raw) for t,raw in [
        ('2026-10-07T10:00Z','METAR OBSERVED'),('2026-09-07T10:00Z','WRONG MONTH'),('2026-10-07T12:00Z','END BOUNDARY')]]
    path.write_text(json.dumps(dict(source_url='https://aviationweather.gov/api/data/metar',observations=rows)))
    assert import_noaa_weather(path,root)['bad_weather']==1
    assert import_noaa_weather(path,root)['bad_weather']==0
    rows[0]['rawOb']='METAR REVISED';path.write_text(json.dumps(dict(source_url='NOAA',observations=rows)))
    assert import_noaa_weather(path,root)['bad_weather']==1
    with (root/'bad_weather/weather.csv').open(encoding='utf-8-sig') as f:
        assert {r['raw'] for r in csv.DictReader(f)}=={'METAR OBSERVED','METAR REVISED'}


def test_fr24_import_validates_epoch_and_utc_and_derives_missing_vs(tmp_path):
    root=init_package(tmp_path/'inputs');path=tmp_path/'fr24.csv'
    base=utc('2026-02-22T03:00:00Z')
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['Timestamp','UTC','Callsign','Position','Altitude','Speed','Direction']);w.writeheader()
        for i in range(2):
            t=base+timedelta(seconds=20*i)
            w.writerow(dict(Timestamp=int(t.timestamp()),UTC=t.isoformat(),Callsign='TEST01',Position='10.9,106.9',Altitude=6000-i*100,Speed=200,Direction=90))
    assert import_track(path,root/'holiday_peak',callsign='TEST01',aircraft_type='A320',ades='VVTS')==2
    assert import_track(path,root/'holiday_peak',callsign='TEST01',aircraft_type='A320',ades='VVTS')==0
    assert dataset_for_case(root/'holiday_peak').points['TEST01'][1].state.vertical_speed_fpm==-300
    text=path.read_text();path.write_text(text.replace(base.isoformat(),'2026-02-22T04:00:00+00:00'))
    with pytest.raises(ValueError,match='disagree'):
        import_track(path,root/'holiday_peak',callsign='TEST01',aircraft_type='A320')


def test_imported_csv_and_archived_flights_are_combined_not_replaced(tmp_path):
    root=init_package(tmp_path);recording(root,callsign='OLD01')
    rows=[dict(flight_id='NEW01',callsign='NEW01',aircraft_type='A321',adep='VVNB',ades='VVTS',
        time_utc=f'2026-10-07T10:00:{second:02}Z',lat=10.9,lon=106.9,altitude_ft=7000,ground_speed_kt=200,heading_deg=90,
        vertical_speed_fpm=0,on_ground='',source='test') for second in (0,20)]
    write_rows(root/'bad_weather/tracks.csv',rows)
    assert set(dataset_for_case(root/'bad_weather').points)=={'OLD01','NEW01'}


def test_measured_throughput_is_not_capacity_and_assumed_capacity_stays_unverified(tmp_path):
    root=init_package(tmp_path);recording(root)
    coverage=root/'bad_weather/coverage.json';data=json.loads(coverage.read_text())
    data.update(complete_airport_traffic=True,planned_demand_complete=True,declared_capacity_verified=True)
    coverage.write_text(json.dumps(data))
    write_rows(root/'bad_weather/flights.csv',[dict(callsign='TEST01',ades='VVTS',actual_landing_utc='2026-10-07T10:05:00Z',actual_inblock_utc='2026-10-07T10:20:00Z',source='reported')])
    interval=dict(start_utc='2026-10-07T10:00:00Z',end_utc='2026-10-07T10:15:00Z',resource='VVTS_ARRIVAL_RUNWAY',source='official')
    write_rows(root/'bad_weather/demand.csv',[dict(**interval,flights_per_interval=5,evidence='fpl')])
    write_rows(root/'bad_weather/capacity.csv',[dict(**interval,flights_per_interval=3,evidence='assumed')])
    case=analyze_case(WINDOWS[0],root,run_pipeline=False)
    assert case['bins_15min'][0]['observed_airport_throughput']==1
    assert case['bins_15min'][1]['observed_airport_throughput']==0 # Gate inblock is not a landing.
    assert case['bins_15min'][0]['declared_capacity'] is None and case['demand_exceeds_capacity'] is None
    write_rows(root/'bad_weather/capacity.csv',[dict(**interval,flights_per_interval=3,evidence='declared')])
    assert analyze_case(WINDOWS[0],root,run_pipeline=False)['demand_exceeds_capacity'] is True


def test_cases_routes_only_export_report_assets(tmp_path):
    app=Flask(__name__);app.register_blueprint(build_vvts_case_blueprint(tmp_path))
    client=app.test_client();assert client.get('/api/vvts-cases/results').status_code==404
    (tmp_path/'report.json').write_text('{"schema_version":1}')
    assert client.get('/api/vvts-cases/results').json=={'schema_version':1}
    assert client.get('/api/vvts-cases/export/report.json').status_code==200
    assert client.get('/api/vvts-cases/export/secret.json').status_code==404
