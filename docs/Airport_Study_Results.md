# VVTS linked airport/TMA study replay

The five mock scenarios were replayed for 2,200 simulation seconds each with `python -m scripts.run_airport_studies`. The detailed event times are in `output/airport_study_results.json`.

| Scenario | Departures | Arrivals at touchdown | Mean taxi-out | Total departure hold | Last takeoff |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline | 1 | 1 | 104 s | 0 s | 105 s |
| Immediate departure surge | 5 | 0 | 220 s | 453 s | 337 s |
| Stand metering, 60 s release interval | 5 | 0 | 127 s | 0 s | 389 s |
| CTOT timed release, 60 s slot spacing | 5 | 0 | 221.2 s | 459 s | 341 s |
| Mixed departures and arrivals | 3 | 2 | 162 s | 141 s | 221 s |

Stand metering reduced mean taxi-out by 93 seconds and removed 453 seconds of departure holding compared with immediate release. The last of five departures took off 52 seconds later. This is the simulated tradeoff for the chosen 60-second stand release spacing, not a claim about VVTS runway capacity.

The CTOT study targeted wheel-off at 100, 160, 220, 280, and 340 seconds. Actual takeoffs occurred 5, 3, 1, 1, and 1 seconds after their targets. Its large holding total shows that slot control at the runway alone can move waiting from stands to the taxi queue. No operational CTOT tolerance window has been assumed.

In the mixed study, two ILS arrivals appeared on the airport approach extension before touchdown, rolled on 25R, exited the runway, waited 30 seconds for 25L crossing clearance, crossed 25L, and reached their stands. Their TMA runway-roll tracks remained visible until the airport runway-exit event. The five flight identities and FPL fields persisted through their handoffs.

These are deterministic mock runs using AEON's layout and indicative A320 movement profiles. Real taxi times, stand choices, runway occupancy, slot tolerances, and traffic demand are needed before treating the measures as operational estimates.
