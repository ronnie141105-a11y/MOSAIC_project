"""Validate adapted source populations, route coverage and shared replay."""
from collections import Counter
from copy import deepcopy
import csv
from datetime import datetime
import hashlib
import json
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from astra.airspace import configure_profile, load_profile
from astra.centre import distance_nm
from astra.dashboard.legacy_flask_app import create_app
from astra.dashboard.store import CycleStore
from astra.interface.state_reader import StateReader
from astra.optimization.video_cases import VideoCaseEvaluator
from astra.studies.workbook_cases import CASES, ROOT, build_case, read_workbook
from astra.studies.vvts_cases import dataset_for_case
from astra.utils.config import ASTRAConfig
from astra.utils.geodesy import haversine_distance_nm


@pytest.fixture(scope='module')
def source():
    return read_workbook(ROOT/'evidence/VVTS_scenarios.xlsx')


@pytest.fixture
def runtime(tmp_path):
    config = configure_profile(ASTRAConfig(), 'tsn_tma')
    reader = StateReader.for_mock(config, sim_step_s=20)
    reader.connect()
    app = create_app(CycleStore(), config, reader, scenarios_dir=str(tmp_path/'builder'))
    return reader, app.test_client(), reader._connector.case_replay


@pytest.mark.parametrize('case_id', CASES)
def test_source_population_and_assumptions_are_traceable(source, case_id):
    spec = CASES[case_id]
    folder = ROOT/case_id
    manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    original = source[spec['sheet']]
    assert json.loads((folder/'source_rows.json').read_text(encoding='utf-8')) == original
    assert len(original) == spec.get('source_arrivals',spec['arrivals']) + spec.get('source_departures',spec['departures'])
    used={f['source_callsign'] for f in manifest['flights'] if not f['synthetic_extension']}
    assert Counter(r['WakeCategory'] for r in original if r['Callsign'] in used) == Counter(f['wake_category'] for f in manifest['flights'] if not f['synthetic_extension'])
    assert manifest['source']['source_rows_used']==len(used)
    assert manifest['source']['sha256'] == hashlib.sha256((ROOT/'evidence/VVTS_scenarios.xlsx').read_bytes()).hexdigest()
    by_id = {r['Callsign']: r for r in original}
    for flight in manifest['flights']:
        assert flight['source_row'] == by_id[flight['source_callsign']]['source_row']
        assert flight['source_route'] == by_id[flight['source_callsign']]['OptimizedRoute']
        assert flight['ground_delay_eligible']==(flight['direction']=='departure')
        assert (datetime.fromisoformat(flight['origin_takeoff_utc']) > datetime.fromisoformat(manifest['planning_utc']))==(flight['direction']=='departure')
        assert flight['adep'] != 'UNKNOWN' and flight['ades'] != 'UNKNOWN'
        assert not flight['actual_landing_verified'] and not flight['actual_takeoff_verified']
    with (folder/'flights.csv').open(encoding='utf-8', newline='') as stream:
        assert all(not r['actual_takeoff_utc'] and not r['actual_landing_utc'] for r in csv.DictReader(stream))
    with (folder/'demand.csv').open(encoding='utf-8', newline='') as stream:
        assert len(list(csv.DictReader(stream))) == len(manifest['flights'])


@pytest.mark.parametrize('case_id', CASES)
def test_complete_native_tracks_cover_transfer_and_modelled_runway(case_id):
    folder = ROOT/case_id
    manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    dataset = dataset_for_case(folder)
    points = load_profile('tsn_tma')['waypoint_data']
    assert dataset.quality['excluded_incomplete'] == 0
    assert dataset.quality['duplicate_timestamp'] == 0
    for flight in manifest['flights']:
        track = dataset.points[flight['callsign']]
        assert all(p.state is not None for p in track)
        assert all(a.epoch_s < b.epoch_s for a, b in zip(track, track[1:]))
        assert all(-3500.001<=p.state.vertical_speed_fpm<=2000.001 for p in track)
        assert all(haversine_distance_nm(a.lat, a.lon, b.lat, b.lon)
                   <= 500*(b.epoch_s-a.epoch_s)/3600+.001 for a, b in zip(track, track[1:]))
        target = datetime.fromisoformat(flight['planned_event_utc']).timestamp()
        if flight['direction'] == 'arrival':
            assert track[0].epoch_s==datetime.fromisoformat(manifest['local_start']).timestamp()
            assert track[0].state.ground_speed_kt>0
            assert flight['approach_transfer_fix']!='VVTS_40NM'
            assert track[-1].epoch_s == target
            assert track[-1].state.altitude_ft < 40
            assert haversine_distance_nm(track[-1].lat, track[-1].lon, points['RW25R']['lat'], points['RW25R']['lon']) < .2
        else:
            assert track[0].epoch_s == target
            assert distance_nm(track[-1].lat, track[-1].lon) > 40
            # Native initial climb has already moved one 205 kt, 1 s tick.
            assert haversine_distance_nm(track[0].lat, track[0].lon, points['RW25L']['lat'], points['RW25L']['lon']) == pytest.approx(205/3600,abs=.001)
            assert track[0].state.altitude_ft == pytest.approx(2000/60)
    summary = json.loads((folder/'summary.json').read_text())
    audit = summary['separation_audit']
    assert audit['violating_pairs'] == 0
    assert summary['surface_audit']['violating_pairs']==0
    assert summary['all_arrivals_visible_at_start'] and summary['all_arrivals_park_at_stands']
    assert summary['initial_departure_states'].get('PARKED',0)>=manifest['counts']['departures']-2
    assert summary['stream_audit']['maximum_airborne_holding_aircraft']==0
    assert summary['stream_audit']['centre_horizontal_conflict_pairs']==[]


@pytest.mark.parametrize('case_id', CASES)
def test_replay_all_flights_without_extending_routes_again(runtime, case_id):
    reader, client, replay = runtime
    response = client.post('/api/case-scenarios/load', json={'case_id': case_id, 'enroute': False})
    assert response.status_code == 200, response.json
    state = response.json['replay']
    assert state['study_window_s'] == 10800
    assert state['enroute'] and state['study_offset_s'] == 0
    assert state['ground_tracks']
    assert not reader.is_simulation_running()
    assert not replay.replay.dataset.quality['synthetic_fir_positions']
    expected_start = replay.replay.dataset.start_epoch_s
    assert replay.replay.start_epoch_s == expected_start
    seen, areas = set(), set()
    for now in range(0, int(replay.duration_s)+21, 20):
        reader._connector.restore_clock(now)
        replay.tick()
        for ac in reader.list_aircraft():
            seen.add(ac['callsign'])
            areas.add('CENTRE' if distance_nm(ac['lat'], ac['lon']) > 40 else 'APPROACH')
    assert seen == set(replay.metadata)
    assert areas == {'CENTRE', 'APPROACH'}
    assert replay.status()['completed'] == len(seen)
    assert not reader.list_aircraft()
    assert not reader.is_simulation_running()
    assert client.post('/api/case-scenarios/load', json={'case_id': case_id, 'enroute': True}).status_code == 200
    assert replay.replay.dataset.start_epoch_s == expected_start
    # Legacy terminal variants still cannot silently substitute for full-route plans.
    assert client.post('/api/case-scenarios/load', json={'case_id': case_id, 'method': 'GA_MIXED'}).status_code == 400
    assert replay.case_id == case_id
    with pytest.raises(ValueError, match='two active video cases'):
        VideoCaseEvaluator(case_id)


def test_import_rejects_missing_population_and_unsupported_types(source):
    records = deepcopy(source['Low_20'])
    with pytest.raises(ValueError, match='population'):
        build_case('workbook_low_20', records[:-1], 'test')
    records[0]['AircraftType'] = 'UNKNOWN_TYPE'
    with pytest.raises(ValueError, match='Unsupported'):
        build_case('workbook_low_20', records, 'test')


def test_workbook_formulas_are_not_executed_or_silently_used(tmp_path):
    target = tmp_path/'formula.xlsx'
    with ZipFile(ROOT/'evidence/VVTS_scenarios.xlsx') as source_zip, ZipFile(target, 'w') as output:
        for item in source_zip.infolist():
            data = source_zip.read(item.filename)
            if item.filename == 'xl/worksheets/sheet2.xml':
                tree = ET.fromstring(data)
                namespace = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
                cell = tree.find(f'.//{{{namespace}}}c')
                ET.SubElement(cell, f'{{{namespace}}}f').text = '1+1'
                data = ET.tostring(tree)
            output.writestr(item, data)
    with pytest.raises(ValueError, match='formulas are not scenario inputs'):
        read_workbook(target)
