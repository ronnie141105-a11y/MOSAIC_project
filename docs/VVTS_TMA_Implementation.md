# VVTS TMA implementation and validation

**Historical baseline:** the 21 September approach/100 NM radar update supersedes
the landing, catalogue, display-default and test-count details below. See
[the current update](VVTS_TMA_Approach_Radar_Update.md).

Implemented 20 September 2026. This is an offline, nominal terminal-traffic
research model for the seminar and a foundation for later GA-based ATFM work.
The existing HCM FIR mode remains the default.

## Run

From the project directory in PowerShell:

```powershell
.\.venv\Scripts\python.exe main.py --mock --profile tsn_tma
```

Open http://127.0.0.1:8050/ and use **Scenario Builder** to choose the mixed,
arrival-merge, or departure-fan preset. Loading a preset leaves it paused;
select Resume or Step. A dedicated procedure form creates a flight by callsign,
procedure and runway. The blue solid lines are SIDs; amber dashed lines are STARs.
Options controls the boundary, routes, fixes and runway overlays.
Return to Overall TMA fits the 40 NM circle. Feeder legs outside it remain in
the route data and can be inspected by panning/zooming.

The environment in `.venv` has the project's requirements installed. For a fresh
environment, install `requirements.txt`. `--profile tsn_tma` requires `--mock`;
live BlueSky terminal procedure integration is not implemented.

## Implemented airspace and procedures

| Item | Implementation |
|---|---|
| Study boundary | Geodesic 40 NM radius around TSH, 10°49′06″N 106°39′02″E |
| Assessment height | 600–5,050 m, converted to feet internally |
| Runway configuration | 25L and 25R |
| Waypoint catalogue | 149 source workbook points |
| RNAV SIDs | SAPEN2D, BACHU2D, MISAN2D, ENPAS2D, XOBAV2D, KADUM2D, ANTRI2D, LANHI2D |
| STARs | SAPEN2H, BITIS2H, VICAL3H, ELSAS2H, DALAP2H, DALAP2J |
| Forecast horizons | 1, 2, 3, 5, 10 and 15 minutes |
| Study thresholds | 8 NM clustering; simultaneous <5 NM and <1,000 ft conflict sampling |
| Conflict sampling | Every 5 simulated seconds, through 15 minutes |

The thresholds are research assumptions, not verified local separation minima.
The circle is the requested study volume, not a claim to reproduce the exact
published TMA polygon. Source charts are the supplied historical 2022–2024
editions, not a verified current AIRAC set. The earlier design brief and waypoint
audit remain under `output/tsn_tma_design`.

SID and STAR routes are independent, directed fix sequences, even when they
share a fix or centreline. Departures climb outbound; arrivals descend inbound.
Each leg has a nominal altitude target separate from extracted chart altitude
restrictions and speed limits. A shared event-based propagator drives both mock
motion and prediction, including traversing several fixes in a single timestep.

Flights hand off at the last modelled procedure fix. An arrival at SOKAN/BOMSU
does not descend to zero or become a landed aircraft. Completed aircraft leave
the active simulation. Aircraft outside the circle or height limits remain
visible and are predicted, but only states inside the volume enter TMA
clustering and complexity assessment. Thus an external feeder can later enter
the assessment volume without truncating its route at 40 NM.

The new conflict-box path samples these same 3D trajectories. Two overlapping
map lines alone do not produce a box: the aircraft must breach both study
thresholds at the same sample time. Existing complexity alerts still represent
traffic interaction, and are not synonymous with confirmed conflicts. Conflict
boxes operate on tracked cluster members; this is not an exhaustive continuous
conflict detector, and brief encounters between samples/horizons may be missed.

Scenario save/load retains remaining procedure legs and altitude targets.
TMA saves use `scenarios/builder/tsn_tma`. Cross-profile loads are rejected.
Reset clears both simulation history and pipeline tracking to prevent stale
aircraft/tracks from appearing in the next scenario.

## Code map

- `scenarios/profiles/tsn_tma`: boundary metadata, fixes, SIDs, STARs and holding metadata.
- `scripts/build_tsn_profile.py`: reproducible compilation from the waypoint audit and chart transcription.
- `astra/airspace.py`: profile loading, scenario generation, volume configuration and GeoJSON.
- `astra/trajectory/procedure.py`: common route and altitude propagation.
- `astra/hotspot/procedure_box.py`: simultaneous trajectory separation sampling.
- `tests/pytest/test_tma_profile.py`: procedure, integration, API and WebSocket regressions.

## Validation results

Command: `.\.venv\Scripts\python.exe -m pytest -q`

**64 tests passed**, including 45 TMA tests and 19 existing asynchronous/streaming
tests. Two dependency deprecation warnings remain in the FastAPI/Starlette test
client. Full output is in `output/tsn_tma_tests/pytest.log`.

All **11 legacy test scripts passed, totalling 610 checks**. The dashboard
script was rerun after updating its stale expected payload fields and its
expected candidate-display default (the production default was already 20).
An existing WebSocket/REST test was fixed to compare schema and monotonically
advancing cycle counts: live requests can legitimately read successive cycles.
Logs are in `output/tsn_tma_tests`.

Coverage includes:

- All 14 procedures on both runway configurations: continuous position/altitude,
  waypoint progression, direction and completion at handoff.
- Predictor versus mock motion over 180 one-second updates on selected routes.
- Shared-path encounters with and without vertical separation.
- Volume filtering while retaining future entries from outside the volume.
- Mixed, arrivals-only and departures-only presets run until all aircraft hand
  off, within a 60-minute simulation window; outputs remain finite JSON.
- Procedure creation, invalid inputs, save/load, preset resets, blocked manual
  route-changing clearances, geometry endpoints, and live TMA WebSocket frames.
- Browser inspection of the circle, separate SID/STAR layers, TMA labels,
  prediction slider and Scenario Builder. Narrow-panel map clipping was fixed.

These are software and internal-consistency checks; they do not establish
operational suitability, real airport capacity or aircraft-performance accuracy.

## Model boundaries and next ATFM work

Conventional SIDs await missing-coordinate reconciliation. Holding definitions
are retained but holding execution is absent. Final approach, missed approach,
runway occupancy, wake separation, departure scheduling and runway 07 operations
are outside this version. Coordination is assumed granted.

Altitude profiles interpolate linearly along centreline legs. Turns have no
bank/turn-radius model. Climb gradients are retained as metadata but are not
enforced. Speed is nominal ground speed numerically capped by extracted IAS
limits; this is a simplified no-wind proxy, not an IAS/TAS/GS conversion or
acceleration model. Procedure feasibility still needs aircraft-performance and
chart-edition validation before quantitative ATFM conclusions.

Legacy tactical heading/altitude/speed recommendations and manual clearances
are withheld for fixed procedure flights because that optimizer does not yet
respect procedure constraints. **No GA optimization is implemented yet.**

For the next stage, add scheduled demand and explicit resource constraints,
then optimize entry/release times and arrival sequencing while preserving each
flight's assigned procedure. Compare a baseline with the GA using delay,
throughput, queue length and conflicts. Runway/wake/merge constraints and a
validated trajectory evaluator must be in place before interpreting a GA
solution as feasible traffic-flow management.
