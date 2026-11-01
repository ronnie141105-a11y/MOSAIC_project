import pytest
from astra.airspace import configure_profile
from astra.utils.config import ASTRAConfig
from astra.interface.state_reader import StateReader
from astra.dashboard.legacy_flask_app import create_app
from astra.dashboard.store import CycleStore

@pytest.mark.parametrize('profile',['tsn_tma','hcm_fir'])
def test_random_spawn_adds_unique_routed_aircraft_without_reset(profile,tmp_path):
    config=configure_profile(ASTRAConfig(),profile)
    reader=StateReader.for_mock(config,sim_step_s=1);reader.connect()
    app=create_app(CycleStore(),config,reader,str(tmp_path))
    client=app.test_client();before={a['callsign'] for a in reader.list_aircraft()}
    kinds=['arrival','departure','mixed'] if profile=='tsn_tma' else ['mixed']*3
    created=set()
    for kind in kinds:
        response=client.post('/scenario/random-aircraft',json={'kind':kind})
        assert response.status_code==200,response.json
        callsign=response.json['callsign'];assert callsign not in created|before
        created.add(callsign);assert reader.get_route(callsign)
        if kind!='mixed':
            p=reader.get_flight_profile(callsign)
            assert p['runway']==('25R' if kind=='arrival' else '25L')
    assert {a['callsign'] for a in reader.list_aircraft()}==before|created
    assert client.post('/scenario/random-aircraft',json={'kind':'invalid'}).status_code==400
