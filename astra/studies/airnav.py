"""Observed VVTS prediction validation and explicitly hypothetical arrival waves."""

from bisect import bisect_left
from dataclasses import asdict, replace
import csv
import io
import json
from pathlib import Path
import statistics

from astra.airspace import configure_profile
from astra.interface.airnav_replay import AirNavDataset, AirNavReplayConnector
from astra.pipeline import Pipeline
from astra.trajectory.engine import predict_constant_velocity
from astra.utils.config import ASTRAConfig
from astra.utils.geodesy import haversine_distance_nm

DATA_DIR = Path(__file__).resolve().parents[2] / "scenarios" / "recorded" / "airnav"
DEFAULT_DATA = DATA_DIR / "VN243_2026-10-08_api.json"
CASE_SPECS = (
    dict(id="observed", label="Observed VN243 arrival", kind="observed", count=1, spacing_s=0),
    dict(id="compressed", label="Hypothetical wave · 30 s", kind="synthetic", count=4, spacing_s=30),
    dict(id="spaced", label="Hypothetical wave · 120 s", kind="synthetic", count=4, spacing_s=120),
)


def _percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * fraction
    low = int(index)
    return values[low] + (values[min(low + 1, len(values) - 1)] - values[low]) * (index - low)


def forecast_errors(points, *, horizons_s=(30, 60, 120, 300), tolerance_s=15):
    """Score against actual later observations; never feed them to prediction.

    Use the nearest later observation within +/- tolerance of a requested
    horizon, predict at its actual elapsed time, and report that time. No
    interpolation of unobserved future truth or scoring of carried altitudes.
    """
    usable = [p for p in points if p.state and p.field_sources.get("altitude") == "reported"]
    times = [p.epoch_s for p in usable]
    rows = []
    for point in usable:
        for horizon in horizons_s:
            desired = point.epoch_s + horizon
            index = bisect_left(times, desired)
            candidates = [usable[i] for i in (index - 1, index) if 0 <= i < len(usable)
                          and usable[i].epoch_s > point.epoch_s]
            if not candidates:
                continue
            truth = min(candidates, key=lambda p: abs(p.epoch_s - desired))
            if abs(truth.epoch_s - desired) > tolerance_s:
                continue
            dt = truth.epoch_s - point.epoch_s
            predicted = predict_constant_velocity(point.state, dt, dt)
            rows.append(dict(source_utc=point.utc, truth_utc=truth.utc,
                requested_horizon_s=horizon, actual_horizon_s=round(dt, 3),
                horizontal_error_nm=haversine_distance_nm(predicted.lat, predicted.lon, truth.lat, truth.lon),
                altitude_error_ft=abs(predicted.altitude_ft - truth.state.altitude_ft)))
    return rows


def _pair_metrics(aircraft, config):
    minimum = None
    conflicts = 0
    aircraft = list(aircraft)
    for i, left in enumerate(aircraft):
        for right in aircraft[i + 1:]:
            distance = haversine_distance_nm(left.lat, left.lon, right.lat, right.lon)
            if abs(left.altitude_ft - right.altitude_ft) < config.conflict_vertical_min_ft:
                minimum = distance if minimum is None else min(minimum, distance)
                if distance < config.conflict_horizontal_min_nm:
                    conflicts += 1
    return conflicts, minimum


def run_study(data_path=DEFAULT_DATA, *, policy=None, case_specs=CASE_SPECS):
    dataset = AirNavDataset.load(data_path, policy)
    source = next(iter(dataset.points))
    flight = dataset.metadata[source]
    if flight.get("arrAirportIcao") != "VVTS":
        raise ValueError("This case study requires a flight arriving at VVTS")
    config = configure_profile(ASTRAConfig(), "tsn_tma")
    config = replace(config, prediction_horizons_min=[1, 2, 5], max_prediction_horizon_min=5,
                     terminal_prediction_step_s=60, resolution_max_tracks_per_cycle=1)
    center = config.assessment_volume
    points = [p for p in dataset.points[source] if not p.on_ground and
              haversine_distance_nm(center.center_lat, center.center_lon, p.lat, p.lon) <= 60]
    if len(points) < 2 or not any(p.state for p in points):
        raise ValueError("The recording has insufficient observations within 60 NM of VVTS")
    start, end = points[0].epoch_s, points[-1].epoch_s
    cases = []
    for spec in case_specs:
        if spec["count"] < 1 or spec["count"] > 8 or spec["spacing_s"] < 0:
            raise ValueError("Study waves support 1–8 aircraft and non-negative spacing")
        offsets = ({source: (source, 0.0)} if spec["kind"] == "observed" else
                   {f"SYN{i + 1:03}": (source, float(i * spec["spacing_s"])) for i in range(spec["count"])})
        connector = AirNavReplayConnector(dataset, start_epoch_s=start, end_epoch_s=end, offsets=offsets)
        connector.connect()
        pipeline = Pipeline(config)  # No route provider: future recorded geometry is never flight intent.
        frames = []
        for t in connector.timeline:
            snapshot, provenance = connector.frame_at(t)
            result = pipeline.run_cycle(snapshot)
            assessed = [ac for ac in snapshot if center.contains(ac)]
            conflicts, minimum = _pair_metrics(assessed, config)
            regions = result.regions_by_horizon.get(0, [])
            peak_forecast = max((region.complexity_score for h, rs in result.regions_by_horizon.items()
                                 if h > 0 for region in rs), default=0.0)
            frames.append(dict(time_s=round(t, 3), aircraft=[asdict(ac) for ac in snapshot],
                provenance=provenance, assessed_aircraft=len(assessed),
                conflict_pairs=conflicts, min_horizontal_nm=minimum,
                observed_complexity=max((r.complexity_score for r in regions), default=0.0),
                predicted_complexity=peak_forecast, open_tracks=len(result.tracks),
                resolution_candidates=sum(len(rs.candidates) for rs in result.resolution_sets),
                manual_intervention_tracks=sum(rs.manual_intervention_required for rs in result.resolution_sets)))
        pair_exposure = sum(frame["conflict_pairs"] * (after["time_s"] - frame["time_s"])
                            for frame, after in zip(frames, frames[1:]))
        evaluated_pair_time = sum(after["time_s"] - frame["time_s"]
                                 for frame, after in zip(frames, frames[1:]) if frame["assessed_aircraft"] >= 2)
        minimums = [f["min_horizontal_nm"] for f in frames if f["min_horizontal_nm"] is not None]
        summary = dict(frames=len(frames), peak_aircraft=max(f["assessed_aircraft"] for f in frames),
            peak_complexity=max(f["observed_complexity"] for f in frames),
            peak_predicted_complexity=max(f["predicted_complexity"] for f in frames),
            conflict_pair_exposure_s=pair_exposure, evaluated_pair_time_s=evaluated_pair_time,
            min_horizontal_nm=min(minimums) if minimums else None,
            frames_with_candidates=sum(f["resolution_candidates"] > 0 for f in frames),
            frames_with_manual_intervention=sum(f["manual_intervention_tracks"] > 0 for f in frames))
        cases.append(dict(**spec, summary=summary, frames=frames))
    errors = forecast_errors(points)
    forecast_summary = []
    for horizon in (30, 60, 120, 300):
        selected = [r for r in errors if r["requested_horizon_s"] == horizon]
        horizontal = [r["horizontal_error_nm"] for r in selected]
        vertical = [r["altitude_error_ft"] for r in selected]
        forecast_summary.append(dict(horizon_s=horizon, count=len(selected),
            mean_horizontal_nm=statistics.mean(horizontal) if horizontal else None,
            p95_horizontal_nm=_percentile(horizontal, .95),
            mean_altitude_ft=statistics.mean(vertical) if vertical else None))
    context_file = Path(data_path).with_name("airport_context.json")
    context = json.loads(context_file.read_text(encoding="utf-8")) if context_file.exists() else None
    return dict(schema_version=1, title="AirNav VVTS arrival case study", source=dataset.summary(),
        flight=flight, airport_context=context, cases=cases, forecast_errors=errors,
        forecast_summary=forecast_summary,
        observed_points=[dict(utc=p.utc, time_s=round(p.epoch_s - start, 3), lat=p.lat, lon=p.lon,
                              usable=p.state is not None, field_sources=p.field_sources,
                              altitude_ft=p.state.altitude_ft if p.state else None) for p in points],
        study=dict(start_utc=points[0].utc, end_utc=points[-1].utc,
            recording_radius_nm=60, assessment_radius_nm=center.radius_nm,
            assessment_lower_ft=center.lower_altitude_ft, assessment_upper_ft=center.upper_altitude_ft,
            center_lat=center.center_lat, center_lon=center.center_lon,
            horizontal_threshold_nm=config.conflict_horizontal_min_nm,
            vertical_threshold_ft=config.conflict_vertical_min_ft,
            prediction_horizons_min=[1, 2, 3, 4, 5], truth_tolerance_s=15,
            source_callsign=source),
        limitations=[
            "Only VN243 is observed. The two four-aircraft waves are hypothetical time-shifted copies, not recorded airport traffic.",
            f"Playback uses past observations and at most {dataset.policy.max_position_age_s:g} seconds of causal extrapolation. Aircraft disappear when data expires or the recording ends.",
            "Predictions use constant velocity. No filed route, SID/STAR assignment or future track is supplied to the predictor.",
            "Forecast errors use later reported observations within ±15 seconds of each requested horizon, predicted at the actual elapsed time. No future truth is interpolated.",
            "Thresholds and complexity scores use the existing VVTS research configuration; these are not verified operational separation minima.",
            "Recorded altitude datum is retained without an AMSL correction. The weather/context snapshot was captured separately and does not drive replay physics.",
            "Candidate clearances are counted but never applied. Pair exposure measures the reconstructed cases, not observed incidents or proved ATFM benefits."])


def csv_text(result, asset):
    if asset == "forecast_errors.csv":
        rows = result["forecast_errors"]
        fields = ["source_utc", "truth_utc", "requested_horizon_s", "actual_horizon_s",
                  "horizontal_error_nm", "altitude_error_ft"]
    elif asset == "cycles.csv":
        fields = ["case_id", "kind", "time_s", "assessed_aircraft", "conflict_pairs",
                  "min_horizontal_nm", "observed_complexity", "predicted_complexity", "open_tracks",
                  "resolution_candidates", "manual_intervention_tracks"]
        rows = [dict(case_id=case["id"], kind=case["kind"],
                     **{key: frame[key] for key in fields[2:]}) for case in result["cases"] for frame in case["frames"]]
    else:
        raise ValueError("Unknown study CSV asset")
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue()


def export_study(result, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    for asset in ("cycles.csv", "forecast_errors.csv"):
        (out_dir / asset).write_text(csv_text(result, asset), encoding="utf-8")
    lines = ["# AirNav VVTS arrival case study", "", f"Source SHA-256: `{result['source']['source_sha256']}`", "",
             "| Case | Kind | Peak aircraft | Peak complexity | Pair exposure (s) | Pair coverage (s) |", "|---|---|---:|---:|---:|---:|"]
    for case in result["cases"]:
        s = case["summary"]
        lines.append(f"| {case['label']} | {case['kind']} | {s['peak_aircraft']} | {s['peak_complexity']:.2f} | {s['conflict_pair_exposure_s']:.2f} | {s['evaluated_pair_time_s']:.2f} |")
    lines.extend(["", "Prediction error is measured against later recorded observations, without exposing future tracks to prediction.", "",
                  "| Horizon (s) | Matched pairs | Mean horizontal error (NM) | Mean altitude error (ft) |", "|---:|---:|---:|---:|"])
    for row in result["forecast_summary"]:
        h = f"{row['mean_horizontal_nm']:.3f}" if row['count'] else "Unavailable"
        v = f"{row['mean_altitude_ft']:.1f}" if row['count'] else "Unavailable"
        lines.append(f"| {row['horizon_s']} | {row['count']} | {h} | {v} |")
    lines.extend(["", *[f"- {text}" for text in result["limitations"]]])
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
