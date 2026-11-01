import math
import pytest
from astra.airspace import geo_asset,load_profile,procedure_aircraft
from astra.airspace_zones import zone_asset
from astra.utils.geodesy import haversine_distance_nm

DATA=load_profile('tsn_tma')

def test_fixed_layers_and_ils_group():
    layers={l['id']:l for l in geo_asset('tsn_tma','manifest.json')['layers']}
    for name,visible in dict(centre_firs=False,firs=True,radar_range=True,airways=True,navaids=True,runways=True).items():
        assert layers[name]['toggleable'] is False
        assert layers[name]['default_visible'] is visible
    assert layers['approach']['toggle_group']==layers['approach_fixes']['toggle_group']=='ils_25r'
    assert len({layers[n]['style']['fill'] for n in ['VVP4','VVR19','VVR36']})==1

@pytest.mark.parametrize('ident',list(DATA['procedure_data']))
def test_each_procedure_owns_its_display_fixes_and_routes(ident):
    p=DATA['procedure_data'][ident]
    expected=set(p['display_fixes'])
    for t in p['transitions'].values():expected.update(t['fixes'])
    shown=geo_asset('tsn_tma',f'procedure_{ident}_fixes.json')['features']
    assert {f['properties']['name'] for f in shown}==expected
    lines=geo_asset('tsn_tma',f'procedure_{ident}_route.json')['features']
    assert len(lines)==1+len(p['transitions'])
    assert all(f['properties']['name'].startswith(ident) for f in lines)

@pytest.mark.parametrize('ident,transition',[(p['id'],t) for p in DATA['procedure_data'].values() for t in p['transitions']])
def test_transition_connects_to_procedure(ident,transition):
    spec=procedure_aircraft('tsn_tma',ident,'TEST',transition=transition)
    p=DATA['procedure_data'][ident];fixes=p['transitions'][transition]['fixes']
    legs=spec['procedure_profile']['legs']
    if p['kind']=='star':
        point=DATA['waypoint_data'][fixes[0]]
        assert (spec['lat'],spec['lon'])==(point['lat'],point['lon'])
        assert [l['fix'] for l in legs[:len(fixes)-1]]==fixes[1:]
        assert legs[-1]['fix']=='TD25R'
    else:assert [l['fix'] for l in legs[-len(fixes):]]==fixes
    assert all(math.isfinite(x) for pos in spec['route_waypoints'] for x in pos)

def test_rf_samples_follow_chart_radius_and_are_not_shown_as_fixes():
    p=DATA['procedure_data']['ANTRI2F'];c=DATA['waypoint_data']['TSC03']
    samples=[l['fix'] for l in p['legs'] if l['fix'].startswith('_')]
    assert len(samples)>40
    for n in samples:
        point=DATA['waypoint_data'][n]
        assert haversine_distance_nm(c['lat'],c['lon'],point['lat'],point['lon'])*1.852==pytest.approx(5.9,abs=.1)
    assert not set(samples)&set(p['display_fixes'])

def test_vvr19_is_explicitly_provisional_closed_and_within_arc():
    f=zone_asset('VVR19')['features'][0];ring=f['geometry']['coordinates'][0];c=DATA['center']
    assert 'provisional' in f['properties']['geometry_status']
    assert len(f['properties']['assumptions'])==4
    assert len(ring)>50 and ring[0]==ring[-1]
    assert all(haversine_distance_nm(c['lat'],c['lon'],lat,lon)*1.852<=75.01 for lon,lat in ring)
