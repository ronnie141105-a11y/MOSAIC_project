"""
Regression tests -- vectorized pairwise distance matrix
(`astra.hotspot.distance`, performance fix).

Run with:
    python3 tests/test_distance.py
"""

import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from astra.hotspot.distance import _NON_NEIGHBOR_DISTANCE, build_distance_matrix
from astra.interface.traffic_state import AircraftState
from astra.utils.geodesy import haversine_distance_nm
from tests._runner import Runner


def _aircraft(callsign, lat, lon, alt_ft=35000.0):
    return AircraftState(
        callsign=callsign,
        lat=lat,
        lon=lon,
        altitude_ft=alt_ft,
        ground_speed_kt=450.0,
        heading_deg=90.0,
        vertical_speed_fpm=0.0,
        aircraft_type="A320",
        timestamp_s=0.0,
    )


def _scalar_reference_matrix(aircraft, vertical_separation_ft):
    """The old, pre-vectorization implementation, kept here only as the
    ground-truth reference this test checks the vectorized version
    against -- not the production code path any more."""
    n = len(aircraft)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            vgap = abs(aircraft[i].altitude_ft - aircraft[j].altitude_ft)
            if vgap > vertical_separation_ft:
                d = _NON_NEIGHBOR_DISTANCE
            else:
                d = haversine_distance_nm(
                    aircraft[i].lat, aircraft[i].lon, aircraft[j].lat, aircraft[j].lon
                )
            matrix[i][j] = matrix[j][i] = d
    return matrix


def test_matches_scalar_haversine_reference(r: Runner) -> None:
    """Performance fix regression: the vectorized matrix must produce
    numerically identical distances to the original pure-Python,
    per-pair scalar haversine implementation -- vectorizing this was
    purely a performance change, never meant to alter DBSCAN's actual
    neighbourhood decisions."""
    random.seed(7)
    aircraft = [
        _aircraft(
            f"AC{i}",
            random.uniform(8.0, 15.0),
            random.uniform(104.0, 110.0),
            alt_ft=random.choice([30000.0, 30500.0, 35000.0, 35500.0, 40000.0]),
        )
        for i in range(40)
    ]
    vertical_sep = 1000.0
    vectorized = build_distance_matrix(aircraft, vertical_sep)
    reference = _scalar_reference_matrix(aircraft, vertical_sep)

    max_err = 0.0
    mismatches = 0
    n = len(aircraft)
    for i in range(n):
        for j in range(n):
            expected = reference[i][j]
            got = vectorized[i, j]
            if expected == _NON_NEIGHBOR_DISTANCE:
                if got != _NON_NEIGHBOR_DISTANCE:
                    mismatches += 1
            else:
                max_err = max(max_err, abs(got - expected))
    r.check(f"zero vertical-gate mismatches (got {mismatches})", mismatches == 0)
    r.check(f"max distance error is negligible ({max_err:.2e} NM)", max_err < 1e-6)


def test_diagonal_is_zero(r: Runner) -> None:
    """Every aircraft's distance to itself is exactly 0, not a tiny
    floating-point residue from the vectorized trig (the clip-before-
    sqrt guard exists specifically to keep this exact)."""
    aircraft = [_aircraft("A1", 10.0, 106.0), _aircraft("A2", 10.5, 106.5), _aircraft("A3", 9.5, 105.5)]
    matrix = build_distance_matrix(aircraft, 1000.0)
    for i in range(len(aircraft)):
        r.check(f"diagonal[{i}] is exactly 0.0", matrix[i, i] == 0.0)


def test_vertical_gate_still_applies(r: Runner) -> None:
    """Two aircraft far apart vertically are marked non-neighbours
    (a huge placeholder distance) even if laterally right on top of
    each other."""
    close_laterally = [_aircraft("LOW", 10.0, 106.0, alt_ft=30000.0), _aircraft("HIGH", 10.0, 106.0, alt_ft=40000.0)]
    matrix = build_distance_matrix(close_laterally, vertical_separation_ft=1000.0)
    r.check(
        "10000 ft apart, 1000 ft gate -> treated as non-neighbours",
        matrix[0, 1] == _NON_NEIGHBOR_DISTANCE,
    )


def test_empty_input(r: Runner) -> None:
    """No aircraft at all -> an empty (0, 0) matrix, not an error."""
    matrix = build_distance_matrix([], 1000.0)
    r.check("empty input returns a (0, 0) matrix", matrix.shape == (0, 0))


def test_symmetric(r: Runner) -> None:
    """The matrix is exactly symmetric (DBSCAN requires this for a
    precomputed metric)."""
    random.seed(3)
    aircraft = [
        _aircraft(f"AC{i}", random.uniform(8.0, 15.0), random.uniform(104.0, 110.0))
        for i in range(15)
    ]
    matrix = build_distance_matrix(aircraft, 1000.0)
    asymmetric_pairs = 0
    for i in range(len(aircraft)):
        for j in range(len(aircraft)):
            if not math.isclose(matrix[i, j], matrix[j, i], abs_tol=1e-9):
                asymmetric_pairs += 1
    r.check(f"matrix is exactly symmetric (found {asymmetric_pairs} mismatches)", asymmetric_pairs == 0)


def main() -> None:
    r = Runner("Performance fix — vectorized pairwise distance matrix (astra.hotspot.distance)")
    test_matches_scalar_haversine_reference(r)
    test_diagonal_is_zero(r)
    test_vertical_gate_still_applies(r)
    test_empty_input(r)
    test_symmetric(r)
    r.summary()


if __name__ == "__main__":
    main()
