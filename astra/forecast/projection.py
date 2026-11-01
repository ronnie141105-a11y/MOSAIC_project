"""
Pure threshold-crossing / peak-detection math for 4DARHAC forecasting
(Milestone 6).

No domain-object dependencies -- operates on plain ``(time_s, score)``
point series. Mirrors ``astra.complexity.stats``'s pattern of small,
dependency-free numeric helpers feeding a stateless engine
(``astra.forecast.engine.ForecastEngine``). See
this module's own docstring above for the design rationale.
"""

from typing import List, Optional, Tuple


def linear_crossing_time(
    points: List[Tuple[float, float]], threshold: float, rising: bool
) -> Optional[float]:
    """First time a piecewise-linear score series crosses ``threshold``.

    Args:
        points: ``(time_s, score)`` pairs, already sorted ascending by
            ``time_s``.
        threshold: The score value to find a crossing of.
        rising: ``True`` to find an upward crossing (score goes from
            below to at/above threshold); ``False`` for a downward
            crossing.

    Returns:
        The linearly-interpolated ``time_s`` of the first qualifying
        crossing between two consecutive points, or ``None`` if no such
        crossing exists in the given series.
    """
    for (t0, s0), (t1, s1) in zip(points, points[1:]):
        if s1 == s0:
            continue
        if rising and s0 < threshold <= s1:
            fraction = (threshold - s0) / (s1 - s0)
            return t0 + fraction * (t1 - t0)
        if not rising and s0 > threshold >= s1:
            fraction = (s0 - threshold) / (s0 - s1)
            return t0 + fraction * (t1 - t0)
    return None


def predicted_peak(
    points: List[Tuple[float, float]], current_peak: float
) -> Optional[Tuple[float, float]]:
    """The predicted peak (time, score) among future points, if it exceeds ``current_peak``.

    ``points`` is a discrete, coarsely-spaced sample -- ASTRA's own
    configured prediction horizons (e.g. 5/10/15/20/30/45/60 min), not
    a dense curve -- so the true complexity peak routinely falls
    *between* two of them rather than exactly on one. Snapping to
    "whichever sampled horizon happens to score highest" (the previous
    behaviour) reports that horizon's own time even when the real
    turning point is, say, partway between the 30- and 45-minute
    samples: systematically the wrong peak time whenever the curve
    isn't lucky enough to have a sample sitting right at its apex.

    When the highest-scoring sample has a neighbour on *both* sides,
    this instead fits a parabola through it and its two neighbours and
    reports that parabola's own vertex (time, score) -- a standard
    3-point parabolic interpolation, and a meaningfully better estimate
    of the actual peak than the raw grid point. The interpolated time
    is clamped to the neighbours' own interval so a nearly-flat or
    concave-down fit can never extrapolate the "peak" outside the data
    it was fit from. When the highest-scoring sample is at either end
    of ``points`` (the curve is still rising at the furthest horizon
    ASTRA can currently see, i.e. the true peak lies beyond the
    forecast window), there is no second neighbour to interpolate
    with, so that raw sample is reported as-is -- the best estimate
    available this cycle, refined further once later horizons resolve
    it or the track is re-forecast next cycle.

    Args:
        points: ``(time_s, score)`` pairs for *future* horizons only
            (the caller should already have excluded the observed "now"
            anchor point), ascending by ``time_s``.
        current_peak: The highest score already known
            (``FourDArhac.peak_complexity``).

    Returns:
        ``(time_s, score)`` of the predicted peak if it exceeds
        ``current_peak``, else ``None``.
    """
    if not points:
        return None
    best_idx, (best_time, best_score) = max(
        enumerate(points), key=lambda item: item[1][1]
    )
    if best_score <= current_peak:
        return None
    if 0 < best_idx < len(points) - 1:
        t0, s0 = points[best_idx - 1]
        t1, s1 = points[best_idx]
        t2, s2 = points[best_idx + 1]
        denom = (t1 - t0) * (s1 - s2) - (t1 - t2) * (s1 - s0)
        if abs(denom) > 1e-9:
            vertex_t = t1 - 0.5 * (
                (t1 - t0) ** 2 * (s1 - s2) - (t1 - t2) ** 2 * (s1 - s0)
            ) / denom
            # Defensive clamp: a fit that isn't a clean local max (near-
            # collinear points, or a saddle) can place the vertex outside
            # the sampled interval -- never report a "peak" the data
            # itself doesn't actually bracket.
            vertex_t = max(t0, min(t2, vertex_t))
            # Evaluate the fitted parabola at its own vertex for the
            # score, via Lagrange interpolation through the same 3
            # points, rather than reusing best_score outright -- this is
            # what makes the vertex_t/score pair internally consistent
            # (an interpolated time deserves its own interpolated score,
            # not the nearest raw sample's).
            def _lagrange(t: float) -> float:
                terms = [
                    s0 * (t - t1) * (t - t2) / ((t0 - t1) * (t0 - t2)),
                    s1 * (t - t0) * (t - t2) / ((t1 - t0) * (t1 - t2)),
                    s2 * (t - t0) * (t - t1) / ((t2 - t0) * (t2 - t1)),
                ]
                return sum(terms)

            vertex_score = _lagrange(vertex_t)
            if vertex_score > current_peak:
                return vertex_t, vertex_score
    return best_time, best_score
