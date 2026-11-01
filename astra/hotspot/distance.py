"""
Custom pairwise distance metric for cluster detection (Milestone 3).

Aircraft are DBSCAN neighbours only if within BOTH a horizontal (NM,
great-circle) and vertical (ft) threshold. See this module's own docstring
for why this needs a precomputed matrix rather than a blended scalar.
"""

from typing import Sequence

import numpy as np

from astra.interface.traffic_state import AircraftState

#: Assigned to any pair failing the vertical gate. Must be finite (DBSCAN
#: rejects inf) and larger than any realistic eps (Earth's circumference
#: is ~21 600 NM).
_NON_NEIGHBOR_DISTANCE = 1.0e9

#: Earth mean radius in nautical miles -- same value as
#: `astra.utils.geodesy._EARTH_RADIUS_NM`. Deliberately re-declared
#: rather than imported: `geodesy` is documented (see that module's own
#: docstring) to stay numpy-free on purpose, so unit tests can import it
#: without installing simulation dependencies -- this module already
#: depends on numpy (DBSCAN needs it) and vectorizes the same haversine
#: formula for performance (see `build_distance_matrix`'s own
#: docstring), so it carries its own copy of the one constant that
#: formula needs rather than pulling numpy into `geodesy`.
_EARTH_RADIUS_NM: float = 3440.065


def build_distance_matrix(
    aircraft: Sequence[AircraftState],
    vertical_separation_ft: float,
) -> np.ndarray:
    """Build a precomputed pairwise (horizontal NM, vertical-gated) distance matrix.

    Performance (profiled 2026-07): this is called once per prediction
    horizon, every cycle -- for a busy cluster this was measurably the
    single largest share of a cycle's runtime (over a third of total
    cycle time in a 30-aircraft/6-cluster profile, ahead of DBSCAN
    itself). The previous implementation called
    `astra.utils.geodesy.haversine_distance_nm` -- a scalar,
    pure-Python function -- once per aircraft *pair* in a nested Python
    loop: O(n^2) pairs, each paying full Python function-call and
    per-element `math.sin`/`math.cos` overhead. This version computes
    the exact same haversine formula for every pair at once via numpy
    broadcasting -- one vectorized set of trig calls over the whole
    ``(n, n)`` matrix instead of ``n^2`` individual scalar calls -- with
    no change to the distances produced (see `test_hotspot.py`'s own
    regression check that this matches the scalar formula exactly).

    Args:
        aircraft: Aircraft states in a fixed order; matrix row/col ``i``
            corresponds to ``aircraft[i]``.
        vertical_separation_ft: Max altitude difference (ft) for two
            aircraft to be neighbourhood candidates at all.

    Returns:
        A symmetric ``(N, N)`` array of NM distances (zero diagonal),
        suitable for ``sklearn.cluster.DBSCAN(metric="precomputed")``.
    """
    n = len(aircraft)
    if n == 0:
        return np.zeros((0, 0), dtype=float)

    lat_rad = np.radians(np.array([ac.lat for ac in aircraft], dtype=float))
    lon_rad = np.radians(np.array([ac.lon for ac in aircraft], dtype=float))
    alt_ft = np.array([ac.altitude_ft for ac in aircraft], dtype=float)

    dlat = lat_rad[:, None] - lat_rad[None, :]
    dlon = lon_rad[:, None] - lon_rad[None, :]
    a = (
        np.sin(dlat / 2.0) ** 2
        + np.cos(lat_rad[:, None]) * np.cos(lat_rad[None, :]) * np.sin(dlon / 2.0) ** 2
    )
    # Clip before sqrt: floating-point noise can push `a` a hair past 1.0
    # for i == j (dlat = dlon = 0 exactly, but cos(lat)*cos(lat)*0 can
    # still round to something like 1.0000000000000002), which would
    # otherwise make sqrt(1 - a) momentarily complex/NaN.
    a = np.clip(a, 0.0, 1.0)
    c = 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
    distance_nm = _EARTH_RADIUS_NM * c

    vertical_gap_ft = np.abs(alt_ft[:, None] - alt_ft[None, :])
    matrix = np.where(vertical_gap_ft > vertical_separation_ft, _NON_NEIGHBOR_DISTANCE, distance_nm)
    np.fill_diagonal(matrix, 0.0)
    return matrix