"""Trajectory-derived polygons for the earliest continuous interaction episode."""
from dataclasses import replace
from itertools import combinations
from scipy.spatial import ConvexHull
from astra.hotspot.spatial_box import HotspotBox
from astra.trajectory.route_engine import RouteAwareTrajectoryEngine
from astra.utils.geodesy import haversine_distance_nm, move_position


def sample_trajectories(snapshot, routes, profiles, config):
    """One shared route/vertical-intent timeline for all tracks."""
    step = config.hotspot_conflict_sample_step_s
    end = config.max_prediction_horizon_min * 60.0
    times = sorted({0.0, end} | {i * step for i in range(1, int(end / step) + 1)})
    cfg = replace(config, airspace_profile='sampled', prediction_horizons_min=[t / 60 for t in times])
    engine = RouteAwareTrajectoryEngine(cfg, routes.get, profiles.get)
    prediction = engine.predict(snapshot)
    return [(h * 60, prediction.at(h)) for h in prediction.horizon_list()]


def compute_procedure_box(track, snapshot, routes, profiles, config, timeline=None):
    if len(track.member_aircraft) < 2 or getattr(track, 'status', None) == 'CLOSED':
        return None
    timeline = timeline if timeline is not None else sample_trajectories(snapshot, routes, profiles, config)
    hits = []
    horizontal = min(config.hotspot_horizontal_buffer_nm, config.conflict_horizontal_min_nm * 1.5)
    vertical = min(config.hotspot_vertical_buffer_ft, config.conflict_vertical_min_ft * 1.5)
    for t, predicted in timeline:
        states = [ac for ac in predicted if ac.callsign in track.member_aircraft
                  and (config.assessment_volume is None or config.assessment_volume.contains(ac))]
        pairs = [(a, b) for a, b in combinations(states, 2)
                 if abs(a.altitude_ft - b.altitude_ft) < vertical
                 and haversine_distance_nm(a.lat, a.lon, b.lat, b.lon) < horizontal]
        # Dense crossing/climbing flows can create workload before minima are
        # approached. Require several aircraft and heading/vertical diversity;
        # a spread-out parallel stream alone does not paint a workload area.
        if len(states) >= 3:
            for a, b in combinations(states, 2):
                angle = abs((a.heading_deg - b.heading_deg + 180) % 360 - 180)
                if (angle >= 30 or abs(a.vertical_speed_fpm - b.vertical_speed_fpm) >= 500):
                    if (abs(a.altitude_ft - b.altitude_ft) < config.separation_vertical_ft
                            and haversine_distance_nm(a.lat, a.lon, b.lat, b.lon) < config.separation_horizontal_nm
                            and (a, b) not in pairs):
                        pairs.append((a, b))
        if pairs:
            hits.append((t, pairs))
        elif hits:
            break  # Never bridge a resolved encounter to a later episode.
    if not hits:
        return None
    points = []
    members = set()
    for _, pairs in hits:
        for a, b in pairs:
            for ac in (a, b):
                members.add(ac.callsign)
                points.extend(move_position(ac.lat, ac.lon, bearing, config.hotspot_polygon_padding_nm)
                              for bearing in range(0, 360, 45))
    unique = sorted(set(points))
    hull = ConvexHull(unique)
    polygon = [unique[i] for i in hull.vertices]
    a, b = hits[0][1][0]
    return HotspotBox(track.arhac_id, snapshot.timestamp_s + hits[0][0],
                      snapshot.timestamp_s + hits[-1][0], polygon, a.callsign, b.callsign,
                      frozenset(members), getattr(track, 'predicted_peak_complexity', None) or track.peak_complexity)
