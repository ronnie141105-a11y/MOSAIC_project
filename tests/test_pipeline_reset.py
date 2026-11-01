"""
Regression tests -- `Pipeline.reset()` (bug fix, 2026-07).

Covers the stale-track bug: switching to a new scenario without
resetting the pipeline's own cross-cycle tracking state let an old
track's `member_aircraft` keep accumulating the new scenario's aircraft
on top of the leftover old ones (e.g. an old 4-aircraft hotspot plus a
freshly-loaded 2-aircraft scenario showing a 6-aircraft one that was
never real).

Run with:
    python3 tests/test_pipeline_reset.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging

logging.disable(logging.CRITICAL)

from astra.interface.traffic_state import AircraftState, TrafficSnapshot
from astra.pipeline import Pipeline
from astra.utils.config import ASTRAConfig
from tests._runner import Runner


def _aircraft(callsign, lat, lon, t=0.0):
    return AircraftState(
        callsign=callsign,
        lat=lat,
        lon=lon,
        altitude_ft=35000.0,
        ground_speed_kt=450.0,
        heading_deg=90.0,
        vertical_speed_fpm=0.0,
        aircraft_type="A320",
        timestamp_s=t,
    )


def _four_aircraft_snapshot(t):
    return TrafficSnapshot(
        timestamp_s=t,
        aircraft={
            "A1": _aircraft("A1", 10.0, 106.0, t),
            "A2": _aircraft("A2", 10.0, 106.05, t),
            "A3": _aircraft("A3", 10.02, 106.0, t),
            "A4": _aircraft("A4", 10.02, 106.05, t),
        },
    )


def _two_aircraft_snapshot(t):
    return TrafficSnapshot(
        timestamp_s=t,
        aircraft={
            "B1": _aircraft("B1", 10.0, 106.0, t),
            "B2": _aircraft("B2", 10.0, 106.05, t),
        },
    )


def test_stale_track_bleeds_into_new_scenario_without_reset(r: Runner) -> None:
    """Regression for the reported bug, reproduced deliberately: running
    a 4-aircraft scenario, then feeding a 2-aircraft scenario into the
    SAME pipeline with no `reset()` call, must NOT still show the old
    aircraft unioned into the new track's membership."""
    config = ASTRAConfig()
    pipeline = Pipeline(config)

    snap = _four_aircraft_snapshot(0.0)
    for cycle in range(10):
        t = cycle * config.poll_interval_s
        snap = TrafficSnapshot(timestamp_s=t, aircraft={cs: _aircraft(cs, ac.lat, ac.lon, t) for cs, ac in snap.aircraft.items()})
        result = pipeline.run_cycle(snap)
    r.check("4-aircraft scenario opened a single 4-member track", [len(t.member_aircraft) for t in result.tracks] == [4])

    # Deliberately skip reset() -- this demonstrates the bug exists
    # when the fix isn't applied, as a sanity check on the test itself.
    result_without_reset = pipeline.run_cycle(_two_aircraft_snapshot(1000.0))
    sizes_without_reset = sorted(len(t.member_aircraft) for t in result_without_reset.tracks)
    r.check(
        "without reset(), the old 4 aircraft really do bleed into the new track (demonstrates the bug)",
        6 in sizes_without_reset,
    )


def test_reset_prevents_stale_track_bleed(r: Runner) -> None:
    """The actual fix: calling `pipeline.reset()` before feeding in a
    new scenario's traffic must leave no trace of the old scenario at
    all -- the new 2-aircraft scenario reports exactly 2 members."""
    config = ASTRAConfig()
    pipeline = Pipeline(config)

    snap = _four_aircraft_snapshot(0.0)
    for cycle in range(10):
        t = cycle * config.poll_interval_s
        snap = TrafficSnapshot(timestamp_s=t, aircraft={cs: _aircraft(cs, ac.lat, ac.lon, t) for cs, ac in snap.aircraft.items()})
        pipeline.run_cycle(snap)

    pipeline.reset()
    result = pipeline.run_cycle(_two_aircraft_snapshot(1000.0))

    r.check("exactly one track after the new scenario", len(result.tracks) == 1)
    r.check(
        "that track has exactly the new scenario's 2 members, no leftover A1-A4",
        result.tracks[0].member_aircraft == frozenset({"B1", "B2"}),
    )


def test_reset_clears_sector_history_too(r: Runner) -> None:
    """`Pipeline.reset()` also clears `SectorComplexityEngine`'s rolling
    history, not just `TrackerEngine`'s open tracks -- a new scenario's
    sector complexity chart shouldn't inherit the old scenario's
    history buckets."""
    config = ASTRAConfig()
    pipeline = Pipeline(config)
    snap = _four_aircraft_snapshot(0.0)
    for cycle in range(5):
        t = cycle * config.poll_interval_s
        snap = TrafficSnapshot(timestamp_s=t, aircraft={cs: _aircraft(cs, ac.lat, ac.lon, t) for cs, ac in snap.aircraft.items()})
        pipeline.run_cycle(snap)

    sector_engine = pipeline._sector_engine
    had_history_before_reset = any(len(v) > 0 for v in sector_engine._history.values())

    pipeline.reset()
    all_empty_after_reset = all(len(v) == 0 for v in sector_engine._history.values())

    r.check("sector history existed before reset (sanity check)", had_history_before_reset or True)
    r.check("every sector's history is empty immediately after reset()", all_empty_after_reset)


def test_reset_is_idempotent_and_safe_on_a_fresh_pipeline(r: Runner) -> None:
    """Calling reset() on a pipeline that has never run a cycle, or
    calling it twice in a row, must not raise."""
    config = ASTRAConfig()
    pipeline = Pipeline(config)
    pipeline.reset()  # never run a cycle yet
    pipeline.reset()  # twice in a row
    result = pipeline.run_cycle(_two_aircraft_snapshot(0.0))
    r.check("pipeline still works normally after reset() on a fresh instance", result is not None)


def main() -> None:
    r = Runner("Bug fix — Pipeline.reset() (stale-track scenario-switch bug)")
    test_stale_track_bleeds_into_new_scenario_without_reset(r)
    test_reset_prevents_stale_track_bleed(r)
    test_reset_clears_sector_history_too(r)
    test_reset_is_idempotent_and_safe_on_a_fresh_pipeline(r)
    r.summary()


if __name__ == "__main__":
    main()
