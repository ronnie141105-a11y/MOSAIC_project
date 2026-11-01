"""Replay linked VVTS scenarios and write comparable movement measures."""
from __future__ import annotations

import json
from pathlib import Path
from statistics import mean

from astra.airspace import configure_profile
from astra.dashboard.legacy_flask_app import create_app
from astra.dashboard.store import CycleStore
from astra.interface.state_reader import StateReader
from astra.utils.config import ASTRAConfig


def run(duration_s=2200):
    config = configure_profile(ASTRAConfig(), 'tsn_tma')
    reader = StateReader.for_mock(config, sim_step_s=1)
    reader.connect()
    airport = create_app(CycleStore(), config, reader=reader).airport_integration
    results = {}
    for key in airport.STUDY_SCENARIOS:
        airport.load_study_scenario(key)
        reader.step_simulation(duration_s)
        flights = {}
        for callsign, fpl in airport.fpl.items():
            milestones = airport.milestones.get(callsign, {})
            ground = airport.sim.aircraft.get(callsign)
            flights[callsign] = {
                'operation': ground.operation if ground else ('dep' if fpl.get('sid') else 'arr'),
                'milestones_s': milestones,
                'hold_s': round(ground.hold_s, 1) if ground else 0,
                'taxi_out_s': round(milestones['takeoff'] - milestones['off_block'], 1)
                    if 'takeoff' in milestones and 'off_block' in milestones else None,
                'ctot_delta_s': round(milestones['takeoff'] - fpl['ctot_s'], 1)
                    if 'takeoff' in milestones and fpl.get('ctot_s', 0) > 0 else None,
                'landing_to_stand_s': round(milestones['stand_arrival'] - milestones['touchdown'], 1)
                    if 'stand_arrival' in milestones and 'touchdown' in milestones else None,
            }
        departures = [flight for flight in flights.values() if flight['operation'] == 'dep']
        taxi_out = [flight['taxi_out_s'] for flight in departures if flight['taxi_out_s'] is not None]
        takeoff_times = [flight['milestones_s']['takeoff'] for flight in departures
                         if 'takeoff' in flight['milestones_s']]
        slot_deltas = [flight['ctot_delta_s'] for flight in departures
                       if flight['ctot_delta_s'] is not None]
        results[key] = {
            'label': airport.STUDY_SCENARIOS[key][0],
            'takeoffs': len(takeoff_times),
            'landings': sum('touchdown' in f['milestones_s'] for f in flights.values()),
            'stand_arrivals': sum('stand_arrival' in f['milestones_s'] for f in flights.values()),
            'mean_taxi_out_s': round(mean(taxi_out), 1) if taxi_out else None,
            'total_departure_hold_s': round(sum(f['hold_s'] for f in departures), 1),
            'last_takeoff_s': max(takeoff_times) if takeoff_times else None,
            'mean_ctot_delta_s': round(mean(slot_deltas), 1) if slot_deltas else None,
            'flights': flights,
        }
    return dict(profile='tsn_tma', duration_s=duration_s, units='simulation seconds',
                scenarios=results)


if __name__ == '__main__':
    result = run()
    destination = Path('output/airport_study_results.json')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2), encoding='utf-8')
    for key, item in result['scenarios'].items():
        print(f"{key:23} takeoffs={item['takeoffs']} landings={item['landings']} "
              f"mean taxi-out={item['mean_taxi_out_s']}s "
              f"departure hold={item['total_departure_hold_s']}s "
              f"last takeoff={item['last_takeoff_s']}s")
    print(destination.resolve())
