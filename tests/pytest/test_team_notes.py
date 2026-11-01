import pytest
from astra.airspace import geo_asset, load_profile
from astra.airspace_zones import zone_asset
from astra.utils.geodesy import haversine_distance_nm


def test_team_zone_geometry():
    polygon = zone_asset('VVP4')['features'][0]['geometry']['coordinates'][0]
    assert len(polygon) == 5 and polygon[0] == polygon[-1]
    assert polygon[0] == pytest.approx([106+38/60+20/3600, 10+47/60+50/3600])
    zone = zone_asset('VVR36')['features'][0]
    lon, lat = zone['properties']['center']
    for x,y in zone['geometry']['coordinates'][0]:
        assert haversine_distance_nm(lat,lon,y,x)*1.852 == pytest.approx(15, abs=1e-7)


def test_layer_groups_and_outline_only_boundary():
    layers = {x['id']: x for x in geo_asset('tsn_tma','manifest.json')['layers']}
    assert not layers['firs']['style']['fill']
    assert not layers['firs'].get('label_field')
    for ident in load_profile('tsn_tma')['procedure_data']:
        line, points = layers[f'procedure_{ident}_route'], layers[f'procedure_{ident}_fixes']
        assert line['toggle_group'] == points['toggle_group']
        assert not line['default_visible'] and not points['default_visible']
    area = {f['properties']['name'] for f in geo_asset('tsn_tma','waypoints.json')['features']}
    app = {f['properties']['name'] for f in geo_asset('tsn_tma','approach_fixes.json')['features']}
    assert not area & app
    assert {'BOMSU','SOKAN','TS424','TS426'} <= app

