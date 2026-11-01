# MOSAIC — Multi-measure ATFM Optimization

**MOSAIC** is a Python research prototype for optimizing ATFM measures in
the Ho Chi Minh FIR and the VVTS terminal area. Its analysis modules predict short/medium-term ATC-complexity hotspots —
*4D Areas of Relatively High ATC Complexity (4DARHAC)* — before they
materialise, and propose ranked,
explainable resolution candidates (speed / flight-level / heading changes)
for a human FMP/ATCO to review and approve. The system never issues
clearances itself: every stage is designed around a strict
**human-in-the-loop** principle.

Demo data and default coordinates are anchored on the **Ho Chi Minh FIR**
(~10.80N, 106.70E).

---

## 1. Pipeline overview

Each poll cycle, `astra.pipeline.Pipeline` runs six stages in sequence:

```
Traffic state -> Trajectory -> Cluster -> Complexity -> Tracking -> Forecast -> Resolution
 (interface)     (trajectory)  (hotspot)  (complexity)  (tracking)  (forecast)  (resolution)
```

| # | Module | Type | What it does |
|---|---|---|---|
| 1 | `astra.interface` | stateless->stateful | Normalises live/mock aircraft state into `TrafficSnapshot` |
| 2 | `astra.trajectory` | stateless | Predicts future positions per aircraft (constant-velocity `TrajectoryEngine`, or `RouteAwareTrajectoryEngine` when a flight-plan route is available) across configurable horizons (5-60 min) |
| 3 | `astra.hotspot` | stateless | DBSCAN clustering (epsilon = 15 NM horizontal, 1000 ft vertical gate) per horizon |
| 4 | `astra.complexity` | stateless | Scores each cluster 0-100 from density, MTCA/LTCA conflict pairs, heading/altitude diversity, aircraft-type mix |
| 5 | `astra.tracking` | **stateful** | Links clusters across poll cycles into a persistent `FourDArhac` with a stable ID and lifecycle (`CANDIDATE -> CONFIRMED -> GROWING -> PEAK -> DISSIPATING -> CLOSED`) |
| 6 | `astra.forecast` | stateless (reads tracks) | Interpolates predicted onset/peak/dissipation time, confidence, urgency rank |
| 7 | `astra.resolution` | stateless (reads tracks) | Exhaustive-search candidate generation + weighted scoring (complexity reduction, domino effect, deviation cost, fuel proxy) |
| 8 | `astra.dashboard` | presentation, read-only | Real-time map, 4DARHAC alerts, ranked resolution candidates with what-if, sector complexity charts |

See `docs/architecture.md` for the full data-flow / dependency diagrams and
`docs/Developer_Handover.md` for module-by-module design notes, testing
conventions, and the full known-limitations table.

---

## 2. Getting started

### Supervisor · Centre / Approach / Tower

Run `./.venv/Scripts/python.exe main.py --mock --profile tsn_tma` and open
`http://127.0.0.1:8050/supervisor`. Centre (`/centre`), Approach (`/`) and
Tower (`/airport`) share timestamped frames and UTC clocks. Handoff at
40 NM keeps a gray Centre track until it descends below 7,000 ft. New linked
airport flights continue on saved airway geometry beyond their STAR/SID.
The case selector offers an optional synthetic FIR extension while preserving
the original terminal case tracks and GA results. See
[the three-view guide](docs/Centre_Approach_Tower.md) for assumptions and controls.

Supervisor includes three [synthetic system tests](docs/System_test_scenarios.md),
checked for 10/20 NM or 1,000 ft separation and at least two minutes between
arrival transfers. Aircraft trails cover the last 10 NM of flown distance.

### Active AirNav video study cases

Run `./.venv/Scripts/python.exe main.py --mock --profile tsn_tma` and open
`http://127.0.0.1:8050/case-scenarios` to load the **February 22** or **October 8**
case into the existing TMA radar. October 7 was removed from this active study
set at the user's request. February has 37 arrival and 43 departure identities
visible in the supplied videos. October has 32 visible departure identities;
its 23 arrivals are explicitly synthetic because the supplied arrival file
duplicates February departures. Paths and runway event times are reconstructed,
not exact historical ADS-B or verified FPLs. The queue tail continues after
the two-hour window to preserve arrival spacing.

See [the case guide](scenarios/reconstructed/vvts_video_cases/README.md).

The Scenario Builder presets and Supervisor test menu include **Nominal · 20 aircraft**
and **Sector overload · 60 aircraft**. The initial airborne cohorts remain visible
at startup; another 6 / 18 arrivals begin at six regional origins and enter radar
after CTOT. The Centre GDP board shows TOBT, CTOT and gate crossing schedules at
those airports and TSN. AC and BAOMY share MIT/MINIT metering; PTH–BAOMY is a feeder.
GA compares fixed-queue GDP/CTOT with coordinated RTA, bounded speed changes,
short rejoining vectors and regional departure level caps. Ground Stop, rerouting
and slot swapping are excluded. All replay variants require native validation.
See [the current model and its assumptions](docs/Gate_flow_ATFM.md).

### Install

```bash
pip install -r requirements.txt --break-system-packages   # Debian/Ubuntu/externally-managed envs
# or simply:
pip install -r requirements.txt
```

Core deps: `numpy`, `scikit-learn` (DBSCAN), `scipy` (Hungarian-algorithm
track assignment). Dashboard: `fastapi`,
`uvicorn`, `websockets`, `pydantic` (real-time telemetry) plus a legacy
`flask` app (Scenario Builder + live-BlueSky HMI), mounted together via
`a2wsgi`. Live BlueSky connectivity is optional and only required if you
run without `--mock`.

### Run — offline mock mode (recommended, no external simulator needed)

```bash
python main.py --mock
```

Opens the real-time dashboard at `http://127.0.0.1:8050/` with a live
WebSocket telemetry feed (`ws://127.0.0.1:8050/ws/telemetry`), seeded with
a 4-aircraft converging demo scenario over the Ho Chi Minh FIR.

For linked VVTS weather scenarios and executable ATFM, run
`python main.py --mock --profile tsn_tma` and open **Weather & ATFM**.
Weather presets display simulated METARs; pasted VVTS METARs are decoded.
The METAR bar stays visible on radar, with simulated TMA weather coverage.
Weather changes procedure speeds, ETAs and trajectory predictions.
Departure CTOT/stand metering, MINIT, ground stops and bounded upstream
arrival speed metering affect the shared simulation. See
[the weather/ATFM guide](docs/weather_atfm.md) for the procedure and model limits.

Console-only (no dashboard):

```bash
python main.py --mock --no-dashboard
```

### Run — live mode against a real BlueSky instance

```bash
python -m bluesky --headless      # terminal 1
python main.py                    # terminal 2
```

`main.py` waits for an active simulation node, then polls at
`config.poll_interval_s` (default 1.0s) and runs every cycle through the
same `Pipeline` used in mock mode — live and offline runs share 100% of
the processing code, only the data source differs.

### Run a scripted scenario offline and export data

```bash
python3 scenarios/run_scn_offline.py scenarios/<file>.scn \
    --duration-min 20 --sim-step-s 15 --out-prefix my_run
```

Loads a `.scn` scenario file into the offline `MockConnector` (BlueSky
stack-command format — no BlueSky process required) and runs it through
the full pipeline cycle by cycle, writing `my_run_cycles.csv` (headline
metrics per cycle) and `my_run_detail.json` (full per-cycle detail: every
region, track, and ranked resolution candidate). This is how the data
under `scenarios/Data/` was produced. The same `.scn` files also load
unchanged in a real BlueSky instance.

Pre-built scenarios in `scenarios/Data/` / generated by
`scenarios/builder/`:

| Scenario | What it tests |
|---|---|
| `nominal` | ~40-aircraft baseline traffic — pipeline stability/throughput under load |
| `crosstrack` | Two-aircraft near-perpendicular crossing — single-hotspot detect->track->forecast->resolve chain |
| `arrival45` | Three-aircraft convergent arrival flow — multi-member cluster growth, domino-effect scoring |

`scenarios/domino_effect_demo.py` is a standalone, hand-built demo
(no connector at all) isolating exactly what `domino_cost_norm`
contributes to `ResolutionEngine`'s scoring.

### Replay the recorded AirNav arrival and run a case study

Open **AirNav case study** from the radar workspace menu, or visit
`http://127.0.0.1:8050/airnav` after starting the app. It offers recorded VN243
playback, a comparison of hypothetical 30-second and 120-second arrival waves,
prediction errors against later observations, and CSV/JSON downloads. It runs
from the saved data, without AirNav access or API credits, and leaves the active
simulation independent of the study.

```bash
python scenarios/run_airnav_case_study.py --out-dir output/airnav_case_study
```

See [the AirNav case-study guide](docs/AirNav_Case_Study.md) for source provenance,
causal recovery of missing fields, coverage limits, and interpretation.

### Three dated VVTS cases from the data request

```bash
python scripts/run_vvts_cases.py --init
```

Open **Ba kịch bản VVTS** at `/vvts-cases`. The study uses the exact requested
bad-weather, nominal and holiday windows, retains incomplete cases explicitly,
and accepts recorded AirNav JSON or AirNav/FR24 track CSV. See
[the three-case guide](docs/VVTS_Three_Cases_VI.md) for source coverage, FPL templates
and the remaining inputs required for real-data ATFM optimization.

The separate [synthetic three-case package](scenarios/synthetic/vvts_cases/README.md)
contains a complete, reproducible traffic manifest and replay tracks for those
same windows. Its assumed flight plans, runway capacity, and 25R/25L procedure
paths are labeled as scenario inputs; the six saved October 7 tracks remain
reference evidence only. Build or check it with
`.\.venv\Scripts\python.exe scripts\build_synthetic_vvts_cases.py --check`.

### Tests

```bash
pytest                     # runs tests/pytest/ (156+ tests, see pytest.ini)
python3 tests/test_*.py    # a few legacy Runner-style scripts, run standalone
```

---

## 3. Configuration

Every tunable constant lives in one frozen dataclass,
`astra.utils.config.ASTRAConfig` — DBSCAN thresholds, prediction
horizons, tracking lifecycle thresholds, forecast onset/dissipation
thresholds, and resolution-candidate step sizes/weights. See the class
docstring for literature-sourced defaults and rationale. Passing a custom
`ASTRAConfig` (e.g. via `dataclasses.replace(DEFAULT_CONFIG, ...)`, as
`main.py` does to declare sectors) is the supported way to change
behaviour — no module reads a magic number directly.

---

## 4. Project layout

```
astra/
  interface/     Traffic-state ingestion: BlueSkyConnector, MockConnector, StateReader
  trajectory/     TrajectoryEngine (constant-velocity), RouteAwareTrajectoryEngine
  hotspot/        ClusterEngine (DBSCAN)
  complexity/     ComplexityEngine, SectorComplexityEngine
  tracking/       TrackerEngine (4DARHAC lifecycle)
  forecast/       ForecastEngine (onset/peak/dissipation/confidence/urgency)
  resolution/     ResolutionEngine (candidate generation + scoring)
  dashboard/      FastAPI real-time dashboard, legacy Flask app, Scenario Builder, geo layers
  pipeline.py     Orchestrates the six engines per poll cycle
  utils/          config.py, units.py, geodesy.py, logger.py (zero internal deps)
scenarios/        .scn scenario files, offline runner, scenario builder, exported CSV/JSON data
tests/            pytest suite (tests/pytest/) + legacy standalone scripts
docs/             architecture.md, Developer_Handover.md
main.py           Entry point (live BlueSky or --mock)
evaluate_trajectory_predictors.py   Held-out comparison: constant-velocity vs route-aware prediction
```

---

## Teammate GA integration (20 October 2026)

The reviewed teammate optimizer is available on **`/case-scenarios`**, with live
run controls, greedy/previous-GA comparisons, annotated results, convergence and
new **GA cộng tác** radar replay options. Original scenarios and earlier results
remain available. Run both studies from the terminal with:

```powershell
.venv\Scripts\python.exe -B -X utf8 scripts/run_teammate_ga.py
```

See [review, provenance and model assumptions](docs/Teammate_GA_review.md).
Results and CSVs are saved under `output/teammate_ga/<run_id>/<case>/`.
Positive residual constraint violations mean a plan is still infeasible.

## 5. Known limitations / roadmap

This is a research prototype, not an operational tool. Full table with
impact/mitigation in `docs/Developer_Handover.md`. Recently addressed:

- **Predicted-only hotspots are no longer dropped.** `TrackerEngine` now
  opens a `"PROVISIONAL"` track directly from a predicted (non-zero
  horizon) cluster once it clears `tracking_provisional_min_complexity`,
  and promotes it to a normal track on its first real observation — see
  `astra/tracking/engine.py`'s module docstring, "Provisional tracks".
- **Track association is now globally optimal by default.** `TrackerEngine.update()`
  solves each cycle's region-to-track matching as one Hungarian-algorithm
  assignment problem (`astra.tracking.association.optimal_track_assignment`)
  instead of greedy, order-dependent matching — toggle via
  `ASTRAConfig.tracking_use_optimal_assignment`.
- **A DIRECT_TO resolution lever now exists.** `astra.resolution.candidates.direct_to_lever_specs`
  generates a candidate aimed at an exact real waypoint further down the
  target's filed route (skipping `resolution_direct_to_skip_waypoints` of
  them), reusing the existing vector-and-rejoin replay machinery — gate
  with `ASTRAConfig.resolution_enable_direct_to`.
- **Complexity scoring** now also offers `"quadratic_mean"` combination
  (`ASTRAConfig.complexity_score_combination`) alongside the original
  linear-weighted sum, reacting more sharply to one dominant driver
  without requiring a historical calibration dataset.
- **An already-critical hotspot is no longer silently dropped from
  resolution/urgency ranking.** `predicted_onset_s` correctly stays
  `None` once a track's current complexity has already crossed
  `forecast_onset_threshold` (there's no future onset left to predict),
  but that used to also make it fall out of `forecast_urgency_rank`
  (sorted as *least* urgent, via `None`-as-`Infinity`) and out of
  `ResolutionEngine` eligibility entirely -- the single most urgent
  situation ASTRA can describe went both unranked and unresolved.
  `FourDArhac.already_critical` (set by `ForecastEngine.forecast`) now
  disambiguates "already critical" from "too new to say anything yet",
  ranks already-critical tracks *first* (by descending current
  complexity), and `ResolutionEngine` evaluates them at horizon 0 (the
  immediate effect) instead of refusing to resolve them at all.
- **Resolution candidates now cover more than one target aircraft.** The
  single-aircraft search used to always resolve to one pre-selected
  aircraft (`select_target_aircraft`'s top pick), so every candidate in
  the ranked list -- no matter how many were shown -- moved that same
  one aircraft; a second aircraft only ever appeared as a *joint*
  candidate's secondary leg (moving alongside the first), never as an
  independent alternative. `ASTRAConfig.resolution_alternative_targets`
  (default `1`) now also searches the next-ranked member and merges both
  aircrafts' candidates into one ranked list, so "turn A" and "turn B"
  compete on `resolution_score` and either can legitimately come out on
  top.
- **Dashboard hotspot polygons no longer relocate when scrubbing
  horizons.** A predicted (non-zero) horizon's region used to be ringed
  only at that horizon's own predicted member positions -- since those
  can be tens of NM from the same aircraft's *current* position, the
  polygon appeared to teleport across the map every time the horizon
  slider moved. Each member is now ringed at *both* its current and
  predicted position, feeding one shared convex hull -- a stable,
  anchored "swept corridor" from where the traffic is now to where the
  hotspot is forecast, rather than a single point that jumps.
- **The Event panel's complexity ring is now labelled with which point
  in time it represents** (`"Now"` vs. `"Predicted @ +N min"`) -- it can
  legitimately differ from the Alert table's `current_complexity_score`
  (always "now") when a future evaluated horizon was recommended; this
  was previously unlabelled and looked like a data inconsistency between
  the two panels.

Still open:

- **Trajectory prediction** defaults to constant-velocity dead-reckoning;
  `RouteAwareTrajectoryEngine` (route/profile-aware) exists and is wired
  into `Pipeline` but only activates when a route provider is supplied —
  no wind correction, no intent/ADS-C data.
- **Complexity/forecast calibration**: both the linear and quadratic-mean
  combination methods, and `ForecastEngine`'s confidence heuristic, are
  documented simplifications rather than a statistically calibrated model
  — would need a historical reference dataset.
- **ResolutionEngine** target-aircraft selection is a conflict-count +
  centroid-distance proxy, not a true per-aircraft complexity-contribution
  score (would need `ComplexityEngine` to expose a per-aircraft
  breakdown, e.g. a leave-one-out complexity delta).
- **Dashboard**: binds to `127.0.0.1` only, no authentication, single-user;
  the legacy Flask app is polling-based while the FastAPI path streams
  over WebSockets; Flask's dev server is not production-hardened.
- **No historical/replay persistence** — `StateReader` history is in-memory
  only (`history_length`), lost on restart.
- No meteorological data (wind, SIGMET/convective weather) is ingested
  anywhere in the pipeline.
- No CI pipeline and no license file.

---

## 6. Notes on data provenance

Scenario aircraft speeds in the hotspot scenarios (110-130 kt) are
deliberately terminal-area/early-approach speeds, not cruise, so that each
scenario starts *below* `forecast_onset_threshold` (50) and is forecast to
cross it — this is what exercises `ForecastEngine.predicted_onset_s` and
therefore `ResolutionEngine`. At cruise speed the group would close, cross,
and disperse within a single prediction horizon, and would already be
above threshold at first detection (bypassing the forecast/resolution
chain entirely — a different, already-critical code path).
