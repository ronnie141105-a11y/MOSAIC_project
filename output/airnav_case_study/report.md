# AirNav VVTS arrival case study

Source SHA-256: `ddd7c4d8af0cdf92374410ce6b9dbb7928886c520a584c7d4ae997c0aa33da5c`

| Case | Kind | Peak aircraft | Peak complexity | Pair exposure (s) | Pair coverage (s) |
|---|---|---:|---:|---:|---:|
| Observed VN243 arrival | observed | 1 | 0.00 | 0.00 | 0.00 |
| Hypothetical wave · 30 s | synthetic | 4 | 64.15 | 1563.06 | 542.30 |
| Hypothetical wave · 120 s | synthetic | 4 | 48.47 | 0.00 | 577.71 |

Prediction error is measured against later recorded observations, without exposing future tracks to prediction.

| Horizon (s) | Matched pairs | Mean horizontal error (NM) | Mean altitude error (ft) |
|---:|---:|---:|---:|
| 30 | 17 | 0.187 | 83.9 |
| 60 | 16 | 0.451 | 242.9 |
| 120 | 15 | 1.120 | 543.3 |
| 300 | 11 | 4.368 | 1585.9 |

- Only VN243 is observed. The two four-aircraft waves are hypothetical time-shifted copies, not recorded airport traffic.
- Playback uses past observations and at most 30 seconds of causal extrapolation. Aircraft disappear when data expires or the recording ends.
- Predictions use constant velocity. No filed route, SID/STAR assignment or future track is supplied to the predictor.
- Forecast errors use later reported observations within ±15 seconds of each requested horizon, predicted at the actual elapsed time. No future truth is interpolated.
- Thresholds and complexity scores use the existing VVTS research configuration; these are not verified operational separation minima.
- Recorded altitude datum is retained without an AMSL correction. The weather/context snapshot was captured separately and does not drive replay physics.
- Candidate clearances are counted but never applied. Pair exposure measures the reconstructed cases, not observed incidents or proved ATFM benefits.
