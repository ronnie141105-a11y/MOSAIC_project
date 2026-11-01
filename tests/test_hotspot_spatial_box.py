"""
Regression tests -- static hotspot spatial shape, v3: anchored on
predicted loss of separation between a pair of aircraft, using the
standard "either/or" 10 NM / 1000 ft separation rule
(`astra.hotspot.spatial_box`).

Run with:
    python3 tests/test_hotspot_spatial_box.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from astra.hotspot.spatial_box import (
    _build_route_vertices,
    _pairwise_conflict_window,
    compute_hotspot_box,
)
from astra.interface.traffic_state import AircraftState, TrafficSnapshot
from astra.tracking.models import FourDArhac
from astra.utils.config import ASTRAConfig
from tests._runner import Runner


def _aircraft(callsign, lat, lon, hdg=90.0, gs=450.0, alt_ft=35000.0, vs_fpm=0.0):
    return AircraftState(
        callsign=callsign,
        lat=lat,
        lon=lon,
        altitude_ft=alt_ft,
        ground_speed_kt=gs,
        heading_deg=hdg,
        vertical_speed_fpm=vs_fpm,
        aircraft_type="A320",
        timestamp_s=0.0,
    )


def _track(members, arhac_id="T1", peak_complexity=70.0):
    return FourDArhac(
        arhac_id=arhac_id,
        status="GROWING",
        track=[],
        provisional_track=[],
        member_aircraft=frozenset(members),
        peak_complexity=peak_complexity,
    )


def _no_route_vertices(ac):
    """Vertices for the no-known-route (pure dead-reckoning) case,
    matching what `_overall_conflict_window` would build."""
    return _build_route_vertices(ac.lat, ac.lon, None)


def test_head_on_same_altitude_produces_a_conflict_window(r: Runner) -> None:
    """Two aircraft closing head-on at the same altitude will genuinely
    violate both minima at their meeting point -- a window must be
    found, bracketing that event."""
    config = ASTRAConfig()
    ac_a = _aircraft("A1", 10.0, 106.0, hdg=90.0, gs=450.0, alt_ft=35000.0)
    ac_b = _aircraft("A2", 10.0, 107.0, hdg=270.0, gs=450.0, alt_ft=35000.0)
    window = _pairwise_conflict_window(ac_a, _no_route_vertices(ac_a), ac_b, _no_route_vertices(ac_b), config, max_horizon_s=3600.0)

    r.check("a conflict window was found", window is not None)
    if window:
        t_start, t_end = window
        r.check(f"start brackets the buffer entry (~160s, got {t_start:.0f}s)", 130 <= t_start <= 190)
        r.check(f"end brackets the buffer exit (~320s, got {t_end:.0f}s)", 290 <= t_end <= 350)


def test_no_conflict_when_vertically_separated(r: Runner) -> None:
    """Two aircraft closing to 0 NM horizontally but with a full 5000 ft
    vertical separation the whole time are NEVER in genuine conflict --
    one of the two separation standards is satisfied throughout."""
    config = ASTRAConfig()
    ac_a = _aircraft("A1", 10.0, 106.0, hdg=90.0, gs=450.0, alt_ft=35000.0)
    ac_b = _aircraft("A2", 10.0, 107.0, hdg=270.0, gs=450.0, alt_ft=40000.0)
    window = _pairwise_conflict_window(ac_a, _no_route_vertices(ac_a), ac_b, _no_route_vertices(ac_b), config, max_horizon_s=3600.0)
    r.check("no conflict window -- vertical separation holds throughout", window is None)


def test_no_conflict_when_horizontally_separated(r: Runner) -> None:
    """Two aircraft converging in altitude to the same level, but never
    closer than 10 NM horizontally, are never in genuine conflict."""
    config = ASTRAConfig()
    ac_a = _aircraft("A1", 10.0, 106.0, hdg=90.0, gs=450.0, alt_ft=35000.0, vs_fpm=0.0)
    ac_b = _aircraft("A2", 10.5, 106.0, hdg=90.0, gs=450.0, alt_ft=36000.0, vs_fpm=-200.0)
    window = _pairwise_conflict_window(ac_a, _no_route_vertices(ac_a), ac_b, _no_route_vertices(ac_b), config, max_horizon_s=3600.0)
    r.check("no conflict window -- horizontal separation holds throughout", window is None)


def test_no_conflict_when_diverging(r: Runner) -> None:
    """Two aircraft already far apart and flying directly away from
    each other never come anywhere near either minimum -- no window."""
    config = ASTRAConfig()
    ac_a = _aircraft("A1", 10.0, 106.0, hdg=270.0, gs=450.0, alt_ft=35000.0)
    ac_b = _aircraft("A2", 10.0, 107.0, hdg=90.0, gs=450.0, alt_ft=35000.0)
    window = _pairwise_conflict_window(ac_a, _no_route_vertices(ac_a), ac_b, _no_route_vertices(ac_b), config, max_horizon_s=3600.0)
    r.check("no conflict window -- already diverging", window is None)


def test_conflict_window_respects_configured_thresholds(r: Runner) -> None:
    """Tightening the buffer/minima thresholds changes the detected
    window -- this is a real, configurable rule, not a hardcoded
    result."""
    config_default = ASTRAConfig()
    config_tight = ASTRAConfig(
        conflict_horizontal_min_nm=2.0,
        hotspot_horizontal_buffer_nm=4.0,
    )
    ac_a = _aircraft("A1", 10.0, 106.0, hdg=90.0, gs=450.0, alt_ft=35000.0)
    ac_b = _aircraft("A2", 10.0, 107.0, hdg=270.0, gs=450.0, alt_ft=35000.0)
    window_default = _pairwise_conflict_window(ac_a, _no_route_vertices(ac_a), ac_b, _no_route_vertices(ac_b), config_default, 3600.0)
    window_tight = _pairwise_conflict_window(ac_a, _no_route_vertices(ac_a), ac_b, _no_route_vertices(ac_b), config_tight, 3600.0)
    r.check("default (wider buffer) window found", window_default is not None)
    r.check("tighter-threshold window found", window_tight is not None)
    if window_default and window_tight:
        r.check(
            "the tighter threshold produces a narrower (shorter) window",
            (window_tight[1] - window_tight[0]) < (window_default[1] - window_default[0]),
        )


def test_no_shape_with_fewer_than_two_members(r: Runner) -> None:
    """A track needs at least a pair to even ask "will they lose
    separation?"."""
    config = ASTRAConfig()
    snapshot = TrafficSnapshot(timestamp_s=0.0, aircraft={"A1": _aircraft("A1", 10.0, 106.0)})
    track = _track(["A1"])
    box = compute_hotspot_box(track, snapshot, {}, config)
    r.check("no shape with only one member", box is None)


def test_no_shape_when_no_pair_actually_conflicts(r: Runner) -> None:
    """A cluster whose members never actually violate real separation
    minima (e.g. well vertically separated the whole time) gets no
    shape at all -- this is a deliberate behaviour change from the
    old complexity-based design: elevated complexity alone is no
    longer enough, a genuine predicted loss of separation is required."""
    config = ASTRAConfig()
    snapshot = TrafficSnapshot(
        timestamp_s=0.0,
        aircraft={
            "A1": _aircraft("A1", 10.0, 106.0, hdg=90.0, alt_ft=35000.0),
            "A2": _aircraft("A2", 10.0, 107.0, hdg=270.0, alt_ft=40000.0),
        },
    )
    track = _track(["A1", "A2"])
    box = compute_hotspot_box(track, snapshot, {}, config)
    r.check("no shape -- vertically separated the whole time", box is None)


def test_shape_computed_for_a_genuine_conflict(r: Runner) -> None:
    """The core case: two aircraft genuinely predicted to lose
    separation get a shape, anchored on the buffer window."""
    config = ASTRAConfig()
    snapshot = TrafficSnapshot(
        timestamp_s=1000.0,
        aircraft={
            "A1": _aircraft("A1", 10.0, 106.0, hdg=90.0, alt_ft=35000.0),
            "A2": _aircraft("A2", 10.0, 107.0, hdg=270.0, alt_ft=35000.0),
        },
    )
    track = _track(["A1", "A2"])
    box = compute_hotspot_box(track, snapshot, {}, config)
    r.check("shape computed", box is not None)
    r.check(
        "both aircraft identified as the pair",
        box is not None and {box.left_callsign, box.right_callsign} == {"A1", "A2"},
    )
    r.check("start_time_s is after the snapshot time", box is not None and box.start_time_s > 1000.0)
    r.check("end_time_s is after start_time_s", box is not None and box.end_time_s > box.start_time_s)
    r.check(
        "member_callsigns includes both aircraft",
        box is not None and box.member_callsigns == frozenset({"A1", "A2"}),
    )


def test_shape_follows_actual_route_waypoints(r: Runner) -> None:
    """With a known route, the drawn shape has real geometry on both
    edges (both edges traced from the actual route/trajectory, not a
    degenerate placeholder)."""
    config = ASTRAConfig()
    snapshot = TrafficSnapshot(
        timestamp_s=0.0,
        aircraft={
            "A1": _aircraft("A1", 10.0, 106.0, hdg=90.0, gs=450.0, alt_ft=35000.0),
            "A2": _aircraft("A2", 10.0, 107.0, hdg=270.0, gs=450.0, alt_ft=35000.0),
        },
    )
    routes = {"A2": [(10.0, 106.6), (10.5, 106.6)]}
    track = _track(["A1", "A2"])
    box = compute_hotspot_box(track, snapshot, routes, config)
    r.check("shape computed", box is not None)
    r.check("at least 4 polygon points (both edges have >=2 points)", box is not None and len(box.polygon) >= 4)


def test_two_aircraft_on_same_track_get_a_visible_corridor(r: Runner) -> None:
    """Two aircraft on the same track (one following the other) that
    will genuinely close within both minima must still get a visible
    corridor, not a degenerate zero-width line."""
    config = ASTRAConfig()
    snapshot = TrafficSnapshot(
        timestamp_s=0.0,
        aircraft={
            "A1": _aircraft("A1", 47.00, 8.0, hdg=90.0, gs=480.0, alt_ft=35000.0),
            "A2": _aircraft("A2", 47.00, 8.2, hdg=90.0, gs=420.0, alt_ft=35000.0),
        },
    )
    track = _track(["A1", "A2"])
    box = compute_hotspot_box(track, snapshot, {}, config)
    r.check("shape computed", box is not None)
    if box:
        lats = [lat for lat, _ in box.polygon]
        r.check(
            "corridor has real, visible lateral width (not a degenerate line)",
            (max(lats) - min(lats)) > 0.02,
        )


def test_union_picks_the_conflicting_pair_in_a_larger_cluster(r: Runner) -> None:
    """A 3-aircraft cluster where only one pair actually conflicts --
    the shape must be anchored on that pair specifically, and every
    present member still listed in member_callsigns."""
    config = ASTRAConfig()
    snapshot = TrafficSnapshot(
        timestamp_s=0.0,
        aircraft={
            "A1": _aircraft("A1", 10.0, 106.0, hdg=90.0, gs=450.0, alt_ft=35000.0),
            "A2": _aircraft("A2", 10.0, 107.0, hdg=270.0, gs=450.0, alt_ft=35000.0),
            "A3": _aircraft("A3", 20.0, 120.0, hdg=45.0, gs=450.0, alt_ft=41000.0),
        },
    )
    track = _track(["A1", "A2", "A3"])
    box = compute_hotspot_box(track, snapshot, {}, config)
    r.check("shape computed", box is not None)
    r.check(
        "anchored on the genuinely conflicting pair (A1/A2), not A3",
        box is not None and {box.left_callsign, box.right_callsign} == {"A1", "A2"},
    )
    r.check(
        "member_callsigns lists every present member, including the uninvolved A3",
        box is not None and box.member_callsigns == frozenset({"A1", "A2", "A3"}),
    )


def test_config_validation_for_conflict_thresholds(r: Runner) -> None:
    """Buffer thresholds must be >= the real minima they buffer around."""
    r.check_raises(
        "horizontal buffer < minimum raises ValueError",
        lambda: ASTRAConfig(conflict_horizontal_min_nm=10.0, hotspot_horizontal_buffer_nm=5.0),
        ValueError,
    )
    r.check_raises(
        "vertical buffer < minimum raises ValueError",
        lambda: ASTRAConfig(conflict_vertical_min_ft=1000.0, hotspot_vertical_buffer_ft=500.0),
        ValueError,
    )
    r.check_raises(
        "non-positive horizontal minimum raises ValueError",
        lambda: ASTRAConfig(conflict_horizontal_min_nm=0.0),
        ValueError,
    )
    r.check_raises(
        "non-positive sample step raises ValueError",
        lambda: ASTRAConfig(hotspot_conflict_sample_step_s=0.0),
        ValueError,
    )


def main() -> None:
    r = Runner("Dashboard visual-spec update v3 — separation-loss-anchored hotspot shape")
    test_head_on_same_altitude_produces_a_conflict_window(r)
    test_no_conflict_when_vertically_separated(r)
    test_no_conflict_when_horizontally_separated(r)
    test_no_conflict_when_diverging(r)
    test_conflict_window_respects_configured_thresholds(r)
    test_no_shape_with_fewer_than_two_members(r)
    test_no_shape_when_no_pair_actually_conflicts(r)
    test_shape_computed_for_a_genuine_conflict(r)
    test_shape_follows_actual_route_waypoints(r)
    test_two_aircraft_on_same_track_get_a_visible_corridor(r)
    test_union_picks_the_conflicting_pair_in_a_larger_cluster(r)
    test_config_validation_for_conflict_thresholds(r)
    r.summary()


if __name__ == "__main__":
    main()
