"""Physical staged descent, all-present cohorts, and protected runway lining up."""
from copy import deepcopy
import math
import numpy as np
import pytest
from astra.airport.aircraft import Aircraft,AircraftState as GroundState
from astra.airport.graph import AirportGraph
from astra.airport.simulation import Simulation
from astra.centre import airway_network,control_area
from astra.interface.traffic_state import AircraftState
from astra.studies.flow_routes import arrival_spec,spec_trajectory,planning_path
from astra.studies.operational_cases import flight_plans
from astra.studies.workbook_cases import ROOT,read_workbook
from astra.trajectory.procedure import advance_procedure
from astra.trajectory.study_performance import altitude_speed
from astra.utils.geodesy import haversine_distance_nm


@pytest.mark.parametrize('altitude,lower,upper',[(10000,230,280),(20000,250,320),(25000,270,350),(30000,450,500),(41000,450,500)])
def test_nominal_ground_speed_stays_in_requested_altitude_bands(altitude,lower,upper):
    assert lower<=altitude_speed(altitude)<=upper


def flow_flight():
    return dict(route_family='W1_AC',requested_fl=330,stream_lane=1,descent_level_ft=26000,
        mid_descent_level_ft=16000,transfer_level_ft=10000,initial_stage=0)


def test_plk_bmt_cruise_and_distance_based_descent_reach_assigned_handoff():
    spec=arrival_spec(flow_flight());profile=deepcopy(spec['procedure_profile']);route=spec['route_waypoints']
    state=AircraftState('A001',spec['lat'],spec['lon'],spec['altitude_ft'],spec['speed_kt'],spec['heading_deg'],0,'A320',0)
    events={};passing={};speeds=[]
    for _ in range(5000):
        if 'BMT' not in events:
            assert state.altitude_ft==pytest.approx(33000,abs=.01)
            assert 450<=state.ground_speed_kt<=500
        result=advance_procedure(state,route,profile,1)
        state,route,profile=result.aircraft,result.remaining_route,result.profile
        for name,time in profile.get('study_waypoint_times',{}).items():
            if name not in events:events[name]=time;passing[name]=state.altitude_ft
        assert -3500.001<=state.vertical_speed_fpm<=2000.001
        if profile.get('approach_transfer_complete'):break
    else:pytest.fail('The named handoff was never crossed')
    assert passing['DESCENT_25']==pytest.approx(26000,abs=60)
    assert passing['DESCENT_55']==pytest.approx(16000,abs=60)
    assert passing['AC']==pytest.approx(10000,abs=60)
    nodes,_=airway_network();distance=haversine_distance_nm(*nodes['BMT'],*nodes['AC'])
    assert distance==pytest.approx(117.35,abs=.1)
    minutes=(events['AC']-events['BMT'])/60
    assert distance/450*60<minutes<35
    assert control_area(*nodes['AC'],'inbound',None,10000,False)['owner']=='CENTRE'
    assert control_area(*nodes['AC'],'inbound',None,10000,True)['owner']=='APPROACH'


@pytest.mark.parametrize('delay',[600,1200,3600])
def test_forward_stream_timing_matches_one_second_native_execution(delay):
    flight=flow_flight();spec=arrival_spec(flight,delay);original=deepcopy(spec)
    baseline,_=spec_trajectory(arrival_spec(flight),1)
    native,transfer=spec_trajectory(spec,1);projection,projected_transfer=planning_path(flight,delay)
    assert haversine_distance_nm(*native[0,1:3],*baseline[0,1:3])>10
    assert native[-1,0]-baseline[-1,0]==pytest.approx(delay,abs=5)
    assert not any(leg.get('phase')=='centre_hold' for leg in spec['procedure_profile']['legs'])
    assert spec['procedure_profile']['sequencing_circuits']==0
    assert abs(transfer-projected_transfer)<5
    assert abs(native[-1,0]-projection[-1,0])<5
    assert spec==original


def test_waypoint_progress_does_not_mutate_the_callers_empty_event_map():
    spec=arrival_spec(flow_flight());profile=spec['procedure_profile']
    profile['study_waypoint_times']={}
    state=AircraftState('A001',*spec['route_waypoints'][0],spec['altitude_ft'],spec['speed_kt'],
        spec['heading_deg'],0,'A320',0)
    result=advance_procedure(state,spec['route_waypoints'],profile,1)
    assert result.profile['study_waypoint_times']
    assert profile['study_waypoint_times']=={}


def test_extended_population_keeps_source_provenance_and_uses_all_corridors():
    records=read_workbook(ROOT/'evidence/VVTS_scenarios.xlsx')['Peak_50']
    flights=flight_plans('workbook_peak_50',records)
    assert len(flights)==60 and len(records)==50
    assert sum(f['synthetic_extension'] for f in flights)==10
    arrivals=[f for f in flights if f['direction']=='arrival']
    assert len(arrivals)==36
    assert sum(f['direction']=='departure' for f in flights)==24
    assert {'BIBAN_BITIS','SAPEN_WEST','NIXIV_VICAL','PTH_BAOMY','W1_AC','W1_LKH','VTV'}=={f['route_family'] for f in arrivals}
    assert any(f['initial_stage']==0 for f in arrivals) and any(f['initial_stage']>0 for f in arrivals)


def test_next_departure_lines_up_but_takeoffs_remain_two_minutes_apart():
    graph=AirportGraph('astra/airport/vvts_layout.json');sim=Simulation(graph)
    sim.running=True;sim.speed_factor=1;sim.allow_lineup=True;sim.minimum_departure_gap_s=120
    for index,stand in enumerate(graph.stands()[:2]):
        ac=Aircraft(f'D{index+1:03d}','A320','dep',stand.id);ac.ctot_s=300;ac.off_block_time_s=index*20
        sim.add_aircraft(ac);assert sim.assign_departure_route(ac.callsign)
    takeoffs={};entries={};lineup=set()
    for _ in range(800):
        for ac in sim.aircraft.values():
            if ac.state==GroundState.HOLDING:sim.grant_takeoff_clearance(ac.callsign)
        sim.tick(1)
        for ac in sim.aircraft.values():
            if ac.state==GroundState.LINING_UP:
                lineup.add(ac.callsign);assert ac.current_speed_mps==0
            if ac.route[min(ac.seg_idx,len(ac.route)-1)] in sim.rwy25l_nodes:entries.setdefault(ac.callsign,sim.time_s)
            if ac.is_done():takeoffs.setdefault(ac.callsign,sim.time_s)
        if len(takeoffs)==2:break
    assert len(takeoffs)==2 and lineup
    assert takeoffs['D001']>=300
    assert takeoffs['D002']-takeoffs['D001']>=120
    assert takeoffs['D001']<=entries['D002']<takeoffs['D002']


def test_takeoff_roll_does_not_yield_to_aircraft_waiting_beside_runway():
    graph=AirportGraph('astra/airport/vvts_layout.json');sim=Simulation(graph)
    sim.running=True;sim.speed_factor=1;sim.allow_lineup=True
    dep=Aircraft('D001','A320','dep','n167');dep.route=['n167','n169']
    dep.state=GroundState.TAXIING;dep.takeoff_roll_started=True;dep.current_speed_mps=60
    waiting=Aircraft('A001','A320','arr','n166');waiting.route=['n166','n165']
    waiting.state=GroundState.HOLDING
    sim.add_aircraft(dep);sim.add_aircraft(waiting)
    before=(dep.x,dep.y);sim.tick(1)
    assert dep.state==GroundState.TAXIING and dep.current_speed_mps>60
    assert (dep.x,dep.y)!=before
