"""
AEON Simulation - Simulation Engine
Handles time-stepping, conflict detection, ATC clearance logic.
"""
import math
from typing import Dict, List, Optional, Set
from .graph import AirportGraph, KEY_NODES
from .aircraft import Aircraft, AircraftState, AEONMode


# Runway nodes set (for on-runway detection)
RWY_25L_NODES = {'n123', 'n124'}
RWY_25R_NODES = {'n125', 'n175', 'n126'}
ALL_RWY_NODES = RWY_25L_NODES | RWY_25R_NODES


class Simulation:
    def __init__(self, graph: AirportGraph):
        self.graph   : AirportGraph         = graph
        self.rwy25l_nodes = set().union(*(set(p.node_ids) for p in graph.paths if p.name == 'RWY-25L/07R'))
        self.rwy25r_nodes = set().union(*(set(p.node_ids) for p in graph.paths if p.name == 'RWY-25R/07L'))
        self.aircraft: Dict[str, Aircraft]  = {}
        self.time_s  : float                = 0.0
        self.running : bool                 = False
        self.paused  : bool                 = False
        self.speed_factor: float            = 5.0   # sim speed multiplier

        # Runway occupation tracking
        self._rwy25l_occupied: Optional[str] = None  # callsign on 25L
        self._rwy25r_occupied: Optional[str] = None  # callsign on 25R
        self.weather_taxi_factor = 1.0
        self.departure_gate = None
        self.runway_release_guard = None
        self.runway_lineup_guard = None
        self._roll_time_cache = {}
        self.allow_lineup = False
        self.lineup_lookahead_s = 60.0
        self.minimum_departure_gap_s = 0.0
        self._last_takeoff_s = None

    # ── Aircraft management ─────────────────────────────────
    def add_aircraft(self, ac: Aircraft):
        """Add aircraft and place it at its stand."""
        node = self.graph.node(ac.stand_id)
        if node:
            ac.x, ac.y = node.x, node.y
        self.aircraft[ac.callsign] = ac

    def remove_aircraft(self, callsign: str):
        self.aircraft.pop(callsign, None)

    def clear(self):
        self.aircraft.clear()
        self.time_s = 0.0
        self._rwy25l_occupied = None
        self._rwy25r_occupied = None
        self._last_takeoff_s = None

    # ── Routing ─────────────────────────────────────────────
    def assign_departure_route(self, callsign: str) -> bool:
        """Compute route: stand → HLD-S1 → WP-1 (enters runway)."""
        ac = self.aircraft.get(callsign)
        if not ac:
            return False
        hld = KEY_NODES['HLD_S1']
        rwy = KEY_NODES['RWY25L_START']
        # Stand → holding point
        path1, d1 = self.graph.dijkstra(ac.stand_id, hld)
        # Holding point → runway entry
        path2, d2 = self.graph.dijkstra(hld, rwy)
        if not path1 or not path2:
            return False
        # Merge (avoid duplicating HLD-S1)
        # Continue the takeoff roll along the full runway before handoff.
        path3, _ = self.graph.dijkstra(rwy, KEY_NODES['RWY25L_END'])
        if not path3:
            return False
        ac.route = path1 + path2[1:] + path3[1:]
        ac.seg_idx = 0
        ac.seg_prog = 0.0
        return True

    def assign_arrival_route(self, callsign: str, exit_node: str, stand_id: str) -> bool:
        """Compute route: WP-3 → exit_node → stand."""
        ac = self.aircraft.get(callsign)
        if not ac:
            return False
        exit_node = KEY_NODES['RWY25R_EXIT_P5']
        spawn = KEY_NODES['RWY25R_SPAWN']
        # On runway to exit
        path1, _ = self.graph.dijkstra(spawn, exit_node)
        # Exit to stand
        # Commit to P5 before searching the apron: an unrestricted shortest
        # path can reverse along 25R and leave via P3/P2 instead.
        hold = KEY_NODES['HLD_P5']
        runway = self.rwy25r_nodes - {exit_node}
        exit_path, _ = self.graph.dijkstra(exit_node, hold, forbidden=runway | {'n298'})
        apron, _ = self.graph.dijkstra(hold, stand_id, forbidden=self.rwy25r_nodes | set(exit_path[:-1]) | {'n298','n296'})
        path2 = exit_path + apron[1:] if exit_path and apron else []
        if not path1 or not path2:
            return False
        ac.route = path1 + path2[1:]
        ac.stand_id = stand_id
        ac.seg_idx = 0
        ac.seg_prog = 0.0
        return True

    def custom_route(self, callsign: str, from_id: str, to_id: str) -> bool:
        """Dijkstra route between any two nodes."""
        ac = self.aircraft.get(callsign)
        if not ac:
            return False
        path, d = self.graph.dijkstra(from_id, to_id)
        if not path:
            return False
        ac.route = path
        ac.seg_idx = 0
        ac.seg_prog = 0.0
        return True

    # ── ATC Clearance ────────────────────────────────────────
    def grant_takeoff_clearance(self, callsign: str):
        ac = self.aircraft.get(callsign)
        if ac:
            ac.cleared_takeoff = True

    def grant_cross_clearance(self, callsign: str):
        ac = self.aircraft.get(callsign)
        if ac:
            ac.cleared_cross = True

    # ── Main tick ────────────────────────────────────────────
    def tick(self, dt_real: float):
        """Advance simulation by dt_real seconds of wall time."""
        if self.paused or not self.running:
            return
        dt = min(dt_real * self.speed_factor, 2.0)  # cap to avoid jumps
        self.time_s += dt

        # Update runway occupation
        self._update_rwy_occupation()

        for ac in list(self.aircraft.values()):
            if ac.is_done():
                continue
            self._tick_aircraft(ac, dt)

    def _update_rwy_occupation(self):
        self._rwy25l_occupied = None
        self._rwy25r_occupied = None
        for ac in self.aircraft.values():
            if ac.is_done() or not ac.route:
                continue
            cur_node = ac.route[ac.seg_idx] if ac.seg_idx < len(ac.route) else None
            next_node=ac.route[ac.seg_idx+1] if ac.seg_idx+1<len(ac.route) else None
            if cur_node in self.rwy25l_nodes or (next_node in self.rwy25l_nodes and ac.seg_prog>0):
                self._rwy25l_occupied = ac.callsign
            if cur_node in self.rwy25r_nodes or (next_node in self.rwy25r_nodes and ac.seg_prog>0):
                self._rwy25r_occupied = ac.callsign

    def _tick_aircraft(self, ac: Aircraft, dt: float):
        if ac.state == AircraftState.PARKED:
            ac.current_speed_mps = 0.0
            if ac.operation == 'dep':
                if self.time_s < max(ac.off_block_time_s, ac.atfm_off_block_s):
                    if self.time_s >= ac.off_block_time_s:
                        ac.flow_stand_hold_s += dt
                    return
                if self.departure_gate and not self.departure_gate(ac):
                    ac.flow_stand_hold_s += dt
                    return
            # Auto-start if route assigned
            if ac.route:
                ac.state = AircraftState.TAXIING
            return

        if not ac.route:
            ac.current_speed_mps = 0.0
            return
        if ac.seg_idx >= len(ac.route) - 1:
            # Reached end of route
            self._complete_route(ac)
            return

        cur_id  = ac.route[ac.seg_idx]
        next_id = ac.route[ac.seg_idx + 1]

        # Check hold conditions
        if self._should_hold(ac, cur_id, next_id):
            ac.current_speed_mps = 0.0
            if ac.state != AircraftState.LINING_UP:ac.state = AircraftState.HOLDING
            ac.hold_s += dt
            ac.delay_s += dt
            ac.fuel_kg += ac.fuel_rate_kgs() * dt * 0.3  # idle burn
            return

        ac.state = AircraftState.TAXIING

        # Detect if on runway
        departure_roll = ac.operation == 'dep' and (ac.takeoff_roll_started if self.allow_lineup else (cur_id in self.rwy25l_nodes or next_id in self.rwy25l_nodes))
        arrival_roll = ac.operation == 'arr' and (cur_id in self.rwy25r_nodes or next_id in self.rwy25r_nodes)
        # Reserve entry immediately, including the segment from the hold to
        # the threshold; two aircraft must not pass the same tick's check.
        if cur_id in self.rwy25l_nodes or next_id in self.rwy25l_nodes:
            self._rwy25l_occupied = ac.callsign
        if cur_id in self.rwy25r_nodes or next_id in self.rwy25r_nodes:
            self._rwy25r_occupied = ac.callsign
        taxi_mps = ac.speed_svgu_per_s(on_runway=False) * 2.74 * self.weather_taxi_factor
        if departure_roll:
            # Approximate A320 ground roll: accelerate to a 145 kt rotation.
            ac.current_speed_mps = min(74.6, ac.current_speed_mps + 2.6 * dt)
        elif arrival_roll:
            # Touchdown near 140 kt, then braking to taxi speed at the exit.
            ac.current_speed_mps = max(taxi_mps, (ac.current_speed_mps or 72.0) - 1.1 * dt)
        else:
            ac.current_speed_mps = taxi_mps
        spd = ac.current_speed_mps / 2.74

        # Segment length
        na = self.graph.node(cur_id)
        nb = self.graph.node(next_id)
        if not na or not nb:
            ac.seg_idx += 1
            ac.seg_prog = 0.0
            return

        seg_len = math.hypot(na.x - nb.x, na.y - nb.y)
        if seg_len < 0.01:
            ac.seg_idx += 1
            ac.seg_prog = 0.0
            return

        step = (spd * dt) / seg_len
        ac.seg_prog = min(ac.seg_prog + step, 1.0)

        ac.x = na.x + (nb.x - na.x) * ac.seg_prog
        ac.y = na.y + (nb.y - na.y) * ac.seg_prog
        ac.add_trail()

        ac.taxi_time_s   += dt
        ac.fuel_kg       += ac.fuel_rate_kgs() * dt
        ac.distance_svgu += spd * dt

        if ac.seg_prog >= 1.0:
            ac.seg_idx += 1
            ac.seg_prog = 0.0
            # Snap to node
            ac.x, ac.y = nb.x, nb.y

    def _should_hold(self, ac: Aircraft, cur_id: str, next_id: str) -> bool:
        """Determine if aircraft must hold."""

        if (ac.operation == 'dep' and cur_id not in self.rwy25l_nodes
                and next_id in self.rwy25l_nodes and ac.seg_prog<=1e-9 and self.departure_gate
                and not self.departure_gate(ac, entering=True)):
            return True

        # An arrival leaving 25R needs a separate clearance before crossing
        # the active departure runway, whichever graph node is the entry.
        if (ac.operation == 'arr' and next_id in self.rwy25l_nodes
                and cur_id not in self.rwy25l_nodes and self._last_takeoff_s is not None
                and self.time_s < self._last_takeoff_s + 20):
            return True
        if (ac.operation == 'arr' and next_id in self.rwy25l_nodes
                and cur_id not in self.rwy25l_nodes and not ac.cleared_cross):
            return True

        # ── Departure: hold at HLD-S1 until takeoff clearance ──
        if (ac.operation == 'dep' and cur_id not in self.rwy25l_nodes
                and next_id in self.rwy25l_nodes and ac.seg_prog<=1e-9):
            if (not self.allow_lineup and self.runway_release_guard and not self.runway_release_guard(ac)):
                return True
            if self.allow_lineup and self.runway_lineup_guard and not self.runway_lineup_guard(ac):
                return True
            # CTOT refers to wheel-off at the runway end. Release from the
            # hold early enough to account for the nominal runway roll.
            roll_s = self.departure_roll_seconds(ac)
            if self.allow_lineup:
                earliest=max(ac.ctot_s,ac.atfm_ctot_s,
                    self._last_takeoff_s+self.minimum_departure_gap_s if self._last_takeoff_s is not None else 0)
                if (self.lineup_lookahead_s is not None
                        and self.time_s+roll_s+self.lineup_lookahead_s<earliest):return True
                if any(other.operation=='arr' and other.cleared_cross and other.route
                        and other.route[min(other.seg_idx,len(other.route)-1)]==KEY_NODES['HLD_P5']
                        for other in self.aircraft.values() if not other.is_done()):return True
            if not ac.cleared_takeoff or (not self.allow_lineup and self.time_s + roll_s < max(ac.ctot_s, ac.atfm_ctot_s)):
                ac.state = AircraftState.HOLDING
                return True

        if (self.allow_lineup and ac.operation=='dep' and cur_id in self.rwy25l_nodes
                and not ac.takeoff_roll_started and ac.seg_prog<=1e-9):
            earliest=max(ac.ctot_s,ac.atfm_ctot_s,
                (self._last_takeoff_s+self.minimum_departure_gap_s) if self._last_takeoff_s is not None else 0)
            if (not ac.cleared_takeoff or self.time_s+self.departure_roll_seconds(ac)<earliest
                    or (self.runway_release_guard and not self.runway_release_guard(ac))):
                ac.state=AircraftState.LINING_UP
                return True
            ac.takeoff_roll_started=True

        # ── Arrival: hold at HLD-P5 if RWY 25L is occupied ───
        if ac.operation == 'arr' and cur_id == KEY_NODES['HLD_P5']:
            if self._rwy25l_occupied not in (None, ac.callsign) and not self._can_cross_stopped_lineup(ac,next_id):
                return True

        # ── Runway incursion prevention ─────────────────────
        # Don't enter 25L if another aircraft is on it
        if (next_id in self.rwy25l_nodes and self._rwy25l_occupied not in (None, ac.callsign)
                and not self._can_cross_stopped_lineup(ac,next_id)):
            return True

        # Don't enter 25R if another aircraft is on it
        if next_id in self.rwy25r_nodes and self._rwy25r_occupied not in (None, ac.callsign):
            return True

        # Reserve a shared taxi intersection before reaching its centre.
        # Otherwise two converging branches can both get inside the following
        # buffer and stop each other after one aircraft reaches the junction.
        if cur_id not in self.rwy25l_nodes|self.rwy25r_nodes and next_id not in self.rwy25l_nodes|self.rwy25r_nodes:
            junction=self.graph.node(next_id)
            if junction and len(self.graph.adj[next_id])>=3:
                distance=math.hypot(ac.x-junction.x,ac.y-junction.y)
                if distance<=60:
                    for other in self.aircraft.values():
                        if (other is ac or other.operation==ac.operation or other.is_done()
                                or other.state==AircraftState.PARKED or not other.route):continue
                        oc=other.route[min(other.seg_idx,len(other.route)-1)]
                        on=other.route[other.seg_idx+1] if other.seg_idx+1<len(other.route) else None
                        od=math.hypot(other.x-junction.x,other.y-junction.y)
                        if oc==next_id and od<30:return True
                        if on==next_id and oc!=cur_id and od<=60:
                            priority=lambda a,d:(round(d,6),0 if a.operation=='arr' else 1,a.callsign)
                            if priority(other,od)<priority(ac,distance):return True

        # ── Separation: maintain distance from aircraft ahead ─
        SEPARATION_SVGU = 30.0  # ~82m
        for other in self.aircraft.values():
            # An aircraft parked at its stand does not occupy the taxi lane.
            # Nearby stand spurs can be closer than the taxi-following buffer.
            if other.callsign == ac.callsign or other.is_done() or other.state == AircraftState.PARKED:
                continue
            if ac.operation=='dep' and ac.takeoff_roll_started and cur_id in self.rwy25l_nodes:
                # A crossing aircraft waiting outside the reserved runway is
                # not traffic ahead on the takeoff roll. Applying taxi following
                # distance across that hold creates a mutual runway deadlock.
                other_cur=other.route[min(other.seg_idx,len(other.route)-1)] if other.route else None
                other_next=other.route[other.seg_idx+1] if other.seg_idx+1<len(other.route) else None
                if other_cur not in self.rwy25l_nodes and not (other_next in self.rwy25l_nodes and other.seg_prog>0):
                    continue
            d = math.hypot(other.x - ac.x, other.y - ac.y)
            if d < SEPARATION_SVGU and self._is_ahead(ac, other):
                return True

        return False

    def _can_cross_stopped_lineup(self, ac, next_id):
        """A stopped threshold lineup need not trap a distant runway crossing.

        The release guard separately prevents that departure from rolling while
        an arrival is cleared to cross or is still crossing the runway.
        """
        if not self.allow_lineup or ac.operation!='arr' or not ac.cleared_cross:return False
        crossing=self.graph.node(next_id)
        if crossing is None:return False
        for other in self.aircraft.values():
            if other is ac or other.is_done() or not other.route:continue
            cur=other.route[min(other.seg_idx,len(other.route)-1)]
            nxt=other.route[other.seg_idx+1] if other.seg_idx+1<len(other.route) else None
            occupies=cur in self.rwy25l_nodes or (nxt in self.rwy25l_nodes and other.seg_prog>0)
            if not occupies:continue
            if (other.operation!='dep' or other.takeoff_roll_started or other.seg_prog>1e-9
                    or cur not in self.rwy25l_nodes or math.hypot(other.x-crossing.x,other.y-crossing.y)<60):return False
        return True

    def departure_roll_seconds(self, ac):
        """Predict wheel-off with the same 1 s acceleration and node stepping."""
        route = tuple(ac.route[ac.seg_idx:])
        key = (route, round(ac.seg_prog, 6), round(ac.current_speed_mps, 3))
        if key not in self._roll_time_cache:
            speed, progress, elapsed = ac.current_speed_mps, ac.seg_prog, 0
            for left, right in zip(route, route[1:]):
                a, b = self.graph.node(left), self.graph.node(right)
                remaining = math.hypot(a.x-b.x, a.y-b.y)*2.74*(1-progress)
                while remaining > 1e-8:
                    speed = min(74.6, speed+2.6)
                    remaining -= speed
                    elapsed += 1
                progress = 0
            self._roll_time_cache[key] = elapsed
        return self._roll_time_cache[key]

    def _is_ahead(self, ac: Aircraft, other: Aircraft) -> bool:
        """Check if other aircraft is ahead of ac on its route."""
        if ac.seg_idx >= len(ac.route):
            return False
        next_id = ac.route[min(ac.seg_idx + 1, len(ac.route) - 1)]
        nb = self.graph.node(next_id)
        if not nb:
            return False
        # Other is "ahead" if it's closer to our next node than we are
        d_other_to_next = math.hypot(other.x - nb.x, other.y - nb.y)
        d_self_to_next  = math.hypot(ac.x   - nb.x, ac.y   - nb.y)
        return d_other_to_next < d_self_to_next

    def _complete_route(self, ac: Aircraft):
        """Called when aircraft reaches end of route."""
        if ac.manual_route:
            # AEON-style drag route: stop at the chosen node. Reaching an
            # arbitrary taxiway node must not trigger takeoff or arrival.
            ac.state = AircraftState.HOLDING
            ac.route = []
            ac.seg_idx = 0
            ac.seg_prog = 0.0
            ac.manual_route = False
            return
        if ac.operation == 'dep':
            ac.state = AircraftState.DEPARTED
            self._last_takeoff_s = self.time_s
        else:
            ac.state = AircraftState.ARRIVED
            ac.current_speed_mps = 0.0
            # Snap to stand
            stand = self.graph.node(ac.stand_id)
            if stand:
                ac.x, ac.y = stand.x, stand.y

    # ── Queries ─────────────────────────────────────────────
    def aircraft_at_hold(self, hold_id: str) -> List[Aircraft]:
        result = []
        for ac in self.aircraft.values():
            if (ac.state == AircraftState.HOLDING and
                    ac.route and ac.seg_idx < len(ac.route) and
                    ac.route[ac.seg_idx] == hold_id):
                result.append(ac)
        return result

    def all_done(self) -> bool:
        return bool(self.aircraft) and all(ac.is_done() for ac in self.aircraft.values())

    def clock_str(self) -> str:
        t = int(self.time_s)
        return f"{t // 3600:02d}:{(t % 3600) // 60:02d}:{t % 60:02d}"
