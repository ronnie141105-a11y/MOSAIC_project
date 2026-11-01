"""Replay frames and observed DBSCAN/complexity diagnostics for Chapter 3."""
import math

from astra.airspace import configure_profile, load_profile
from astra.complexity.engine import ComplexityEngine
from astra.hotspot.engine import ClusterEngine
from astra.interface.traffic_state import AircraftState, TrafficSnapshot
from astra.utils.config import ASTRAConfig
from astra.utils.geodesy import move_position, bearing_deg


def frame(rows, now_min):
    center = load_profile('tsn_tma')['center']
    states = []
    for r in rows:
        if not r['entry_min'] <= now_min < r['exit_min']:
            continue
        elapsed = now_min-r['entry_min']
        vertices, offsets = r['trajectory_local_nm_ft'], r['trajectory_offsets_min']
        leg = 0
        while leg < len(offsets)-2 and elapsed >= offsets[leg+1]:
            leg += 1
        a, b = vertices[leg], vertices[leg+1]
        fraction = (elapsed-offsets[leg])/(offsets[leg+1]-offsets[leg])
        x, y, altitude = [a[k]+fraction*(b[k]-a[k]) for k in range(3)]
        lat, lon = move_position(center['lat'], center['lon'], math.degrees(math.atan2(x, y)), math.hypot(x, y))
        waypoints = [move_position(center['lat'], center['lon'], math.degrees(math.atan2(p[0], p[1])), math.hypot(p[0], p[1]))
                     for p in vertices[leg+1:]]
        states.append(dict(callsign=r['id'], aircraft_type=r['aircraft_type'], lat=lat, lon=lon,
            altitude_ft=altitude, heading_deg=bearing_deg(lat, lon, *waypoints[0]),
            ground_speed_kt=math.hypot(b[0]-a[0], b[1]-a[1])/(offsets[leg+1]-offsets[leg])*60,
            vertical_speed_fpm=(b[2]-a[2])/(offsets[leg+1]-offsets[leg]), route_waypoints=waypoints,
            replay_profile={'flight_type': 'SYNTHETIC_REPLAY', 'direction': 'inbound', 'synthetic': True}))
    return states


def validate_runs(runs, methods, sample_min=.5):
    cfg = configure_profile(ASTRAConfig(), 'tsn_tma')
    clusterer, complexity = ClusterEngine(cfg), ComplexityEngine(cfg)
    output = {}
    for method in methods:
        rows = runs[method]['flights']
        end = max(r['exit_min'] for r in rows)
        samples, members, peak, hotspot_frames = [], set(), 0, 0
        for k in range(math.ceil(end/sample_min)+1):
            now = k*sample_min
            snapshot = TrafficSnapshot(now*60, {
                s['callsign']: AircraftState(**{key: s[key] for key in
                    ('callsign', 'aircraft_type', 'lat', 'lon', 'altitude_ft', 'heading_deg',
                     'ground_speed_kt', 'vertical_speed_fpm')}, timestamp_s=now*60)
                for s in frame(rows, now)})
            regions = complexity.assess_many(clusterer.detect(snapshot), snapshot)
            score = max((r.complexity_score for r in regions), default=0)
            hotspots = [r for r in regions if r.complexity_score >= cfg.forecast_onset_threshold]
            peak = max(peak, score)
            hotspot_frames += bool(hotspots)
            for r in hotspots:
                members.add(tuple(sorted(r.cluster.member_callsigns)))
            samples.append(dict(time_min=now, aircraft=len(snapshot), clusters=len(regions),
                                hotspots=len(hotspots), max_complexity=score))
        output[method] = dict(sample_interval_min=sample_min, frames=len(samples),
            peak_complexity=peak, hotspot_frames=hotspot_frames,
            hotspot_memberships=[list(m) for m in sorted(members)], samples=samples,
            method='Existing MOSAIC observed DBSCAN and weighted complexity modules; no PCA fit',
            scope='Same assumed TMA paths; sampled complexity is diagnostic, separation checked continuously')
    baseline = {tuple(m) for m in output['NO_CONTROL']['hotspot_memberships']}
    for report in output.values():
        report['new_hotspot_memberships'] = [m for m in report['hotspot_memberships'] if tuple(m) not in baseline]
        report['new_hotspot_definition'] = 'Exact member set absent from all uncontrolled frames; diagnostic only, not included in GA fitness'
    for method, report in output.items():
        report['accepted_in_study'] = bool(runs[method]['metrics']['feasible_in_synthetic_tma'] and not report['new_hotspot_memberships'])
    return output
