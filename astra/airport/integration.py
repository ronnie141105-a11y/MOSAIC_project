"""Shared-clock VVTS ground/TMA handoff for mock scenarios.

AEON's graph and separation/holding logic run here without its PyQt UI or
engine-off fuel assumptions.  Positions on the approach extension are schematic;
TMA coordinates and procedure legs remain the source of airborne motion.
"""
from __future__ import annotations

from pathlib import Path
from threading import RLock
from copy import deepcopy
import re
import math

from astra.airspace import load_profile, procedure_aircraft
from astra.utils.geodesy import bearing_deg, haversine_distance_nm, move_position
from .aircraft import Aircraft, AircraftState
from .graph import AirportGraph, KEY_NODES
from .simulation import Simulation
from .surface_policy import (ARRIVAL_PROTECTION_NM,ARRIVAL_PROTECTION_S,LINEUP_LOOKAHEAD_S,
    MINIMUM_TAKEOFF_GAP_S)


class AirportIntegration:
    STAND_RELEASE_SPACING_S = 60  # nominal study value, not a published capacity
    STUDY_SCENARIOS = {
        'vvts_baseline': ('Baseline: one departure and one arrival',
            'One stand departure and one STAR/ILS arrival, with normal runway access.', 2),
        'vvts_departure_surge': ('Departure surge: immediate taxi',
            'Five departures request the runway together; compare queue and hold times.', 5),
        'vvts_stand_metering': ('Departure surge: stand metering',
            'The same five flights leave stands at nominal 44-second intervals.', 5),
        'vvts_ctot_sequence': ('CTOT sequence: timed runway release',
            'Five departures share 25L with planned wheel-off targets 120 seconds apart.', 5),
        'vvts_mixed_flow': ('Mixed flow: arrivals and departures',
            'Three departures and two ILS arrivals share taxiways and runway crossings.', 5),
        'vvts_weather_capacity': ('Heavy rain: demand exceeds capacity',
            'Ten departures request release in heavy rain. Review CTOT/stand metering, then compare delay and runway releases.', 10),
        'vvts_weather_recovery': ('Severe storm: suspension and recovery',
            'Five departures face a simulated severe storm; fair weather returns after five simulation minutes.', 5),
        'vvts_tma_weather': ('Thunderstorm in TMA',
            'Three STAR arrivals and two airport departures in a simulated TMA thunderstorm. Observe speeds, ETAs and arrival metering.', 5),
    }

    def __init__(self, reader, profile_name: str):
        self.reader = reader
        self.profile_name = profile_name
        self.graph = AirportGraph(str(Path(__file__).with_name('vvts_layout.json')))
        self.profile = load_profile(profile_name)
        self.sim = Simulation(self.graph)
        self.sim.runway_release_guard = self.departure_runway_available
        self.sim.runway_lineup_guard = self.departure_lineup_available
        self.sim.allow_lineup=True
        self.sim.lineup_lookahead_s=LINEUP_LOOKAHEAD_S
        self.sim.minimum_departure_gap_s=MINIMUM_TAKEOFF_GAP_S
        self.sim.running = True
        self.sim.speed_factor = 1
        self.sim.time_s = reader.simulation_time_s()
        self.fpl: dict[str, dict] = {}
        self.departures: dict[str, dict] = {}
        self.approaches: dict[str, dict] = {}
        self.events: list[dict] = []
        self.milestones: dict[str, dict] = {}
        self.study_key: str | None = None
        self.connected_fir = False
        self.rollout_tracks: set[str] = set()
        self.rollout_origins: dict[str, tuple[float, float, float]] = {}
        self._previous_tma: set[str] = set()
        self._last_time = reader.simulation_time_s()
        self._lock = RLock()
        self.airborne_specs = {}
        from .flow_management import FlowManagement
        self.flow = FlowManagement(self)

    def reset(self):
        with self._lock:
            self.sim.clear()
            self.fpl.clear()
            self.departures.clear()
            self.airborne_specs.clear()
            self.approaches.clear()
            self.events.clear()
            self.milestones.clear()
            self.study_key = None
            self.rollout_tracks.clear()
            self.rollout_origins.clear()
            self._previous_tma.clear()
            self._last_time = self.reader.simulation_time_s()
            self.flow.reset()

    def add_departure(self, *, callsign, aircraft_type, stand_id, sid,
                      requested_fl, destination, depart_route='', transition=None,
                      off_block_time_s=0, ctot_s=0, airborne_spec=None):
        callsign = callsign.strip().upper()
        if not re.fullmatch(r'[A-Z0-9_-]{1,16}', callsign):
            raise ValueError('Enter a callsign using 1–16 letters, digits, underscore or hyphen.')
        with self._lock:
            if callsign in self.sim.aircraft or any(a['callsign'] == callsign for a in self.reader.list_aircraft()):
                raise ValueError('Callsign already exists.')
            if self.graph.node(stand_id) not in self.graph.stands():
                raise ValueError('Choose a valid airport stand node.')
            if int(requested_fl) < 10 or int(requested_fl) > 450:
                raise ValueError('Requested flight level must be FL010–FL450.')
            off_block_time_s = float(off_block_time_s)
            ctot_s = float(ctot_s)
            if (not math.isfinite(off_block_time_s) or not math.isfinite(ctot_s)
                    or off_block_time_s < 0 or ctot_s < 0):
                raise ValueError('Off-block and CTOT must be nonnegative simulation seconds.')
            proc = self.profile['procedure_data'].get(sid)
            if not proc or proc['kind'] != 'sid':
                raise ValueError('Choose a VVTS departure SID.')
            # Validate transition using the same compiler as TMA.
            procedure_aircraft(self.profile_name, sid, callsign, transition=transition)
            ac = Aircraft(callsign, aircraft_type.strip().upper(), 'dep', stand_id)
            ac.off_block_time_s = off_block_time_s
            ac.ctot_s = ctot_s
            self.sim.add_aircraft(ac)
            if not self.sim.assign_departure_route(callsign):
                self.sim.remove_aircraft(callsign)
                raise ValueError('No taxi route from this stand to runway 25L.')
            self.fpl[callsign] = dict(callsign=callsign, origin='VVTS', destination=destination.strip().upper(),
                requested_fl=int(requested_fl), departure_route=depart_route.strip().upper(),
                off_block_time_s=off_block_time_s, ctot_s=ctot_s,
                sid=sid, transition=transition, runway='25L', aircraft_type=ac.ac_type,
                stand=self.graph.node(stand_id).name)
            self.departures[callsign] = dict(stage='ground')
            if airborne_spec is not None:
                self.airborne_specs[callsign] = deepcopy(airborne_spec)
            return self.fpl[callsign]

    def clear_takeoff(self, callsign):
        with self._lock:
            ac = self.sim.aircraft.get(callsign.upper())
            if not ac or ac.operation != 'dep':
                raise ValueError('Unknown ground departure.')
            self.sim.grant_takeoff_clearance(ac.callsign)
            self._event(ac.callsign, 'takeoff_clearance', self._last_time)

    def add_arrival(self, *, callsign, aircraft_type, origin, star,
                    requested_fl, arrival_route='', start_index=0, centre_start_nm=220, airborne_spec=None):
        callsign = callsign.strip().upper()
        if not re.fullmatch(r'[A-Z0-9_-]{1,16}', callsign):
            raise ValueError('Enter a callsign using 1–16 letters, digits, underscore or hyphen.')
        with self._lock:
            if callsign in self.sim.aircraft or any(a['callsign'] == callsign for a in self.reader.list_aircraft()):
                raise ValueError('Callsign already exists.')
            if int(requested_fl) < 10 or int(requested_fl) > 450:
                raise ValueError('Requested flight level must be FL010–FL450.')
            proc = self.profile['procedure_data'].get(star)
            if not proc or proc['kind'] != 'star':
                raise ValueError('Choose a VVTS arrival STAR.')
            spec = deepcopy(airborne_spec) if airborne_spec is not None else procedure_aircraft(self.profile_name, star, callsign, start_index=start_index)
            spec['callsign'] = callsign
            if self.connected_fir and start_index == 0 and airborne_spec is None:
                from astra.centre import connect_procedure
                reach = float(centre_start_nm)
                if not math.isfinite(reach) or not 45 <= reach <= 500:
                    raise ValueError('Centre entry range must be 45–500 NM.')
                spec = connect_procedure(spec,int(requested_fl),reach)
            spec['aircraft_type'] = aircraft_type.strip().upper()
            self.reader.create_aircraft(**spec)
            self.fpl[callsign] = dict(callsign=callsign, origin=origin.strip().upper(),
                destination='VVTS', requested_fl=int(requested_fl), arrival_route=arrival_route.strip().upper(),
                star=star, runway='25R', aircraft_type=spec['aircraft_type'], stand=None)
            self.fpl[callsign]['centre_route'] = spec['procedure_profile'].get('centre_route')
            return self.fpl[callsign]

    def point_merge_status(self, callsign):
        return self.reader.point_merge_status(callsign)

    def clear_point_merge(self, callsign):
        decision = self.reader.clear_point_merge(callsign)
        with self._lock:
            if callsign.upper() in self.fpl:
                self.fpl[callsign.upper()]['point_merge_clearance'] = decision['merge_fix']
            self._event(callsign.upper(), 'point_merge_direct', self.reader.simulation_time_s())
        return decision

    def clear_crossing(self, callsign):
        with self._lock:
            ac = self.sim.aircraft.get(callsign.upper())
            if not ac or ac.operation != 'arr':
                raise ValueError('Unknown ground arrival.')
            self.sim.grant_cross_clearance(ac.callsign)
            self._event(ac.callsign, 'crossing_clearance', self._last_time)

    def landing_runway_progress(self, ac):
        start = self.graph.node(KEY_NODES['RWY25R_SPAWN'])
        end = self.graph.node(KEY_NODES['RWY25R_EXIT_P4'])
        dx, dy = end.x-start.x, end.y-start.y
        return max(0.0, min(1.0, ((ac.x-start.x)*dx+(ac.y-start.y)*dy)/(dx*dx+dy*dy)))

    def departure_runway_available(self, ac):
        """Release before the 6 NM gate, with time to finish before touchdown."""
        for arrival in self.sim.aircraft.values():
            if arrival.operation != 'arr' or arrival.is_done() or not arrival.route:
                continue
            cur = arrival.route[min(arrival.seg_idx, len(arrival.route)-1)]
            nxt=arrival.route[arrival.seg_idx+1] if arrival.seg_idx+1<len(arrival.route) else None
            if cur in self.sim.rwy25r_nodes or cur in self.sim.rwy25l_nodes:
                return False
            if nxt in self.sim.rwy25l_nodes and (arrival.seg_prog>0 or arrival.cleared_cross):
                return False
        # Check all inbound traffic, including aircraft outside the local
        # approach list. Fast arrivals can still leave insufficient roll time.
        approaches=dict(self.approaches)
        threshold=self.profile['waypoint_data']['RW25R']
        for aircraft in self.reader.list_aircraft():
            cs=aircraft['callsign']
            if cs in self.sim.aircraft:continue
            profile=self.reader.get_flight_progress(cs) or {}
            if profile.get('direction')!='inbound':continue
            approaches[cs]=dict(distance_nm=haversine_distance_nm(aircraft['lat'],aircraft['lon'],threshold['lat'],threshold['lon']),
                speed_kt=aircraft.get('ground_speed_kt',140))
        # The distance gate applies at roll start. Arrival clearance distance
        # is not runway occupancy: use the remaining time and actual roll.
        roll = self.sim.departure_roll_seconds(ac)
        for arrival in approaches.values():
            speed=max(1,arrival.get('speed_kt',140));distance=max(0,arrival['distance_nm'])
            eta=distance/speed*3600
            if distance<=ARRIVAL_PROTECTION_NM or eta<=ARRIVAL_PROTECTION_S+roll:
                return False
        return True

    def departure_lineup_available(self, ac):
        """Lineup may wait for an arrival; give ground crossings priority."""
        for arrival in self.sim.aircraft.values():
            if arrival.operation!='arr' or arrival.is_done() or not arrival.route:continue
            cur=arrival.route[min(arrival.seg_idx,len(arrival.route)-1)]
            nxt=arrival.route[arrival.seg_idx+1] if arrival.seg_idx+1<len(arrival.route) else None
            if cur in self.sim.rwy25l_nodes or (nxt in self.sim.rwy25l_nodes and (arrival.seg_prog>0 or arrival.cleared_cross)):
                return False
        return True

    def reroute_ground(self, callsign: str, target_id: str, queue: bool = False):
        """AEON drag routing: replace the route or append one waypoint."""
        with self._lock:
            ac = self.sim.aircraft.get(callsign.upper())
            if not ac or ac.is_done() or self.departures.get(ac.callsign, {}).get('stage') == 'climb':
                raise ValueError('Choose an active ground aircraft.')
            if target_id not in self.graph.nodes:
                raise ValueError('Choose a valid airport graph node.')
            if queue and ac.route:
                start = ac.route[-1]
                path, _ = self.graph.dijkstra(start, target_id)
                if not path:
                    raise ValueError('No connected route to that node.')
                ac.route.extend(path[1:])
            else:
                if ac.route and ac.seg_idx + 1 < len(ac.route):
                    cur = ac.route[ac.seg_idx]
                    next_id = ac.route[ac.seg_idx + 1]
                    path, _ = self.graph.dijkstra(next_id, target_id)
                    if not path:
                        raise ValueError('No connected route to that node.')
                    ac.route = [cur, next_id] + path[1:]
                    ac.seg_idx = 0
                    # Keep segment progress and position during the drag.
                else:
                    nearest = min(self.graph.nodes.values(), key=lambda n:
                        (n.x-ac.x)**2 + (n.y-ac.y)**2)
                    path, _ = self.graph.dijkstra(nearest.id, target_id)
                    if not path:
                        raise ValueError('No connected route to that node.')
                    ac.route = path
                    ac.seg_idx = 0
                    ac.seg_prog = 0.0
                    ac.x, ac.y = nearest.x, nearest.y
                ac.manual_route = True
                if ac.state == AircraftState.HOLDING:
                    ac.state = AircraftState.TAXIING
            return list(ac.route)

    def restore_planned_route(self, callsign: str):
        """Return a manually routed aircraft to its departure/stand path."""
        with self._lock:
            ac = self.sim.aircraft.get(callsign.upper())
            if not ac or ac.is_done():
                raise ValueError('Choose an active ground aircraft.')
            nearest = min(self.graph.nodes.values(), key=lambda n:
                (n.x-ac.x)**2 + (n.y-ac.y)**2)
            if ac.operation == 'dep':
                points = [nearest.id, KEY_NODES['HLD_S1'],
                    KEY_NODES['RWY25L_START'], KEY_NODES['RWY25L_END']]
            else:
                points = [nearest.id, ac.stand_id]
            route = []
            for start, end in zip(points, points[1:]):
                leg, _ = self.graph.dijkstra(start, end)
                if not leg:
                    raise ValueError('No planned path from the current position.')
                route.extend(leg if not route else leg[1:])
            ac.route = route
            ac.seg_idx = 0
            ac.seg_prog = 0.0
            ac.x, ac.y = nearest.x, nearest.y
            ac.manual_route = False
            ac.state = AircraftState.TAXIING
            return list(route)

    def on_mock_tick(self):
        """Called after each connector tick, outside its own lock."""
        with self._lock:
            now = self.reader.simulation_time_s()
            if now < self._last_time:
                self.reset()
            dt = max(0.0, now - self._last_time)
            self._last_time = now
            self.flow.tick()
            if dt == 0:
                return
            remaining = dt
            while remaining > 0:
                step = min(remaining, 1.0)
                if ((self.flow.recovery_at_s is not None and self.sim.time_s >= self.flow.recovery_at_s)
                        or (self.flow.program and self.sim.time_s >= self.flow.program['ends_at_s'])):
                    self.flow.tick()
                if self.study_key:
                    for ac in list(self.sim.aircraft.values()):
                        if (ac.operation == 'arr' and ac.state == AircraftState.HOLDING
                                and ac.hold_s >= 30 and not ac.cleared_cross):
                            self.clear_crossing(ac.callsign)
                before = {cs: (ac.state, ac.seg_idx,
                    ac.route[ac.seg_idx] if ac.route and ac.seg_idx < len(ac.route) else None)
                    for cs, ac in self.sim.aircraft.items()}
                self.sim.tick(step)
                for cs, ac in self.sim.aircraft.items():
                    old = before.get(cs)
                    if old is None:
                        continue
                    previous_state, previous_index, previous_node = old
                    current_node = ac.route[ac.seg_idx] if ac.route and ac.seg_idx < len(ac.route) else None
                    if ac.operation == 'dep':
                        if previous_state == AircraftState.PARKED and ac.state == AircraftState.TAXIING:
                            self._event(cs, 'off_block', self.sim.time_s)
                        if current_node in self.sim.rwy25l_nodes and previous_node not in self.sim.rwy25l_nodes:
                            self._event(cs, 'runway_entry', self.sim.time_s)
                            self.flow.runway_entry(cs, self.sim.time_s)
                        if ac.takeoff_roll_started:
                            self._event(cs,'takeoff_roll',self.sim.time_s)
                        if ac.state == AircraftState.DEPARTED and previous_state != AircraftState.DEPARTED:
                            self._event(cs, 'takeoff', self.sim.time_s)
                    else:
                        if (current_node in self.sim.rwy25r_nodes
                                and self.landing_runway_progress(ac) >= 2/3):
                            self._event(cs, 'landing_two_thirds', self.sim.time_s)
                        if previous_node in self.sim.rwy25r_nodes and current_node not in self.sim.rwy25r_nodes:
                            self._event(cs, 'runway_exit', self.sim.time_s)
                            if cs in self.rollout_tracks:
                                self.reader.remove_aircraft(cs)
                                self.rollout_tracks.discard(cs)
                                self.rollout_origins.pop(cs, None)
                        if current_node in self.sim.rwy25l_nodes and previous_node not in self.sim.rwy25l_nodes:
                            self._event(cs, 'crossing_entry', self.sim.time_s)
                        if previous_node in self.sim.rwy25l_nodes and current_node not in self.sim.rwy25l_nodes:
                            self._event(cs, 'crossing_exit', self.sim.time_s)
                        if ac.state == AircraftState.ARRIVED and previous_state != AircraftState.ARRIVED:
                            self._event(cs, 'stand_arrival', self.sim.time_s)
                    if ac.state == AircraftState.HOLDING and previous_state != AircraftState.HOLDING:
                        self._event(cs, 'hold_start', self.sim.time_s, repeat=True)
                    if previous_state == AircraftState.HOLDING and ac.state != AircraftState.HOLDING:
                        self._event(cs, 'hold_end', self.sim.time_s, repeat=True)
                remaining -= step
            # Keep the TMA runway-roll symbol aligned with the airport
            # position and braking speed until the actual 25R exit event.
            spawn_node = self.graph.node(KEY_NODES['RWY25R_SPAWN'])
            exit_node = self.graph.node(KEY_NODES['RWY25R_EXIT_P5'])
            axis_x, axis_y = exit_node.x - spawn_node.x, exit_node.y - spawn_node.y
            axis_sq = axis_x * axis_x + axis_y * axis_y
            for cs in tuple(self.rollout_tracks):
                ac = self.sim.aircraft.get(cs)
                origin = self.rollout_origins.get(cs)
                if not ac or not origin or axis_sq == 0:
                    continue
                fraction = max(0.0, min(1.0,
                    ((ac.x - spawn_node.x) * axis_x + (ac.y - spawn_node.y) * axis_y) / axis_sq))
                lat, lon = move_position(origin[0], origin[1], 249.1, origin[2] * fraction)
                speed = ac.current_speed_mps * 1.943844
                if not self.reader.update_aircraft(cs, lat=lat, lon=lon,
                        ground_speed_kt=speed, altitude_ft=33):
                    endpoint = move_position(origin[0], origin[1], 249.1, origin[2])
                    self.reader.create_aircraft(callsign=cs, aircraft_type=ac.ac_type,
                        lat=lat, lon=lon, heading_deg=249.1, altitude_ft=33,
                        speed_kt=speed, route_waypoints=[endpoint])
            current = {a['callsign']: a for a in self.reader.list_aircraft()}
            threshold = self.profile['waypoint_data']['RW25R']
            for cs, a in current.items():
                profile = self.reader.get_flight_progress(cs) or {}
                if profile.get('study_waypoint_times') and cs in self.fpl:
                    self.fpl[cs]['study_waypoint_times']=dict(profile['study_waypoint_times'])
                if profile.get('connected_fir'):
                    from astra.centre import distance_nm
                    range_nm=distance_nm(a['lat'],a['lon'])
                    if profile.get('direction')=='outbound':
                        if profile.get('leg_phase')=='centre':
                            self._event(cs,'sid_exit',now)
                        if range_nm>40:self._event(cs,'centre_handoff',now)
                    elif profile.get('direction')=='inbound' and (profile.get('approach_transfer_complete') if profile.get('approach_transfer_fix') else range_nm<=40):
                        self._event(cs,'approach_handoff',now)
                if profile.get('direction') != 'inbound' or cs in self.sim.aircraft:
                    continue
                if cs not in self.fpl:
                    self.fpl[cs] = dict(callsign=cs, origin='ENROUTE', destination='VVTS',
                        requested_fl=None, departure_route='', sid='', star=profile.get('procedure_id'),
                        runway='25R', aircraft_type=a['aircraft_type'], stand=None)
                distance = haversine_distance_nm(a['lat'], a['lon'], threshold['lat'], threshold['lon'])
                if distance <= 8.0:
                    self.approaches[cs] = dict(distance_nm=distance, altitude_ft=a['altitude_ft'],
                        speed_kt=a.get('ground_speed_kt', 0), vertical_speed_fpm=a.get('vertical_speed_fpm', 0), aircraft_type=a['aircraft_type'],
                        lat=a['lat'], lon=a['lon'])
                    self._event(cs, 'approach_visible', now)
            for cs in list(self.approaches):
                if cs not in current and cs in self._previous_tma and cs not in self.sim.aircraft:
                    self._land(cs)
                elif cs in current:
                    self.approaches[cs]['altitude_ft'] = current[cs]['altitude_ft']
                    self.approaches[cs]['speed_kt'] = current[cs].get('ground_speed_kt', 0)
                    self.approaches[cs]['vertical_speed_fpm'] = current[cs].get('vertical_speed_fpm', 0)
                    self.approaches[cs]['distance_nm'] = haversine_distance_nm(
                        current[cs]['lat'], current[cs]['lon'], threshold['lat'], threshold['lon'])
            for cs, state in list(self.departures.items()):
                ac = self.sim.aircraft.get(cs)
                if state['stage'] == 'ground' and ac and ac.state == AircraftState.DEPARTED:
                    state.update(stage='climb', altitude_ft=0.0, elapsed_s=0.0)
                if state['stage'] == 'climb':
                    state['elapsed_s'] += dt
                    state['altitude_ft'] = min(1500.0, state['elapsed_s'] * (2000.0 / 60.0))
                    if state['altitude_ft'] >= 1500.0:
                        self._handoff_departure(cs)
                        state['stage'] = 'tma'
                        self._event(cs, 'tma_handoff', now)
            for cs in self._previous_tma - set(current):
                if cs in self.departures and self.departures[cs]['stage'] == 'tma':
                    self._event(cs, 'fir_route_exit' if self.connected_fir else 'sid_exit', now)
            self._previous_tma = set(current)
            self.flow.tick()

    def _event(self, callsign, kind, time_s, repeat=False):
        marks = self.milestones.setdefault(callsign, {})
        if not repeat and kind in marks:
            return
        if not repeat:
            marks[kind] = round(float(time_s), 1)
        self.events.append(dict(callsign=callsign, event=kind, time_s=round(float(time_s), 1)))

    def _land(self, cs):
        last_approach = self.approaches.pop(cs, None)
        self._event(cs, 'touchdown', self._last_time)
        taken = {a.stand_id for a in self.sim.aircraft.values() if a.state != AircraftState.DEPARTED}
        exit_node = self.graph.node(KEY_NODES['RWY25R_EXIT_P5'])
        available = [n for n in self.graph.stands() if n.id not in taken]
        available.sort(key=lambda n: (n.x-exit_node.x)**2 + (n.y-exit_node.y)**2)
        if self.study_key == 'vvts_mixed_flow':
            preferred = {'ARR901': 'n9', 'ARR902': 'n10'}.get(cs)
            if preferred:
                available.sort(key=lambda n: (n.id != preferred,
                    (n.x-exit_node.x)**2 + (n.y-exit_node.y)**2))
        stand = available[0].id if available else None
        if not stand:
            return
        ac = Aircraft(cs, self.fpl[cs]['aircraft_type'], 'arr', stand)
        self.sim.add_aircraft(ac)
        spawn = self.graph.node(KEY_NODES['RWY25R_SPAWN'])
        ac.x, ac.y = spawn.x, spawn.y
        if not self.sim.assign_arrival_route(cs, KEY_NODES['RWY25R_EXIT_P5'], stand):
            self.sim.remove_aircraft(cs)
            return
        ac.state = AircraftState.LANDED
        self.fpl[cs]['stand'] = self.graph.node(stand).name
        if last_approach:
            # Keep a low-altitude TMA track through the runway rollout. The
            # airport graph controls exit timing; this geographic leg only
            # makes the runway movement visible on the TMA monitor.
            lat, lon = last_approach['lat'], last_approach['lon']
            exit_distance_nm = math.hypot(spawn.x-exit_node.x,
                spawn.y-exit_node.y) * 2.74 / 1852
            endpoint = move_position(lat, lon, 249.1, exit_distance_nm)
            self.reader.create_aircraft(callsign=cs,
                aircraft_type=self.fpl[cs]['aircraft_type'], lat=lat, lon=lon,
                heading_deg=249.1, altitude_ft=33, speed_kt=140,
                route_waypoints=[endpoint])
            self.rollout_tracks.add(cs)
            self.rollout_origins[cs] = (lat, lon, exit_distance_nm)

    def _handoff_departure(self, cs):
        fpl = self.fpl[cs]
        spec = deepcopy(self.airborne_specs[cs]) if cs in self.airborne_specs else procedure_aircraft(self.profile_name, fpl['sid'], cs,
            transition=fpl.get('transition'))
        if self.connected_fir and cs not in self.airborne_specs:
            from astra.centre import connect_procedure
            spec = connect_procedure(spec,fpl.get('requested_fl') or 300)
            fpl['centre_route'] = spec['procedure_profile']['centre_route']
        if cs in self.airborne_specs:
            fpl['centre_route'] = spec['procedure_profile'].get('centre_route')
        spec['callsign'] = cs
        spec['aircraft_type'] = fpl['aircraft_type']
        spec['altitude_ft'] = 1500.0
        # Place the handoff beyond the runway, along the SID's first leg.
        # 45 s at 205 kt from the threshold matches the 2,000 fpm climb handoff.
        spec['lat'], spec['lon'] = move_position(spec['lat'], spec['lon'],
            bearing_deg(spec['lat'], spec['lon'], *spec['route_waypoints'][0]), 205 * 45 / 3600)
        spec['speed_kt'] = 205.0
        spec['heading_deg'] = bearing_deg(spec['lat'], spec['lon'], *spec['route_waypoints'][0])
        self.reader.create_aircraft(**spec)

    def load_study_scenario(self, key):
        """Replace traffic with one of the linked VVTS ground/TMA studies."""
        if key not in self.STUDY_SCENARIOS:
            raise ValueError('Unknown VVTS airport scenario.')
        self.reader.reset_simulation()
        self.study_key = key
        stands = sorted(self.graph.stands(), key=lambda n:
            (n.x-self.graph.node(KEY_NODES['HLD_S1']).x)**2 +
            (n.y-self.graph.node(KEY_NODES['HLD_S1']).y)**2)
        departures = 2 if key == 'vvts_tma_weather' else 10 if key == 'vvts_weather_capacity' else 3 if key == 'vvts_mixed_flow' else 5 if key in (
            'vvts_departure_surge', 'vvts_stand_metering', 'vvts_ctot_sequence', 'vvts_weather_recovery') else 1
        for i in range(departures):
            self.add_departure(callsign=f'DEP{901+i}', aircraft_type='A320',
                stand_id=stands[i].id, sid=('SAPEN2D', 'ANTRI2D', 'KADUM2D',
                'LANHI2D', 'XOBAV2D')[i % 5], requested_fl=240+i*10,
                destination='VVNB', depart_route='VVTS SID',
                off_block_time_s=i*self.STAND_RELEASE_SPACING_S
                    if key == 'vvts_stand_metering' else 0,
                ctot_s=100+i*120 if key == 'vvts_ctot_sequence' else 0)
            self.clear_takeoff(f'DEP{901+i}')
        if key == 'vvts_weather_capacity':
            self.flow.set_weather(dict(preset='heavy_rain'))
        if key == 'vvts_weather_recovery':
            self.flow.set_weather(dict(preset='severe', duration_min=5))
        if key == 'vvts_tma_weather':
            self.flow.set_weather(dict(preset='thunderstorm'))
            for i, star in enumerate(('BITIS2H', 'SAPEN2H', 'VICAL3H')):
                self.add_arrival(callsign=f'ARR{901+i}', aircraft_type='A320', origin='VVNB',
                    star=star, requested_fl=240, arrival_route=star,
                    start_index=len(self.profile['procedure_data'][star]['legs']) - (6 if i == 0 else 2 if i == 1 else 1))
        if key in ('vvts_baseline', 'vvts_mixed_flow'):
            self.add_arrival(callsign='ARR901', aircraft_type='A320', origin='VVNB',
                star='BITIS2H', requested_fl=240, arrival_route='L637 BITIS',
                start_index=2)
        if key == 'vvts_mixed_flow':
            self.add_arrival(callsign='ARR902', aircraft_type='A321', origin='VVDB',
                star='VICAL3H', requested_fl=220, arrival_route='VICAL',
                start_index=2)

    def load_linked_scenario(self):
        """Backward-compatible alias for the original linked demo."""
        self.load_study_scenario('vvts_baseline')

    def state(self):
        with self._lock:
            tower_arrivals={}
            threshold=self.profile['waypoint_data']['RW25R']
            for a in self.reader.list_aircraft():
                if a['callsign'] in self.sim.aircraft:continue
                progress=self.reader.get_flight_progress(a['callsign']) or {}
                if progress.get('direction')!='inbound':continue
                distance=haversine_distance_nm(a['lat'],a['lon'],threshold['lat'],threshold['lon'])
                if distance<=20:
                    tower_arrivals[a['callsign']]=dict(lat=a['lat'],lon=a['lon'],distance_nm=distance,
                        altitude_ft=a['altitude_ft'],speed_kt=a['ground_speed_kt'],
                        heading_deg=a['heading_deg'],vertical_speed_fpm=a.get('vertical_speed_fpm',0))
            aircraft = []
            for cs, ac in self.sim.aircraft.items():
                if ac.operation == 'dep' and self.departures.get(cs, {}).get('stage') == 'tma':
                    continue
                departure = self.departures.get(cs, {})
                climbing = ac.operation == 'dep' and departure.get('stage') == 'climb'
                progress = min(1.0, departure.get('elapsed_s', 0.0) / 45.0) if climbing else 0.0
                aircraft.append(dict(callsign=cs,
                    x=ac.x - 275 * progress if climbing else ac.x,
                    y=ac.y - 36 * progress if climbing else ac.y,
                    state='CLIMBING' if climbing else ac.state.name,
                    altitude_ft=departure.get('altitude_ft') if climbing else None,
                    speed_kt=205.0 if climbing else ac.current_speed_mps * 1.943844,
                    vertical_speed_fpm=2000.0 if climbing else 0.0,
                    operation=ac.operation, route=ac.route, seg_idx=ac.seg_idx,
                    manual_route=ac.manual_route, stand=ac.stand_id,
                    fpl=self.fpl.get(cs), metrics=ac.metrics()))
            return dict(sim_time_s=self._last_time,
                running=self.reader.is_simulation_running(), aircraft=aircraft,
                approaches=self.approaches.copy(),tower_arrivals=tower_arrivals,fpl=self.fpl.copy(),
                events=self.events[-200:], milestones=self.milestones.copy(),
                study_key=self.study_key,
                flow_management=self.flow.state(),
                stands=[dict(id=n.id, name=n.name) for n in self.graph.stands()],
                sids=[p['id'] for p in self.profile['procedure_data'].values() if p['kind']=='sid'],
                stars=[p['id'] for p in self.profile['procedure_data'].values() if p['kind']=='star'])

    def export_scenario(self):
        """Persist ground positions and FPL alongside the TMA scenario."""
        with self._lock:
            return dict(fpl=self.fpl.copy(), departures=self.departures.copy(),
                sim_time_s=self.sim.time_s,
                runway_sequence=dict(allow_lineup=self.sim.allow_lineup,
                    minimum_departure_gap_s=self.sim.minimum_departure_gap_s,
                    last_takeoff_s=self.sim._last_takeoff_s),
                events=list(self.events), milestones=self.milestones.copy(),
                study_key=self.study_key, rollout_tracks=sorted(self.rollout_tracks),
                flow_management=self.flow.export(),
                rollout_origins=self.rollout_origins.copy(),
                aircraft=[dict(callsign=a.callsign, aircraft_type=a.ac_type,
                    operation=a.operation, stand_id=a.stand_id, state=a.state.name,
                    route=list(a.route), seg_idx=a.seg_idx, seg_prog=a.seg_prog,
                    x=a.x, y=a.y, cleared_takeoff=a.cleared_takeoff,
                    takeoff_roll_started=a.takeoff_roll_started,
                    cleared_cross=a.cleared_cross, off_block_time_s=a.off_block_time_s,
                    ctot_s=a.ctot_s, manual_route=a.manual_route,
                    atfm_off_block_s=a.atfm_off_block_s, atfm_ctot_s=a.atfm_ctot_s,
                    flow_stand_hold_s=a.flow_stand_hold_s,
                    current_speed_mps=a.current_speed_mps) for a in self.sim.aircraft.values()
                    if a.state != AircraftState.DEPARTED])

    def import_scenario(self, data):
        with self._lock:
            self.sim.time_s = self.reader.simulation_time_s()
            self._last_time = self.sim.time_s
            sequence=data.get('runway_sequence') or {}
            self.sim.allow_lineup=bool(sequence.get('allow_lineup',False))
            self.sim.minimum_departure_gap_s=float(sequence.get('minimum_departure_gap_s',0))
            self.sim._last_takeoff_s=sequence.get('last_takeoff_s')
            self.fpl = dict(data.get('fpl') or {})
            self.departures = dict(data.get('departures') or {})
            self.events = list(data.get('events') or [])
            self.milestones = dict(data.get('milestones') or {})
            self.study_key = data.get('study_key')
            self.rollout_tracks = set(data.get('rollout_tracks') or [])
            self.rollout_origins = {cs: tuple(values) for cs, values in
                (data.get('rollout_origins') or {}).items()}
            for item in data.get('aircraft') or []:
                if item['stand_id'] not in self.graph.nodes:
                    continue
                a = Aircraft(item['callsign'], item['aircraft_type'],
                    item['operation'], item['stand_id'])
                self.sim.add_aircraft(a)
                a.state = AircraftState[item['state']]
                a.route = list(item['route'])
                a.seg_idx = int(item['seg_idx'])
                a.seg_prog = float(item['seg_prog'])
                a.x, a.y = float(item['x']), float(item['y'])
                a.cleared_takeoff = bool(item.get('cleared_takeoff'))
                a.takeoff_roll_started=bool(item.get('takeoff_roll_started',False))
                a.cleared_cross = bool(item.get('cleared_cross'))
                a.off_block_time_s = float(item.get('off_block_time_s', 0))
                a.ctot_s = float(item.get('ctot_s', 0))
                a.atfm_off_block_s = float(item.get('atfm_off_block_s', 0))
                a.atfm_ctot_s = float(item.get('atfm_ctot_s', 0))
                a.flow_stand_hold_s = float(item.get('flow_stand_hold_s', 0))
                a.manual_route = bool(item.get('manual_route', False))
                a.current_speed_mps = float(item.get('current_speed_mps', 0))
            if data.get('flow_management'):
                self.flow.restore(data['flow_management'])
