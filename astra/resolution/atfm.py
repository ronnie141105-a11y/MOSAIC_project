"""Deterministic ATFM coordination proposals at shared procedure fixes.

Schedules include all known traffic using a fix, not only hotspot members.
These are target times for coordination, not executable tactical clearances.
"""
from collections import defaultdict
from astra.utils.geodesy import haversine_distance_nm


def plan_measures(track, snapshot, route_provider, profile_provider, config):
    if track.status == 'CLOSED' or route_provider is None or profile_provider is None:
        return []
    fixes = defaultdict(list)
    for ac in snapshot:
        route = route_provider(ac.callsign) or []
        profile = profile_provider(ac.callsign) or {}
        legs = profile.get('legs', [])
        if profile.get('flight_type') != 'PROCEDURE' or len(legs) != len(route):
            continue
        lat, lon = ac.lat, ac.lon
        eta = snapshot.timestamp_s
        for point, leg in zip(route, legs):
            speed = leg.get('nominal_speed_kt') or ac.ground_speed_kt
            if leg.get('max_ias_kt') is not None:
                speed = min(speed, leg['max_ias_kt'])
            if speed <= 0:
                break
            eta += haversine_distance_nm(lat, lon, *point) / speed * 3600
            lat, lon = point
            if eta - snapshot.timestamp_s > config.max_prediction_horizon_min * 60:
                break
            fixes[(round(lat, 5), round(lon, 5))].append((eta, ac.callsign, profile, leg))
    # Select the earliest bottleneck with at least two hotspot members. A
    # single coordination point avoids contradictory independently timed slots.
    bottlenecks = [(min(e[0] for e in entries), point, entries) for point, entries in fixes.items()
                   if len({e[1] for e in entries} & set(track.member_aircraft)) >= 2]
    if not bottlenecks:
        return []
    _, point, entries = min(bottlenecks, key=lambda item: (item[0], item[1]))
    measures = []
    previous = float('-inf')
    seen = set()
    for eta, cs, profile, leg in sorted(entries, key=lambda e: (e[0], e[1])):
        if cs in seen:
            continue
        seen.add(cs)
        target = max(eta, previous + config.atfm_spacing_s)
        previous = target
        delay = target - eta
        if cs not in track.member_aircraft or delay < 1:
            continue
        direction = profile.get('direction')
        kind = 'ARRIVAL_METERING' if direction == 'inbound' else 'DEPARTURE_RELEASE_COORDINATION'
        measures.append(dict(
            measure_type=kind, target_callsign=cs,
            fix=leg.get('fix') or leg.get('name') or 'Shared procedure fix',
            lat=point[0], lon=point[1], estimated_time_s=eta, target_time_s=target,
            delay_s=delay, spacing_s=config.atfm_spacing_s,
            status='COORDINATION_REQUIRED' if delay <= config.atfm_max_delay_s else 'CAPACITY_REVIEW_REQUIRED',
            planning_only=True,
            rationale=('Coordinate upstream arrival timing; retain the published procedure.' if direction == 'inbound'
                       else 'Coordinate future departure releases upstream; this airborne flight cannot receive a ground hold.'),
        ))
    if measures:
        measures.append(dict(measure_type='FLOW_RATE', target_callsign=None,
            fix=measures[0]['fix'], lat=point[0], lon=point[1],
            target_rate_per_hour=3600 / config.atfm_spacing_s,
            spacing_s=config.atfm_spacing_s, status='COORDINATION_REQUIRED', planning_only=True,
            rationale='Study flow-rate target at this bottleneck; validate against runway and sector capacity.'))
    return measures
