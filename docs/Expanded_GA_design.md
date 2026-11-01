# Previous GA design (superseded 2026-11-01)

This file documents the earlier free-resequencing model. It is retained as historical context only. The current implementation uses fixed origin queues, regional GDP and coordinated gate flow; see [Gate flow ATFM](Gate_flow_ATFM.md).

# Expanded full-route GA

The two synthetic workbook cases use `astra/optimization/hybrid_ga.py` through
`full_route_cases.experiment`. The video cases retain the original reviewed
teammate solver. Scenario inputs, traffic counts and capacity limits are unchanged.

## Decisions and prediction

- Departure ground delay: 0–60 minutes in one-minute steps, for FCFS and GA.
- Arrival Centre speed reduction: 0/1/2/3/5/10/15%, only when eligible.
- Nearby parked departures can exchange sequence positions. A decoder converts
  the proposed order into available CTOT actions, respecting readiness and the
  committed departure prefix. An order requiring an unavailable delay is rejected.
- Arrival groups use route-family crossover and coordinated mutations, allowing
  neighbouring traffic to change speed together. Local mutation also explores
  individual aircraft; every resulting combination still undergoes pair checks.
- Predictions use one-second propagation for controlled arrivals and one-second
  arrival-pair checks. Occupancy and mixed/departure screening use twenty seconds.
- Departure-pair tables exploit relative time-shift equivalence. This avoids a
  separate full trajectory comparison for every combination of minute delays.

Safety violations receive a barrier larger than the scenario's capacity and cost
scale. Among safe projected plans, the score is delay cost plus the sector-excess
penalty. The native airport and airborne audits remain mandatory before replay.

## Exploration and execution feedback

The population uses tournament selection, cohort crossover, local CTOT changes,
sequence swaps, and random immigrants. Coordinate refinement occurs periodically.
Ten generations without a projected improvement trigger a diversity restart;
search continues until its generation/evaluation limit rather than ending on
the first stagnation event.

Both one-minute and five-minute FCFS schedules initialize the search. Their
candidate checks count toward each method/seed's fast evaluation allowance.
Keeping the coarse schedule prevents the new domain from losing a useful known
timing pattern merely because a finer schedule has a lower projected cost.

Up to four complete native checkpoints are requested per method/seed, including
the two warm starts. Mid-search and final checkpoints use the remaining budget.
Identical plans share cached native execution. The checkpoint budget is reported
separately from fast objective calls; it is not hidden inside the 6,000-call figure.

A measured execution residual adjusts candidate ranking. The minimum measured
nonnegative residual supplies a common offset; the nearest control vector's
additional residual decays with distance. This is an empirical search guide,
not a proven bound or a replacement for simulation. Repaired speed controls also
enter the fast archive as new seeds. The returned plan is the best **measured**
native incumbent, including a tested FCFS fallback.

`history` stores the best raw projected score for convergence plotting.
`search.native_history` stores measured candidate and best-incumbent scores.
The selected plan can therefore differ from the raw projected incumbent;
`search.projected_incumbent_plan` preserves that distinction for audit.

## Execution and evidence

Each final seed is reported separately, then all seeds contribute to the native
mean and sample standard deviation. The replay uses the seed with the lowest
native objective. Candidate manifests, proposed/executed controls, native
adjustments and per-flight timing are retained under the immutable run folder.

The simulator preserves all initial arrival positions and altitudes, forward
arrival motion, the existing route geometry and descent constraints, 120-second
takeoff spacing, full landing-runway evacuation and a 6 NM cutoff at takeoff-roll start and 30 seconds
from wheel-off to the next touchdown, at most four active surface
departures, and zero holding circuits. Existing airborne traffic may still
create sector excess; that remains visible in the objective and report.

The six-mile gate applies when the takeoff roll starts. Wheel-off must also
precede the next touchdown by more than 30 seconds. Mixed arrival/departure
pairs use 5 NM or 1,000 ft when both are within 40 NM and at or below 10,000 ft,
matching the existing Approach monitor's horizontal model threshold. Other
pairs and Centre traffic retain the existing 10/20 NM study rules. These are
declared simulation assumptions, shared by FCFS and GA.

`requested_schedule_delay_min` measures delay against each baseline flight's
fixed constructed request. `reference_embedded_delay_min` exposes delay already
built into the reference. Neither is a claim of measured real-world airline
delay. Additional regulation remains a separate metric.

Reproduce with the existing `run_full_route_studies.py` and
`report_fcfs_ga_comparison.py` scripts. `output/ga_expansion/previous_results.json`
retains the preceding experiment. Its input hashes must match before comparing
configurations; the before/after comparison changes action resolution and native
computation as well as genetic operators.
