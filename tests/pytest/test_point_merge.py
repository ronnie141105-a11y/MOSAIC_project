"""25R point-merge clearances, route display, and study speeds."""
import pytest

from astra.airspace import configure_profile, geo_asset, procedure_aircraft
from astra.dashboard.legacy_flask_app import create_app
from astra.dashboard.store import CycleStore
from astra.interface.state_reader import StateReader
from astra.point_merge import ARCS, MAX_VERTICAL_RATE_FPM
from astra.utils.config import ASTRAConfig


def mock_reader(step_s=10):
    config = configure_profile(ASTRAConfig(), 'tsn_tma')
    reader = StateReader.for_mock(config, sim_step_s=step_s)
    reader.connect()
    return config, reader


def test_clearance_shortens_arc_and_sequences_follower():
    _, reader = mock_reader()
    reader.create_aircraft(**procedure_aircraft('tsn_tma', 'BITIS2H', 'A', '25R', start_index=4))
    reader.create_aircraft(**procedure_aircraft('tsn_tma', 'BITIS2H', 'B', '25R', start_index=3))
    first = reader.point_merge_status('A')
    assert first['safe'] and first['merge_fix'] == 'SOKAN'
    assert not reader.point_merge_status('B')['available']
    reader.clear_point_merge('A')
    assert reader._connector._aircraft['A'].procedure_profile['legs'][0]['fix'] == 'SOKAN'
    reader.step_simulation(24)
    waiting = reader.point_merge_status('B')
    assert waiting['available'] and not waiting['safe']
    assert '20 NM required' in waiting['reason']
    with pytest.raises(ValueError, match='Hold on the arc'):
        reader.clear_point_merge('B')
    reader.step_simulation(3)
    second = reader.point_merge_status('B')
    assert second['safe'] and second['next_arc_fix'] == 'RUNSI'
    reader.clear_point_merge('B')
    assert reader._connector._aircraft['B'].procedure_profile['legs'][0]['fix'] == 'SOKAN'


def test_clearance_requires_merge_altitude_and_web_api():
    config, reader = mock_reader()
    spec = procedure_aircraft('tsn_tma', 'BITIS2H', 'HIGH', '25R', start_index=4)
    spec['altitude_ft'] = 20000
    reader.create_aircraft(**spec)
    blocked = reader.point_merge_status('HIGH')
    assert blocked['available'] and not blocked['safe']
    assert '2,000 ft/min' in blocked['reason']
    app = create_app(CycleStore(), config, reader=reader)
    client = app.test_client()
    assert not client.get('/airport/point-merge/HIGH').get_json()['safe']
    response = client.post('/airport/point-merge/clearance', json={'callsign': 'HIGH'})
    assert response.status_code == 409
    assert MAX_VERTICAL_RATE_FPM == 2000


def test_fan_routes_and_restricted_zone_borders():
    arcs = geo_asset('tsn_tma', 'point_merge_arcs.json')['features']
    spokes = geo_asset('tsn_tma', 'point_merge_spokes.json')['features']
    assert len(arcs) == len(ARCS) == 4
    assert len(spokes) == sum(map(len, ARCS.values()))
    assert {f['properties']['merge_fix'] for f in spokes} == {'SOKAN', 'BOMSU'}
    manifest = geo_asset('tsn_tma', 'manifest.json')['layers']
    by_id = {item['id']: item for item in manifest}
    assert all(by_id[name]['style']['fill'] is None for name in ('VVP4', 'VVR19', 'VVR36'))
    assert all(by_id[name]['default_visible'] for name in ('point_merge_arcs', 'point_merge_spokes'))
    star = procedure_aircraft('tsn_tma', 'BITIS2H', 'SPD', '25R')
    sid = procedure_aircraft('tsn_tma', 'SAPEN2D', 'SID', '25L')
    assert star['speed_kt'] == 240
    assert sid['speed_kt'] >= 200
    assert any(230 <= leg['nominal_speed_kt'] <= 250 for leg in star['procedure_profile']['legs'] if leg['phase'] == 'star')