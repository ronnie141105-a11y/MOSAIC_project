"""Thread-safe bridge from the simulation cycle to browser responses."""

import threading
from math import hypot

from astra.dashboard.models import DashboardSnapshot
from astra.pipeline import CycleResult


class CycleStore:
    """Holds the latest `CycleResult`, safe for one writer + many readers.

    Example::

        store = CycleStore()
        # poll loop thread:
        store.update(pipeline.run_cycle(snapshot))
        # Flask request-handling thread(s):
        snapshot = store.snapshot()
    """

    def __init__(self) -> None:
        """Start with an empty snapshot (no cycle has run yet)."""
        self._lock = threading.Lock()
        self._snapshot = DashboardSnapshot.empty()
        self._trail_paths: dict[str, list[dict]] = {}
        self._trail_time: float | None = None
        self._trail_generation = 0

    def update(self, cycle_result: CycleResult) -> None:
        """Publish a newly-completed cycle. Called once per poll cycle.

        Args:
            cycle_result: The result of the `Pipeline.run_cycle()` call
                that just completed.
        """
        with self._lock:
            observed = cycle_result.snapshot
            time_s = observed.timestamp_s
            if self._trail_time is not None and time_s < self._trail_time:
                self._clear_trails_locked()
            active = set(observed.aircraft)
            for callsign in list(self._trail_paths):
                if callsign not in active:
                    del self._trail_paths[callsign]
            for ac in observed:
                path = self._trail_paths.setdefault(ac.callsign, [])
                if path and hypot(ac.lat - path[-1]["lat"], ac.lon - path[-1]["lon"]) > 0.1:
                    path.clear()
                point = {"lat": ac.lat, "lon": ac.lon, "time_s": time_s}
                if path and path[-1]["time_s"] == time_s:
                    path[-1] = point
                else:
                    path.append(point)
                    if len(path) > 1800:
                        del path[:-1800]
            self._trail_time = time_s
            self._snapshot = DashboardSnapshot(
                cycle_result=cycle_result,
                cycle_count=self._snapshot.cycle_count + 1,
                updated_at_s=cycle_result.snapshot.timestamp_s,
            )

    def _clear_trails_locked(self) -> None:
        self._trail_paths.clear()
        self._trail_time = None
        self._trail_generation += 1

    def clear_trails(self) -> None:
        """Discard observed tracks when a new simulation scenario starts."""
        with self._lock:
            self._clear_trails_locked()

    def trails(self) -> dict:
        """Return one independent copy for a newly opened dashboard page."""
        with self._lock:
            return {
                "generation": self._trail_generation,
                "timestamp_s": self._trail_time,
                "paths": {callsign: [point.copy() for point in path]
                          for callsign, path in self._trail_paths.items()},
            }

    @property
    def trail_generation(self) -> int:
        with self._lock:
            return self._trail_generation

    def seed_replay_trails(self, paths: dict, time_s: float) -> None:
        """Restore past scenario positions so a seek has an existing trail."""
        with self._lock:
            self._clear_trails_locked()
            self._trail_paths = {cs: [dict(p) for p in points if p['time_s'] <= time_s][-1800:]
                                 for cs, points in paths.items()}
            self._trail_time = time_s

    def snapshot(self) -> DashboardSnapshot:
        """Return the latest published `DashboardSnapshot`.

        Returns:
            `DashboardSnapshot.empty()` if `update()` has never been
            called (no cycle has completed yet).
        """
        with self._lock:
            return self._snapshot
