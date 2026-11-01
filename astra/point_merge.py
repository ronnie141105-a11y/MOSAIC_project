"""Mock 25R point-merge direct-to planning and spacing checks.

The published STAR arcs remain available. A controller may release an arrival
from its arc to SOKAN or BOMSU once the proposed route keeps spacing from
aircraft already released to the shared approach.
"""
from copy import deepcopy
from functools import lru_cache
from math import isfinite

from astra.airspace import load_profile
from astra.interface.traffic_state import AircraftState
from astra.trajectory.procedure import advance_procedure
from astra.utils.geodesy import bearing_deg, haversine_distance_nm

HORIZONTAL_MIN_NM = 10.0
SAME_TRACK_MIN_NM = 20.0
MAX_VERTICAL_RATE_FPM = 2000.0
SAMPLE_STEP_S = 15.0
MAX_CHECK_S = 18 * 60.0

# The STAR fix catalogue spells the team's "TS62" as TS462.
ARCS = {
    'H_WEST': ('VANLI', 'TS488', 'RUNSI', 'TS458', 'TS456', 'TS454'),
    'H_NORTH': ('VIKEP', 'TS452', 'TS438', 'TS436', 'TS434', 'TS432'),
    'J_NORTH': ('ANSUP', 'TS448', 'TS446', 'TS444', 'TS442'),
    'J_EAST': ('TS468', 'TS466', 'TS464', 'TS462'),
}


@lru_cache(maxsize=32)
def arc_for_procedure(procedure_id):
    proc = load_profile('tsn_tma')['procedure_data'].get(procedure_id)
    if not proc or proc['kind'] != 'star':
        return None
    names = [leg['fix'] for leg in proc['legs']]
    merge = names[-1]
    candidates = []
    for arc in ARCS.values():
        matches = [fix for fix in arc if fix in names]
        if len(matches) >= 2 and names.index(matches[0]) < names.index(matches[-1]):
            candidates.append((len(matches), arc))
    if not candidates:
        return None
    arc = max(candidates, key=lambda item: item[0])[1]
    if merge not in ('SOKAN', 'BOMSU'):
        return None
    return arc, merge


def _state(record, time_s):
    return AircraftState(record.callsign, record.lat, record.lon,
                         record.altitude_ft, record.ground_speed_kt,
                         record.heading_deg, record.vertical_speed_fpm,
                         record.aircraft_type, time_s)


def _committed(record):
    profile = record.procedure_profile or {}
    if profile.get('direction') != 'inbound':
        return False
    if profile.get('point_merge_cleared'):
        return True
    first = (profile.get('legs') or [{}])[0].get('fix')
    return first in {'TS426', 'TS424', 'TS422', 'RW25R', 'TD25R'}


def _spacing_conflict(candidate, candidate_route, candidate_profile, peer, now_s):
    a = _state(candidate, now_s)
    b = _state(peer, now_s)
    a_route, b_route = list(candidate_route), list(peer.route_waypoints or [])
    a_profile, b_profile = deepcopy(candidate_profile), deepcopy(peer.procedure_profile)
    for tick in range(1, int(MAX_CHECK_S / SAMPLE_STEP_S) + 1):
        a_step = advance_procedure(a, a_route, a_profile, SAMPLE_STEP_S)
        b_step = advance_procedure(b, b_route, b_profile, SAMPLE_STEP_S)
        a, a_route, a_profile = a_step.aircraft, a_step.remaining_route, a_step.profile
        b, b_route, b_profile = b_step.aircraft, b_step.remaining_route, b_step.profile
        if a_step.completed or b_step.completed:
            break
        distance = haversine_distance_nm(a.lat, a.lon, b.lat, b.lon)
        angle = abs((a.heading_deg - b.heading_deg + 180) % 360 - 180)
        minimum = SAME_TRACK_MIN_NM if angle <= 25 else HORIZONTAL_MIN_NM
        if distance < minimum:
            return peer.callsign, round(distance, 1), minimum
    return None


def plan_clearance(record, records, now_s):
    """Return public decision plus the route/profile to install if safe."""
    profile = record.procedure_profile or {}
    result = {'callsign': record.callsign, 'available': False, 'safe': False,
              'merge_fix': None, 'reason': 'Choose an active 25R STAR arrival.'}
    if profile.get('direction') != 'inbound' or profile.get('runway') != '25R':
        return result, None, None
    arc_info = arc_for_procedure(profile.get('procedure_id'))
    if arc_info is None:
        return result, None, None
    arc, merge = arc_info
    result['merge_fix'] = merge
    if profile.get('point_merge_cleared'):
        result['reason'] = f'Already cleared direct to {merge}.'
        return result, None, None
    route = list(record.route_waypoints or [])
    legs = profile.get('legs') or []
    if len(route) != len(legs):
        result['reason'] = 'Procedure route and legs are out of sync.'
        return result, None, None
    fixes = [leg.get('fix') for leg in legs]
    if merge not in fixes:
        result['reason'] = f'Aircraft has passed {merge}.'
        return result, None, None
    index = fixes.index(merge)
    next_fix = fixes[0]
    if next_fix not in arc[1:] and next_fix != merge:
        result['reason'] = f'Wait until the aircraft enters the {arc[0]}–{arc[-1]} merge arc.'
        return result, None, None
    result['available'] = True
    merge_leg = legs[index]
    merge_lat, merge_lon = route[index]
    distance_nm = haversine_distance_nm(record.lat, record.lon, merge_lat, merge_lon)
    speed = min(230.0, merge_leg.get('max_ias_kt') or 230.0)
    if not isfinite(speed) or speed <= 0 or distance_nm <= 0:
        result['reason'] = 'No valid direct leg remains.'
        return result, None, None
    travel_s = distance_nm / speed * 3600.0
    target_ft = merge_leg['target_altitude_ft']
    required_fpm = abs(target_ft - record.altitude_ft) / travel_s * 60.0
    if required_fpm > MAX_VERTICAL_RATE_FPM + 1e-6:
        result['reason'] = f'Cannot reach the {merge} altitude at 2,000 ft/min from this position.'
        return result, None, None
    proposed_route = route[index:]
    proposed_profile = deepcopy(profile)
    proposed_profile['legs'] = deepcopy(legs[index:])
    proposed_profile['legs'][0]['nominal_speed_kt'] = 230.0
    proposed_profile['point_merge_cleared'] = True
    proposed_profile['point_merge_fix'] = merge
    proposed_profile['point_merge_cleared_at_s'] = now_s
    for peer in records:
        if peer.callsign == record.callsign or not _committed(peer):
            continue
        conflict = _spacing_conflict(record, proposed_route, proposed_profile, peer, now_s)
        if conflict:
            peer_id, distance, minimum = conflict
            result['reason'] = (f'Hold on the arc: predicted {distance} NM from {peer_id}; '
                                f'{minimum:.0f} NM required.')
            return result, None, None
    result.update(safe=True, reason=f'Clear direct {merge}; target altitude {round(target_ft):,} ft.',
                  target_altitude_ft=round(target_ft),
                  next_arc_fix=next_fix)
    return result, proposed_route, proposed_profile
