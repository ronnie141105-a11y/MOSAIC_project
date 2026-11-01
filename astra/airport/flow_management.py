"""Executable local ATFM procedure on the shared airport/TMA simulation clock.

One reviewed program at a time: departure CTOT/stand metering, MINIT, ground
stop, or bounded upstream arrival speed metering. Slots are study flow targets,
not separation minima. Weather reduction is a physical simulation constraint.
"""
from copy import deepcopy
import math
from uuid import uuid4

from .aircraft import AircraftState
from .surface_policy import MAX_ACTIVE_DEPARTURES
from .weather import PRESETS, decode_metar, preset_weather
from astra.utils.geodesy import haversine_distance_nm
from astra.trajectory.weather import TMA_SPEED_FACTORS, procedure_speed
from astra.trajectory.procedure import advance_procedure
from astra.interface.traffic_state import AircraftState as TrafficAircraftState


def bounded_number(value, name, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be a finite number from {low} to {high}.')
    return float(value)


class FlowManagement:
    TYPES = ('departure_slots', 'minit', 'ground_stop', 'arrival_metering')

    def __init__(self, airport):
        self.airport = airport
        self.reset()

    def reset(self):
        self.weather = preset_weather('clear')
        self.nominal_departures_per_hour = 60.0
        self.nominal_arrivals_per_hour = 40.0
        self.recovery_at_s = None
        self.revision = 0
        self.program = None
        self.preview = None
        self.history = []
        self.slots = []
        self._signature = None
        self._last_entry_s = None
        self._sync_simulation()

    @property
    def now(self):
        return self.airport.sim.time_s

    def rates(self):
        factor = self.weather['capacity_factor']
        return self.nominal_departures_per_hour * factor, self.nominal_arrivals_per_hour * factor

    def set_weather(self, body):
        if not isinstance(body, dict):
            raise ValueError('JSON object required.')
        report = (decode_metar(body['metar']) if 'metar' in body else preset_weather(body.get('preset', 'clear')))
        if 'metar' in body:
            report['source'] = 'USER_SUPPLIED_METAR'
        dep = bounded_number(body.get('nominal_departures_per_hour', self.nominal_departures_per_hour), 'Nominal departure rate', 1, 120)
        arr = bounded_number(body.get('nominal_arrivals_per_hour', self.nominal_arrivals_per_hour), 'Nominal arrival rate', 1, 120)
        duration = bounded_number(body.get('duration_min', 0), 'Weather duration', 0, 180)
        self.weather = report
        self.nominal_departures_per_hour, self.nominal_arrivals_per_hour = dep, arr
        self.recovery_at_s = self.now + duration * 60 if duration else None
        self.revision += 1
        self.preview = None
        self._signature = None
        self._sync_simulation()
        self.tick()
        self._record('WEATHER_CHANGED', report['label'])
        return self.state()

    def _record(self, event, reason):
        self.history.append(dict(event=event, reason=reason, time_s=self.now))
        self.history = self.history[-100:]

    def _sync_simulation(self):
        sim = self.airport.sim
        sim.weather_taxi_factor = self.weather['taxi_factor']
        sim.departure_gate = self.departure_gate
        self.airport.reader._connector.set_tma_weather(self.tma_weather())

    def tma_weather(self):
        return dict(preset=self.weather['preset'], center=deepcopy(self.airport.profile['center']),
                    radius_nm=self.airport.profile['radius_nm'],
                    wind_direction_deg=self.weather['wind_direction_deg'], wind_speed_kt=self.weather['wind_speed_kt'],
                    speed_factor=TMA_SPEED_FACTORS[self.weather['preset']], until_s=self.recovery_at_s,
                    source='SIMULATED_TMA_WEATHER')

    def _pending(self):
        sim = self.airport.sim
        return [ac for ac in sim.aircraft.values() if ac.operation == 'dep' and not ac.is_done()
                and not (ac.route and ac.route[ac.seg_idx] in sim.rwy25l_nodes)]

    def _travel_s(self, ac):
        """Remaining ground transit estimate, consistent with existing CTOT roll model."""
        seconds = 0.0
        for i in range(ac.seg_idx, len(ac.route) - 1):
            a, b = (self.airport.graph.node(n) for n in ac.route[i:i + 2])
            distance = math.hypot(a.x - b.x, a.y - b.y) * 2.74
            if i == ac.seg_idx:
                distance *= 1 - ac.seg_prog
            on_runway = ac.route[i] in self.airport.sim.rwy25l_nodes or ac.route[i + 1] in self.airport.sim.rwy25l_nodes
            seconds += distance / (52 if on_runway else 11.3 * self.weather['taxi_factor'])
        return seconds

    def _arrival_rows(self):
        rows = []
        threshold = self.airport.profile['waypoint_data']['RW25R']
        for ac in self.airport.reader.list_aircraft():
            cs = ac['callsign']
            profile = self.airport.reader.get_flight_profile(cs) or {}
            route = self.airport.reader.get_route(cs) or []
            if (profile.get('direction') != 'inbound' or 'legs' not in profile
                    or len(route) != len(profile['legs'])):
                continue
            distance = haversine_distance_nm(ac['lat'], ac['lon'], threshold['lat'], threshold['lon'])
            lat, lon = ac['lat'], ac['lon']
            eta = self.now
            profile['weather_endpoint'] = list(route[-1]) if route else None
            adjustable_s = 0.0
            adjustable_segments = []
            for point, leg in zip(route, profile['legs']):
                nominal = leg.get('nominal_speed_kt') or ac['ground_speed_kt']
                speed, _ = procedure_speed(nominal, leg, profile, lat, lon, *point, eta, include_atfm=False)
                segment_s = haversine_distance_nm(lat, lon, *point) / max(speed, 1) * 3600
                # Same >10 NM altitude/speed envelope as the shared propagator.
                if speed > 180 and leg['target_altitude_ft'] >= 3000 and haversine_distance_nm(*point, threshold['lat'], threshold['lon']) > 10:
                    adjustable_s += segment_s
                    adjustable_segments.append((segment_s, speed))
                eta += segment_s
                lat, lon = point
            # Calculate completion with the same event-based propagator as
            # prediction, including recovery in the middle of a leg. Demand
            # excludes existing ATFM controls while retaining the weather.
            intent = deepcopy(profile)
            intent.pop('atfm_speed_factor', None)
            intent.pop('atfm_until_s', None)
            aircraft = TrafficAircraftState(cs, ac['lat'], ac['lon'], ac['altitude_ft'],
                ac['ground_speed_kt'], ac['heading_deg'], ac.get('vertical_speed_fpm', 0), ac['aircraft_type'], self.now)
            completion = advance_procedure(aircraft, route, intent, 86400)
            eta = self.now + completion.elapsed_s
            rows.append(dict(callsign=cs, estimated_time_s=eta, distance_nm=distance,
                             adjustable_s=adjustable_s, adjustable_segments=adjustable_segments))
        return sorted(rows, key=lambda row: (row['estimated_time_s'], row['callsign']))

    def _config(self, body):
        kind = body.get('type')
        if kind not in self.TYPES:
            raise ValueError('Choose departure_slots, minit, ground_stop or arrival_metering.')
        reason = body.get('reason', '')
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 200:
            raise ValueError('Enter a coordination reason (1–200 characters).')
        duration = bounded_number(body.get('duration_min', 30), 'Program duration', 1, 180)
        dep, arr = self.rates()
        maximum = arr if kind == 'arrival_metering' else dep
        if kind == 'arrival_metering' and maximum <= 0:
            raise ValueError('Arrival capacity is zero; speed metering cannot resolve this condition.')
        rate = bounded_number(body.get('rate_per_hour', max(1, maximum)), 'Program rate', 1, 120)
        spacing = bounded_number(body.get('minit_min', 3), 'MINIT interval', 1, 30)
        return dict(type=kind, reason=reason.strip(), duration_min=duration,
                    rate_per_hour=rate, minit_min=spacing)

    def _rows(self, config):
        dep, arr = self.rates()
        if config['type'] == 'arrival_metering':
            if arr <= 0:
                return [dict(callsign=row['callsign'], estimated_time_s=row['estimated_time_s'],
                             target_time_s=None, delay_s=None, speed_factor=1.0,
                             residual_delay_s=None, status='CAPACITY_REVIEW_REQUIRED')
                        for row in self._arrival_rows()]
            spacing = 3600 / min(arr, config['rate_per_hour'])
            previous = -math.inf
            rows = []
            for item in self._arrival_rows():
                target = max(item['estimated_time_s'], previous + spacing)
                delay = target - item['estimated_time_s']
                # Maximum 20% reduction: extra time is at most 25% of eligible cruise time.
                factor = max(.8, item['adjustable_s'] / (item['adjustable_s'] + delay)) if item['adjustable_s'] else 1.0
                absorbed = sum(seconds * (speed / max(180, speed * factor) - 1)
                               for seconds, speed in item['adjustable_segments'])
                public = {key: value for key, value in item.items() if key != 'adjustable_segments'}
                rows.append(dict(**public, target_time_s=target, delay_s=delay, speed_factor=factor,
                                 feasible_time_s=item['estimated_time_s'] + absorbed,
                                 residual_delay_s=max(0, delay - absorbed), status='SPEED_METERING' if absorbed else 'NO_SPEED_CHANGE'))
                previous = target
            return rows
        requests = []
        for ac in self._pending():
            ready = max(self.now, ac.off_block_time_s) + self._travel_s(ac)
            requests.append((max(ready, ac.ctot_s), ac.callsign, ac))
        rows = []
        spacing = max(3600 / max(dep, .001),
                      config['minit_min'] * 60 if config['type'] == 'minit' else 3600 / config['rate_per_hour'])
        previous = -math.inf
        for ready, cs, ac in sorted(requests, key=lambda r: (r[0], r[1])):
            stop = config['type'] == 'ground_stop' or dep == 0
            target = None if stop else max(ready, previous + spacing)
            if target is not None:
                previous = target
            off_block = max(ac.off_block_time_s, target - self._travel_s(ac)) if target is not None else None
            rows.append(dict(callsign=cs, estimated_time_s=ready, target_time_s=target,
                             off_block_time_s=off_block, delay_s=max(0, target - ready) if target is not None else None,
                             status='GROUND_STOP' if stop else 'STAND_HOLD' if ac.state == AircraftState.PARKED and off_block > self.now else 'RUNWAY_SLOT'))
        return rows

    def _traffic_signature(self):
        return (self.revision, tuple(sorted(ac.callsign for ac in self._pending())),
                tuple(row['callsign'] for row in self._arrival_rows()))

    def review(self, body):
        if not isinstance(body, dict):
            raise ValueError('JSON object required.')
        self.tick()
        config = self._config(body)
        self.preview = dict(token=uuid4().hex, config=config, slots=self._rows(config),
                            signature=self._traffic_signature())
        return dict(token=self.preview['token'], config=config, slots=self.preview['slots'])

    def apply(self, token):
        self.tick()
        if not self.preview or token != self.preview['token']:
            raise ValueError('Review the program before applying it.')
        if self.preview['signature'] != self._traffic_signature():
            self.preview = None
            raise ValueError('Weather or traffic changed. Review the updated program.')
        config = self.preview['config']
        self.cancel(record=False)
        self.program = dict(**config, starts_at_s=self.now, ends_at_s=self.now + config['duration_min'] * 60,
                            status='ACTIVE')
        self._signature = None
        self.preview = None
        self.tick()
        self._record('PROGRAM_APPLIED', config['reason'])
        return self.state()

    def cancel(self, record=True):
        if record and self.program:
            self._record('PROGRAM_CANCELLED', self.program['reason'])
        self.program = None
        self.slots = []
        self.preview = None
        self._signature = None
        for ac in self.airport.sim.aircraft.values():
            ac.atfm_off_block_s = ac.atfm_ctot_s = 0
        self.airport.reader._connector.set_arrival_metering({}, None)

    def tick(self):
        if self.recovery_at_s is not None and self.now >= self.recovery_at_s:
            self.weather = preset_weather('clear')
            self.recovery_at_s = None
            self.revision += 1
            self._signature = None
            self.preview = None
            self._sync_simulation()
            self._record('WEATHER_RECOVERED', 'Scheduled return to fair weather')
        if self.program and self.now >= self.program['ends_at_s']:
            self._record('PROGRAM_EXPIRED', self.program['reason'])
            self.cancel(record=False)
        if not self.program:
            return
        signature = self._traffic_signature()
        if signature == self._signature:
            return
        self.slots = self._rows(self.program)
        self.program['status'] = ('CAPACITY_REVIEW_REQUIRED' if self.program['type'] == 'arrival_metering'
                                  and self.rates()[1] <= 0 else 'ACTIVE')
        self._signature = signature
        if self.program['type'] == 'arrival_metering':
            factors = {row['callsign']: row['speed_factor'] for row in self.slots}
            self.airport.reader._connector.set_arrival_metering(factors, self.program['ends_at_s'])
        else:
            for row in self.slots:
                ac = self.airport.sim.aircraft[row['callsign']]
                ac.atfm_off_block_s = row['off_block_time_s'] or 0
                ac.atfm_ctot_s = row['target_time_s'] or 0

    def departure_gate(self, ac, entering=False):
        """Called only before leaving a stand or entering the runway; never mid-roll."""
        dep, _ = self.rates()
        active = self.program and self.airport.sim.time_s < self.program['ends_at_s']
        if dep <= 0 or (active and self.program['type'] == 'ground_stop'):
            return False
        if not entering:
            active_departures=sum(other.operation=='dep' and other.state!=AircraftState.PARKED and not other.is_done()
                for other in self.airport.sim.aircraft.values())
            return active_departures<MAX_ACTIVE_DEPARTURES
        # Preserve the existing fair-weather baseline mechanics. Reduced
        # weather capacity or an applied program adds a release constraint.
        if not active and self.weather['capacity_factor'] == 1 and self.nominal_departures_per_hour == 60:
            return True
        spacing = 3600 / dep
        if active and self.program['type'] in ('departure_slots', 'minit'):
            spacing = max(spacing, 3600 / self.program['rate_per_hour'])
            if self.program['type'] == 'minit':
                spacing = max(spacing, self.program['minit_min'] * 60)
        if self._last_entry_s is not None and self.airport.sim.time_s - self._last_entry_s < spacing:
            return False
        return True

    def runway_entry(self, cs, time_s):
        self._last_entry_s = time_s

    def state(self):
        self.tick()
        dep, arr = self.rates()
        pending = self._pending()
        departures = sum(max(self.now, ac.off_block_time_s) + self._travel_s(ac) <= self.now + 900 for ac in pending)
        arrivals = sum(row['estimated_time_s'] <= self.now + 900 for row in self._arrival_rows())
        overloaded = departures > dep / 4 or arrivals > arr / 4
        trigger = 'DEPARTURE_CAPACITY_ZERO' if dep == 0 else 'DEMAND_EXCEEDS_CAPACITY' if overloaded else 'BALANCED'
        return dict(weather=deepcopy(self.weather), presets=[dict(key=k, label=v[0]) for k, v in PRESETS.items()],
                    tma_weather=self.tma_weather(),
                    recovery_at_s=self.recovery_at_s, sim_time_s=self.now,
                    capacity=dict(nominal_departures_per_hour=self.nominal_departures_per_hour,
                                  nominal_arrivals_per_hour=self.nominal_arrivals_per_hour,
                                  departures_per_hour=dep, arrivals_per_hour=arr),
                    demand=dict(horizon_min=15, departures=departures, arrivals=arrivals,
                                departure_slots=dep / 4, arrival_slots=arr / 4, trigger=trigger),
                    recommendation='ground_stop' if dep == 0 else 'departure_slots' if departures > dep / 4 else 'arrival_metering' if arrivals > arr / 4 else None,
                    program=deepcopy(self.program), slots=deepcopy(self.slots), history=deepcopy(self.history),
                    metrics=dict(completed_departures=sum('takeoff' in marks for marks in self.airport.milestones.values()),
                                 departures_last_15min=sum(self.now - 900 < marks.get('takeoff', -1e9) <= self.now for marks in self.airport.milestones.values()),
                                 stand_hold_s=sum(ac.flow_stand_hold_s for ac in self.airport.sim.aircraft.values()),
                                 runway_and_taxi_hold_s=sum(ac.hold_s for ac in self.airport.sim.aircraft.values() if ac.operation == 'dep'),
                                 assigned_delay_s=sum(row['delay_s'] or 0 for row in self.slots),
                                 residual_arrival_delay_s=sum(row.get('residual_delay_s') or 0 for row in self.slots)),
                    note='Simulated TMA coverage and a uniform wind proxy affect procedure speeds and ETAs. Capacity and speed reductions are study assumptions. No real radar feed, storm avoidance or runway switching; arrival metering can leave residual delay.')

    def export(self):
        return deepcopy(dict(weather=self.weather, nominal_departures_per_hour=self.nominal_departures_per_hour,
                             nominal_arrivals_per_hour=self.nominal_arrivals_per_hour,
                             recovery_at_s=self.recovery_at_s, program=self.program, slots=self.slots,
                             history=self.history, last_entry_s=self._last_entry_s))

    def restore(self, data):
        self.weather = deepcopy(data['weather'])
        self.nominal_departures_per_hour = bounded_number(data['nominal_departures_per_hour'], 'Departure rate', 1, 120)
        self.nominal_arrivals_per_hour = bounded_number(data['nominal_arrivals_per_hour'], 'Arrival rate', 1, 120)
        self.recovery_at_s = data.get('recovery_at_s')
        self.program = deepcopy(data.get('program'))
        self.slots = deepcopy(data.get('slots', []))
        self.history = deepcopy(data.get('history', []))
        self._last_entry_s = data.get('last_entry_s')
        self._signature = self._traffic_signature() if self.program else None
        self._sync_simulation()
        if self.program and self.program['type'] == 'arrival_metering':
            self.airport.reader._connector.set_arrival_metering({row['callsign']: row['speed_factor'] for row in self.slots}, self.program['ends_at_s'])
