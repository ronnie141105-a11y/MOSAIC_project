"""Centre's arrival routing and display must respect the handoff endpoint."""
import pytest

from astra.airspace import load_profile,procedure_aircraft,geo_asset
from astra.centre import connect_procedure,distance_nm,outward_route
from astra.dashboard.centre_layers import arrival_feeders,star_route,transfer_waypoints,ROUTE_STYLE
from tests.pytest.test_centre_connection import runtime


@pytest.mark.parametrize('procedure',['VICAL3H','VICAL3J'])
@pytest.mark.parametrize('transition',[None,'NIXIV'])
def test_arrivals_join_vical_directly_from_nixiv(procedure,transition):
    original=procedure_aircraft('tsn_tma',procedure,'ARRTEST',transition=transition)
    linked=connect_procedure(original,300,220)
    names=[l['fix'] for l in linked['procedure_profile']['legs']]
    assert 'VICAL' in names and 'NIXIV' in names
    assert names[names.index('VICAL')-1]=='NIXIV'
    assert 'XOBAV' not in names
    assert linked['procedure_profile']['legs'][-len(original['procedure_profile']['legs']):]==original['procedure_profile']['legs']
    assert not linked['procedure_profile']['centre_join_connector_assumed']


def test_departure_keeps_xobav_nixiv_transition():
    original=procedure_aircraft('tsn_tma','XOBAV2D','DEPTEST',transition='NIXIV')
    linked=connect_procedure(original,300,220)
    before=original['procedure_profile']['legs'];after=linked['procedure_profile']['legs']
    assert after[:len(before)]==before
    names=[l['fix'] for l in after]
    assert names[names.index('XOBAV')+1]=='NIXIV'


@pytest.mark.parametrize('procedure',[p['id'] for p in load_profile('tsn_tma')['procedure_data'].values() if p['kind']=='star'])
def test_all_centre_star_geometry_stops_outside_tma(procedure):
    features=star_route(procedure)['features']
    assert features
    for feature in features:
        coords=feature['geometry']['coordinates']
        assert all(distance_nm(lat,lon)>=40-1e-6 for lon,lat in coords)
        if procedure.startswith('DALAP'):
            assert distance_nm(coords[-1][1],coords[-1][0])==pytest.approx(40,abs=1e-6)
    # The full Approach STAR still includes its merge fix.
    assert len(geo_asset('tsn_tma',f'procedure_{procedure}_route.json')['features'][0]['geometry']['coordinates'])>2


def test_named_arrival_handoff_is_the_last_display_point():
    profile=load_profile('tsn_tma')
    for procedure,gate in [('BITIS2H','BITIS'),('VICAL3H','VICAL'),('ELSAS2H','GOMIN')]:
        expected=[profile['waypoint_data'][gate]['lon'],profile['waypoint_data'][gate]['lat']]
        assert all(f['geometry']['coordinates'][-1]==expected for f in star_route(procedure)['features'])
    assert len(star_route('VICAL3H')['features'][0]['geometry']['coordinates'])==2


def test_centre_layers_keep_sid_and_highlight_both_units_transfer_fixes(tmp_path):
    _,_,client=runtime(tmp_path)
    manifest=client.get('/centre/geo/manifest.json').json
    for layer in manifest['layers']:
        if layer['kind']=='line' and layer['id'] not in ('coastlines','country_borders','runways'):
            assert layer['style']['dash']==[5,5]
        if layer['id'].startswith('procedure_'):
            assert load_profile('tsn_tma')['procedure_data'][layer['id'].split('_')[1]]['kind']=='sid'
    highlighted=next(l for l in manifest['layers'] if l['id']=='transfer_waypoints')
    assert highlighted['default_visible'] and highlighted['toggleable'] is False
    fixes={f['properties']['name'] for f in client.get('/centre/geo/transfer_waypoints.json').json['features']}
    assert {'BACHU','MISAN','ANTRI','LANHI','VICAL','XOBAV','BITIS','GOMIN'}.issubset(fixes)
    assert client.get('/centre/geo/procedure_XOBAV2D_route.json').json==geo_asset('tsn_tma','procedure_XOBAV2D_route.json')
    assert client.get('/centre/geo/procedure_VICAL3H_route.json').json==star_route('VICAL3H')
    assert client.get('/centre/geo/arrival_feeders.json').json==arrival_feeders()


def test_approach_and_centre_share_visible_transfer_fixes(tmp_path):
    _,_,client=runtime(tmp_path)
    layers=[]
    for endpoint in ('/centre/geo/manifest.json','/airspace/geo/manifest.json'):
        response=client.get(endpoint)
        assert response.status_code==200
        highlighted=[l for l in response.json['layers'] if l['id']=='transfer_waypoints']
        assert len(highlighted)==1
        layer=highlighted[0]
        assert layer['default_visible'] and layer['toggleable'] is False
        layers.append(layer)
    assert layers[0]['style']==layers[1]['style']
    centre=client.get('/centre/geo/transfer_waypoints.json')
    approach=client.get('/airspace/geo/transfer_waypoints.json')
    assert centre.status_code==approach.status_code==200
    assert centre.json==approach.json
    assert {'BACHU','MISAN','VICAL','XOBAV'}.issubset(
        f['properties']['name'] for f in approach.json['features'])
