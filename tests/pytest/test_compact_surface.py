from astra.airport.graph import AirportGraph,KEY_NODES
from astra.airport.simulation import Simulation
from astra.airport.aircraft import Aircraft

def test_arrivals_use_p5_without_returning_to_landing_runway():
    g=AirportGraph('astra/airport/vvts_layout.json');s=Simulation(g)
    for i,stand in enumerate(g.stands()):
        a=Aircraft(str(i),'A320','arr',stand.id);s.add_aircraft(a)
        assert s.assign_arrival_route(a.callsign,KEY_NODES['RWY25R_EXIT_P4'],stand.id)
        exit_index=a.route.index(KEY_NODES['RWY25R_EXIT_P5'])
        assert a.route[exit_index:exit_index+3]==['n175','n174','n113']
        assert not set(a.route[exit_index+1:])&s.rwy25r_nodes
        assert a.route[exit_index+3]=='n124'

def test_crossing_waits_twenty_seconds_after_takeoff():
    g=AirportGraph('astra/airport/vvts_layout.json');s=Simulation(g)
    a=Aircraft('ARR','A320','arr','n9');s.add_aircraft(a)
    a.route=['n113','n124','n112'];a.cleared_cross=True
    s._last_takeoff_s=100;s.time_s=119
    assert s._should_hold(a,'n113','n124')
    s.time_s=120
    assert not s._should_hold(a,'n113','n124')
