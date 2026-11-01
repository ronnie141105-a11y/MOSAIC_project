# AirNav VVTS arrival case study

MOSAIC can now replay saved AirNav flight-search JSON and track CSV files. A
case-study page combines the recorded VN243 arrival, a prediction evaluation,
and two hypothetical arrival waves. Everything runs offline from the saved
recording; it does not call AirNav or need an API credential.

Start the usual application:

```powershell
python main.py --mock --profile tsn_tma
```

Open **AirNav case study** in the radar workspace menu, or visit
`http://127.0.0.1:8050/airnav`. The page also works in the default FIR profile.
Its analysis uses a fresh pipeline configured for VVTS, independent of the
currently running simulation. Play/pause, playback speed, a time slider,
case selection, data-quality details, complexity charts and CSV/JSON exports
are available. The study starts through a bounded background job; repeated
run requests during that job do not launch another experiment.

For a repeatable batch run:

```powershell
python scenarios/run_airnav_case_study.py --out-dir output/airnav_case_study
```

The runner writes `report.md`, `report.json`, `cycles.csv`, and
`forecast_errors.csv`. `--data` accepts another saved AirNav flight-search
response containing an arrival at VVTS. The first flight in that response is
the source for this study. For simultaneous observed traffic, the ingestion
adapter supports multiple flights, but these particular comparison cases
deliberately use one source flight.

## Cases and interpretation

| Case | Input | Question |
|---|---|---|
| Observed arrival | VN243 / HVN243, VN-A399, A321, VVNB to VVTS on 8 October 2026 | How well does constant-velocity prediction match later recorded positions? |
| Hypothetical compressed wave | Four copies of the arrival, shifted by 0, 30, 60 and 90 seconds | How does a tightly spaced arrival wave affect modeled complexity and pair exposure? |
| Hypothetical spaced wave | Four copies shifted by 0, 120, 240 and 360 seconds | How does increased entry spacing change the same modeled measures? |

The hypothetical copies use `SYN001`–`SYN004` and carry the source callsign,
source UTC, shift and recovery provenance on every frame. They do not
represent additional flights recorded by AirNav. The pipeline counts ranked
clearances and manual-review frames without applying commands. Comparing the
two waves studies a spacing assumption; it does not demonstrate an operational
ATFM benefit or validate real airport capacity.

The recorded track is displayed within 60 NM of VVTS. Assessment uses the
existing `tsn_tma` profile's 40 NM circle and altitude band, with its research
thresholds of 5 NM horizontally and 1,000 ft vertically. Forecast complexity
uses horizons 1–5 minutes. Actual route intent and SID/STAR assignments are
unavailable and are not inferred from the future recorded geometry.

Pair exposure is a sampled estimate: the number of eligible pairs below both
thresholds multiplied by the interval to the next replay event. Pair coverage
is the duration for which at least two aircraft have usable states inside the
assessment volume. Different hypothetical spacings can change coverage, so
compare exposure together with its coverage denominator. Minimum horizontal
distance considers only pairs below the vertical threshold. Unavailable pair
distances and unmatched forecast horizons remain null instead of becoming zero.

## Data handling and prediction evaluation

`astra.interface.airnav_replay` normalizes explicit timestamp offsets to UTC,
preserves feet/knots/ft-per-minute, validates finite coordinates and state
fields, sorts observations, and keeps the last source row at duplicate times.
API `onGround` flags exclude ground traffic. CSV requires explicit callsign
and aircraft type because the track export does not contain those identifiers
or an airborne flag. Records that lack a usable airborne state remain gaps.

Missing fields may use a reported value from at most 30 seconds earlier.
Speed and track bearing can be derived from the previous position when both
samples are within that age bound; vertical rate can be derived from a recent
accepted altitude. Each field records `reported`, `carried` or `derived`.
The loader rejects altitude jumps exceeding a generous 6,000 ft/min bound and
invalid speeds/headings/rates. Rejected values may recover from recent past
data under the same age limit. These thresholds are explicit `ReplayPolicy`
parameters, not a calibration established from this one flight.

Between source events, reconstruction uses the existing constant-velocity
kinematics for at most 30 seconds and labels the position `extrapolated` with
its source age. Expiry events remove stale aircraft. Reconstruction does not
interpolate using future samples or bridge long coverage gaps. Replay is
finite and rejects traffic-creation and clearance commands. `StateReader.for_airnav`
provides the adapter to other offline pipeline consumers; it remains a
non-mock data source and is intentionally not injected into the editable
airport simulator.

Forecast evaluation uses horizons 30, 60, 120 and 300 seconds. It selects the
nearest later usable observation within ±15 seconds of a requested horizon
and predicts at that observation's actual elapsed time. Both source and truth
altitudes must be reported values. It does not interpolate future truth.
The exported rows contain requested and actual horizon, source/truth UTC,
horizontal error in NM and absolute altitude error in feet. This is one-flight
descriptive validation, without a training or tuning stage.

The source response contains 698 positions, many with null fields. In the
arrival window there are 22 source observations. At five minutes, the baseline
matches 11 future-observation pairs and has a mean horizontal error of about
4.37 NM, illustrating why constant velocity cannot fully represent the
approach's turns and speed changes. Refer to a freshly generated report for
the exact results and denominator for every horizon.

## Provenance and limits

Stable source copies live in `scenarios/recorded/airnav/`, with an acquisition
request, airport-context snapshot and manifest. The response's download-link
token values are redacted; no API key is required or stored in project code.
Every report contains the source SHA-256 and replay policy.

Recorded altitude is retained without correcting its datum to AMSL. The
separately captured Airport View weather and runway-use snapshot provides
context only and does not alter replay physics. The recording ends before
the displayed landing timestamp, so there is no inferred taxi or gate-arrival
segment. Larger observed multi-flight datasets are required to validate
complexity, conflicts, congestion, capacity or ATFM outcomes against reality.
