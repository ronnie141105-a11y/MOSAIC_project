"""Approach continuity, Centre entry, and radar context regressions."""
import math
import pytest

from astra.airspace import configure_profile, load_profile, procedure_aircraft, geo_asset, feeder_aircraft
from astra.interface.state_reader import StateReader
from astra.interface.traffic_state import AircraftState
from astra.trajectory.procedure import advance_procedure
from astra.trajectory.route_engine import RouteAwareTrajectoryEngine
from astra.utils.config import ASTRAConfig
from astra.utils.geodesy import haversine_distance_nm


@pytest.mark.parametrize('star,entry',[('SAPEN2H','SOKAN'),('DALAP2J','BOMSU')])
def test_star_joins_approach_and_lands_without_stopping_at_iaf(star,entry):
    data=load_profile('tsn_tma')
    start=len(data['procedure_data'][star]['legs'])-1
    spec=procedure_aircraft('tsn_tma',star,'LAND','25R',start_index=start)
    profile=spec['procedure_profile'];route=spec['route_waypoints']
    assert profile['approach_id']=='ILS_W_25R'
    assert [leg['fix'] for leg in profile['legs']]==['TS426','TS424','TS422','RW25R','TD25R']
    assert (spec['lat'],spec['lon'])==(data['waypoint_data'][entry]['lat'],data['waypoint_data'][entry]['lon'])
    # Approach minimum/level segments and threshold crossing altitude.
    altitudes=[leg['target_altitude_ft']*.3048 for leg in profile['legs'][:2]]
    assert 600<=altitudes[0]<620 and altitudes[0]==altitudes[1]
    assert profile['legs'][-2]['target_altitude_ft']*.3048==pytest.approx(26)
    faf=data['waypoint_data']['TS424'];threshold=data['waypoint_data']['RW25R']
    angle=math.degrees(math.atan2(altitudes[1]-26,haversine_distance_nm(faf['lat'],faf['lon'],threshold['lat'],threshold['lon'])*1852))
    assert angle==pytest.approx(3,abs=.001)
    state=AircraftState('LAND',spec['lat'],spec['lon'],spec['altitude_ft'],spec['speed_kt'],spec['heading_deg'],0,'A320',0)
    reached=[]
    for _ in range(900):
        previous=state
        before=[leg['fix'] for leg in profile['legs']]
        step=advance_procedure(state,route,profile,1)
        state,route,profile=step.aircraft,step.remaining_route,step.profile
        after=[leg['fix'] for leg in profile['legs']]
        reached.extend(fix for fix in before if fix not in after)
        assert state.altitude_ft <= previous.altitude_ft+1e-6
        assert abs(state.altitude_ft-previous.altitude_ft)<30
        if step.completed:break
        assert state.ground_speed_kt>0
    assert step.completed and reached==['TS426','TS424','TS422','RW25R','TD25R']
    assert state.altitude_ft==pytest.approx(10/.3048)
    assert state.ground_speed_kt==0
    assert haversine_distance_nm(threshold['lat'],threshold['lon'],state.lat,state.lon)*1852==pytest.approx(16/math.tan(math.radians(3)),abs=.01)


def test_approach_predictor_matches_simulator_through_final_and_removal():
    config=configure_profile(ASTRAConfig(),'tsn_tma')
    reader=StateReader.for_mock(config,sim_step_s=1);reader.connect()
    start=len(load_profile('tsn_tma')['procedure_data']['DALAP2J']['legs'])-1
    reader.create_aircraft(**procedure_aircraft('tsn_tma','DALAP2J','FINAL','25R',start))
    snapshot=reader.poll()
    predicted=RouteAwareTrajectoryEngine(config,reader.get_route,reader.get_flight_profile).predict(snapshot)
    reader.step_simulation(300)
    actual=reader.poll().get('FINAL');future=predicted.at(5).get('FINAL')
    assert actual is not None and future is not None
    assert haversine_distance_nm(actual.lat,actual.lon,future.lat,future.lon)<1e-6
    assert actual.altitude_ft==pytest.approx(future.altitude_ft,abs=1e-5)
    reader.step_simulation(900)
    assert reader.list_aircraft()==[]
    assert predicted.at(15).get('FINAL') is None


def test_fixed_runways_and_sid_has_no_approach():
    for proc,runway in [('DALAP2J','25L'),('SAPEN2D','25R')]:
        with pytest.raises(ValueError, match='requires 25L'):
            procedure_aircraft('tsn_tma',proc,'TEST',runway)
    spec=procedure_aircraft('tsn_tma','SAPEN2D','TEST','25L')
    assert spec['procedure_profile']['approach_id'] is None
    assert spec['procedure_profile']['endpoint_behavior']=='handoff'


def test_radar_context_is_larger_than_assessment_and_deduplicates_fixes():
    data=load_profile('tsn_tma');c=data['center']
    for asset,radius in [('boundary.json',40),('radar_range.json',100)]:
        ring=geo_asset('tsn_tma',asset)['features'][0]['geometry']['coordinates'][0]
        assert all(haversine_distance_nm(c['lat'],c['lon'],lat,lon)==pytest.approx(radius,abs=1e-7) for lon,lat in ring)
    points=geo_asset('tsn_tma','waypoints.json')['features']
    points += geo_asset('tsn_tma','approach_fixes.json')['features']
    navaids=geo_asset('tsn_tma','navaids.json')['features']
    names=[p['properties']['name'] for p in points]+[p['properties']['ident'] for p in navaids]
    assert len(names)==len(set(names))
    assert {'BAOMY','BOMSU','SOKAN','TS426','TS424','TSH','AC','VTV','ANHOA'}<=set(names)
    assert 'DONXD' not in names and 'DONXO' in names
    assert any(70<haversine_distance_nm(c['lat'],c['lon'],*reversed(p['geometry']['coordinates']))<110 for p in points)
    layers={l['id']:l for l in geo_asset('tsn_tma','manifest.json')['layers']}
    assert all(not v['default_visible'] for k,v in layers.items() if k.startswith('procedure_'))
    assert all(layers[n]['default_visible'] for n in ['airways','waypoints','navaids','coastlines','firs','radar_range'])
    assert all(geo_asset('tsn_tma',layer['file'])['features'] for layer in layers.values())


def test_area_route_endpoints_use_single_canonical_catalogue():
    data=load_profile('tsn_tma')
    routes=geo_asset('tsn_tma','airways.json')['features']
    for f in routes:
        for name,coord in zip(f['properties']['waypoints'],f['geometry']['coordinates']):
            p=data['waypoint_data'][name]
            assert coord==[p['lon'],p['lat']]
    assert any(f['properties']['waypoints']==['BUKMA','BAOMY'] for f in routes)
    assert any(f['properties']['waypoints']==['BAOMY','MATGI'] for f in routes)


def test_centre_feeder_uses_connected_airway_before_star():
    spec=feeder_aircraft('tsn_tma','ENTRY');data=load_profile('tsn_tma');c=data['center']
    assert 40<haversine_distance_nm(c['lat'],c['lon'],spec['lat'],spec['lon'])<100
    assert any(['ANHOA','BITIS'] in r['segments'] for r in data['area_routes_data'])
    assert spec['procedure_profile']['legs'][0]['fix']=='BITIS'
    assert spec['procedure_profile']['legs'][1]['fix']=='NOKUM'
    assert spec['procedure_profile']['legs'][-1]['fix']=='TD25R'
