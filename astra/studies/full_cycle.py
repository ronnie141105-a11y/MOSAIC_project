"""Generate a complete synthetic ground/terminal/FIR functional fixture.

The native airport and procedure engines run on one-second steps. Only the
finished, audited result is saved for synchronized playback and instant seek.
"""
from datetime import timedelta
import csv
import gzip
import json
import math

import numpy as np

from astra.airspace import configure_profile
from astra.airport.integration import AirportIntegration
from astra.centre import distance_nm
from astra.interface.state_reader import StateReader
from astra.utils.config import ASTRAConfig
from astra.studies.system_tests import CASES, START, pair_audit

SIDS = ('SAPEN2D', 'XOBAV2D', 'ANTRI2D', 'KADUM2D', 'SAPEN2D',
        'XOBAV2D', 'ANTRI2D', 'KADUM2D', 'SAPEN2D', 'XOBAV2D')
STARS = ('BITIS2H', 'DALAP2H', 'VICAL3H', 'BITIS2H', 'DALAP2H',
         'VICAL3H', 'BITIS2H', 'DALAP2H', 'VICAL3H', 'BITIS2H')


def _runtime():
    config = configure_profile(ASTRAConfig(), 'tsn_tma')
    reader = StateReader.for_mock(config, sim_step_s=1)
    reader.connect()
    airport = AirportIntegration(reader, 'tsn_tma')
    airport.connected_fir = True
    airport.study_key = 'test_full_cycle'
    reader._connector.on_tick = airport.on_mock_tick
    reader._connector.on_reset = airport.reset
    return reader, airport


def flight_plan():
    _, airport = _runtime()
    stands = []
    for node in sorted(airport.graph.stands(), key=lambda n: (n.y, n.x)):
        if all(math.hypot(node.x-old.x, node.y-old.y) >= 40 for old in stands):
            stands.append(node)
        if len(stands) == 10:
            break
    if len(stands) != 10:
        raise ValueError('Ten separate departure stands are required')
    flights = []
    for i in range(10):
        ac_type = 'A321' if i % 3 == 1 else 'A320'
        flights.append(dict(callsign=f'TDEP{i+1:02d}', aircraft_type=ac_type,
            direction='departure', procedure=SIDS[i], stand_id=stands[i].id,
            adep='VVTS', ades=('VVNB', 'VVCR', 'VVDN', 'VVPQ')[i % 4], requested_fl=300))
        flights.append(dict(callsign=f'TARR{i+1:02d}', aircraft_type=ac_type,
            direction='arrival', procedure=STARS[i], adep=('VVNB', 'VVDN', 'VVCR')[i % 3],
            ades='VVTS', requested_fl=300))
    return flights


def _departure(airport, flight, offset):
    airport.add_departure(callsign=flight['callsign'], aircraft_type=flight['aircraft_type'],
        stand_id=flight['stand_id'], sid=flight['procedure'], requested_fl=flight['requested_fl'],
        destination=flight['ades'], off_block_time_s=30+offset)


def _arrival(airport, flight):
    airport.add_arrival(callsign=flight['callsign'], aircraft_type=flight['aircraft_type'],
        origin=flight['adep'], star=flight['procedure'], requested_fl=flight['requested_fl'],
        centre_start_nm=130)


def _clearances(airport):
    for cs, ac in airport.sim.aircraft.items():
        if ac.operation == 'dep' and ac.state.name == 'HOLDING' and not ac.cleared_takeoff and ac.hold_s >= 10:
            airport.clear_takeoff(cs)
    # AirportIntegration issues crossing clearances after a 30 s test hold;
    # the existing runway-occupation checks still control physical entry.


def simulate(flights, offsets, *, record_ground=False, max_s=20000):
    reader, airport = _runtime()
    pending = []
    for flight in flights:
        if flight['direction'] == 'departure':
            _departure(airport, flight, offsets[flight['callsign']])
        else:
            pending.append((offsets[flight['callsign']], flight))
    paths = {f['callsign']: [] for f in flights}
    ground = {}

    def capture(now):
        for ac in reader.list_aircraft():
            paths[ac['callsign']].append([now, ac['lat'], ac['lon'], ac['altitude_ft'],
                ac['ground_speed_kt'], ac['heading_deg'], ac['vertical_speed_fpm']])
        if not record_ground:
            return
        for ac in airport.state()['aircraft']:
            track = ground.setdefault(ac['callsign'], dict(operation=ac['operation'],
                route=list(ac['route']), stand=ac['stand'], samples=[]))
            row = [now, round(ac['x'], 5), round(ac['y'], 5), round(ac['speed_kt'], 5),
                   ac['altitude_ft'], ac['vertical_speed_fpm'], ac['state'], ac['seg_idx']]
            samples = track['samples']
            if not samples or samples[-1][1:] != row[1:]:
                old = track.get('_previous')
                if old and old[0] > samples[-1][0]:
                    samples.append(old)
                samples.append(row)
            track['_previous'] = row

    for now in range(max_s+1):
        for birth, flight in pending[:]:
            if birth <= now:
                _arrival(airport, flight)
                pending.remove((birth, flight))
        capture(now)
        complete = all(('fir_route_exit' if f['direction'] == 'departure' else 'stand_arrival')
                       in airport.milestones.get(f['callsign'], {}) for f in flights)
        if complete:
            break
        _clearances(airport)
        reader.step_simulation()
    else:
        raise ValueError(f'Full-cycle traffic did not finish: {airport.milestones}')
    for cs, track in ground.items():
        last = track.pop('_previous')
        if track['samples'][-1][0] < last[0]:
            track['samples'].append(last)
        track['start_s'] = track['samples'][0][0]
        track['end_s'] = (airport.milestones[cs]['tma_handoff']
                          if track['operation'] == 'dep' else now+36)
    return dict(paths={cs: np.asarray(rows, dtype=float) for cs, rows in paths.items()},
        ground=ground, milestones=airport.milestones, events=airport.events,
        fpl=airport.fpl, duration_s=now+35)


def _transfer(path, direction):
    radii = np.asarray([distance_nm(p[1], p[2]) for p in path])
    crossing = np.where((radii[:-1] > 40) & (radii[1:] <= 40))[0] if direction == 'arrival' else np.where((radii[:-1] <= 40) & (radii[1:] > 40))[0]
    if not len(crossing):
        raise ValueError('Full-cycle flight did not cross the 40 NM boundary')
    i = int(crossing[0]); fraction = (40-radii[i])/(radii[i+1]-radii[i])
    return dict(time_s=round(float(path[i, 0]+fraction*(path[i+1, 0]-path[i, 0])), 3),
        fix='VVTS_40NM', lat=float(path[i, 1]+fraction*(path[i+1, 1]-path[i, 1])),
        lon=float(path[i, 2]+fraction*(path[i+1, 2]-path[i, 2])))


def _audit(flights, paths):
    pairs = [dict(left=a['callsign'], right=b['callsign'],
                  **pair_audit(paths[a['callsign']], paths[b['callsign']]))
             for i, a in enumerate(flights) for b in flights[i+1:]]
    transfers = [dict(callsign=f['callsign'], direction=f['direction'], procedure=f['procedure'],
                      **_transfer(paths[f['callsign']], f['direction'])) for f in flights]
    arrivals = sorted((t for t in transfers if t['direction'] == 'arrival'), key=lambda t: t['time_s'])
    gaps = [round(b['time_s']-a['time_s'], 3) for a, b in zip(arrivals, arrivals[1:])]
    return pairs, transfers, arrivals, gaps


def build_full_cycle(case_id, root):
    flights = flight_plan()
    offsets, placed, transfer_times = {}, [], []
    # Admit complete native flights, including the stand/taxi time before
    # the airborne part. Add extra time when the shared ground run needs it.
    for flight in flights:
        reference = simulate([flight], {flight['callsign']: 0})
        original = reference['paths'][flight['callsign']]
        transfer = _transfer(original, flight['direction'])['time_s']
        offset = (int(flight['callsign'][-2:])-1)*120
        while offset <= 14400:
            path = original.copy(); path[:, 0] += offset
            gap_ok = flight['direction'] != 'arrival' or all(abs(transfer+offset-t) >= 180 for t in transfer_times)
            if gap_ok and all(not pair_audit(path, other, margin=True)['violations'] for other in placed):
                break
            offset += 30
        else:
            raise ValueError('Could not separate the full-cycle admission schedule')
        offsets[flight['callsign']] = offset
        placed.append(path)
        if flight['direction'] == 'arrival':
            transfer_times.append(transfer+offset)
    for attempt in range(15):
        run = simulate(flights, offsets, record_ground=True)
        pairs, transfers, arrivals, gaps = _audit(flights, run['paths'])
        conflicts = [p for p in pairs if p['violations']]
        print(json.dumps(dict(full_cycle_attempt=attempt+1, duration_s=run['duration_s'],
            violating_pairs=len(conflicts), minimum_transfer_gap_s=min(gaps))), flush=True)
        if not conflicts and min(gaps) >= 120:
            break
        delays = {}
        for pair in conflicts:
            delays[pair['right']] = max(delays.get(pair['right'], 0), 120)
        for left, right in zip(arrivals, arrivals[1:]):
            if right['time_s']-left['time_s'] < 120:
                delays[right['callsign']] = max(delays.get(right['callsign'], 0), 180)
        for cs, delay in delays.items():
            offsets[cs] += delay
    else:
        raise ValueError('Full-cycle separation audit failed; no fixture published')
    folder = root/case_id
    folder.mkdir(parents=True, exist_ok=True)
    stamp = lambda seconds: (START+timedelta(seconds=float(seconds))).isoformat(timespec='seconds')
    fields = ['flight_id', 'callsign', 'aircraft_type', 'adep', 'ades', 'time_utc', 'lat', 'lon',
              'altitude_ft', 'ground_speed_kt', 'heading_deg', 'vertical_speed_fpm', 'on_ground', 'source']
    metadata = []
    with (folder/'tracks.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        for flight in flights:
            cs = flight['callsign']; path = run['paths'][cs]; marks = run['milestones'][cs]
            inbound = flight['direction'] == 'arrival'
            completion = marks['stand_arrival' if inbound else 'fir_route_exit']
            event = marks['touchdown' if inbound else 'takeoff']
            metadata.append(dict(**flight, runway='25R' if inbound else '25L',
                centre_route=run['fpl'][cs].get('centre_route'), stand=run['fpl'][cs]['stand'],
                start_s=offsets[cs], off_block_time_s=30+offsets[cs] if not inbound else None,
                completed_s=completion, simulated_slot_utc=stamp(event), planned_event_utc=stamp(event),
                first_track_utc=stamp(path[0, 0]), last_track_utc=stamp(path[-1, 0]),
                evidence='synthetic_full_cycle_native_simulation', synthetic=True))
            for t, lat, lon, alt, speed, heading, vs in path:
                writer.writerow(dict(flight_id=cs, callsign=cs, aircraft_type=flight['aircraft_type'],
                    adep=flight['adep'], ades=flight['ades'], time_utc=stamp(t), lat=lat, lon=lon,
                    altitude_ft=alt, ground_speed_kt=speed, heading_deg=heading, vertical_speed_fpm=vs,
                    on_ground=False, source='SYNTHETIC_FULL_CYCLE'))
    with gzip.open(folder/'ground_tracks.json.gz', 'wt', encoding='utf-8') as stream:
        json.dump(dict(flights=run['ground'], events=run['events'], milestones=run['milestones']),
                  stream, separators=(',', ':'))
    audit = dict(sample_s=1, horizontal_nm=10, same_heading_horizontal_nm=20,
        same_heading_tolerance_deg=25, vertical_ft=1000,
        separation_logic='horizontal >= threshold OR vertical >= 1000 ft; airborne paths only',
        transfer_minimum_s=120, minimum_arrival_transfer_gap_s=min(gaps),
        violating_pairs=0, pair_checks=pairs, transfer_events=transfers, arrival_transfer_gaps_s=gaps)
    manifest = dict(case_id=case_id, label=CASES[case_id]['label'], basis=CASES[case_id]['description'],
        synthetic=True, system_test_version='full-cycle-1', local_start=START.isoformat(),
        local_end=stamp(run['duration_s']), duration_s=run['duration_s'], connected_fir=True,
        counts=dict(total=20, arrivals=10, departures=10), flights=metadata,
        ground_replay_file='ground_tracks.json.gz', lifecycle_events=run['milestones'],
        separation_audit=audit, limitations=[
            'Synthetic functional traffic, not observed flights or real FPL data.',
            'Generated with the native airport graph and connected SID/STAR procedure simulator at 1 s steps.',
            'Ground uses native taxi spacing and runway occupancy; airborne 10/20 NM or 1000 ft criteria are audited separately.',
            'A320/A321 share the current nominal performance model; this is not aircraft-type performance calibration.',
            'Automatic test clearances, a 40 NM study handoff boundary and saved historical airway geometry are simulation assumptions.',
            'Playback is read-only so pause, seek and restart preserve the audited traffic.'])
    (folder/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest
