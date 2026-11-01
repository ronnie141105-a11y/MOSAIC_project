# ATFM GA search improvement — 2 October 2026

This update improves the existing synthetic arrival-entry optimizer. It does not
implement robust optimization or validate trajectories against real VVTS operations.
The 29 September report in `ATFM_LAB_EVALUATION_VI.md` describes the previous version.

## Changes

- Mixed search receives the same seed's optimized ground-only plan as an incumbent.
  Its first evaluation is that plan, and elitism preserves the best evaluated plan
  even if an evaluation limit interrupts population scoring.
- Crossover inherits each flight's ground/speed pair together. Mutation can transfer
  delay between the two measures without changing its request time, and can also
  change timing. Transfers respect ground eligibility and both measure bounds.
- `optimize()` keeps its `(plan, history, count)` return interface. New optional
  keyword arguments are `incumbent`, `max_evaluations`, and `diagnostics`.
- Fitness evaluation caps include the cached evaluations used to prepare heuristics.
  Convergence records include evaluation counts. Runtime and stop reasons are saved.
- CLI and HTTP KPI exports include preparation, search, total evaluation counts and
  inclusive runtime. The dashboard shows inclusive costs and plots convergence
  against total evaluations. Previously saved results still display, with unknown
  inclusive costs left blank rather than invented.
- Bounded exhaustive enumeration checks small integer-minute decision grids. It
  refuses the 54-flight grid before evaluating it. This establishes optimality on
  the tested grids using the same evaluator, not independent model validity.

## Fair comparison and budget accounting

With population 60 and 100 generations, the incumbent stage has at most
`60 + 58 * 100 = 5,860` distinct fitness evaluations. The total cap is 11,720.

For each of seeds 11/22/33/44/55:

1. `GA_GROUND_<seed>` produces the reference incumbent with a 5,860 cap.
2. `GA_CONTINUED_GROUND_<seed>` continues ground-only search from that incumbent.
3. `GA_MIXED_<seed>` continues mixed search from that same incumbent.

Both continuations have the SAME total cap, including the ground preparation cost,
and the same population and refinement generation limit. Refinement uses seed+1000.
Actual evaluation counts may differ because duplicate plans reuse cached scores.
The budget counts fitness calls; final KPI/audit evaluations, FCFS comparisons,
stress re-evaluations and exact checks are outside the search cap and inside the
experiment's overall wall-clock measurement.

The incumbent is computed once and shared by the experiment, but its cost is
included in each continuation's standalone runtime/count. Do not add those
inclusive runtimes to infer the experiment's elapsed time.

The guaranteed bound is that each continuation scores no worse than its INITIAL
ground incumbent under the unchanged objective. There is no mathematical guarantee
that mixed beats ground-only continuation or that either reaches a global optimum.

`--max-evaluations` overrides the TOTAL cap and reserves half for preparation.
With a cap of one, both continuations simply retain the incumbent.

## New five-seed results

All values below are means over five seeds. Delay values are summed flight-minutes
across 54 flights; maximum delay is minutes per flight. Lower objective is better.

| Method | Ground | Speed | Holding | Total delay | Maximum delay | Objective |
|---|---:|---:|---:|---:|---:|---:|
| GA ground incumbent | 986.00 | 0.00 | 449.62 | 1435.62 | 51.35 | 2794.75 |
| GA ground continuation | 994.00 | 0.00 | 441.62 | 1435.62 | 51.35 | 2770.75 |
| GA mixed continuation | 968.20 | 114.60 | 352.82 | 1435.62 | 51.32 | 2618.94 |

Mixed continuation reduced weighted objective by approximately 5.48% and holding
by approximately 20.11% relative to the matched ground continuation. It beat that
comparator in all five seeds. Mean total arrival delay was unchanged. Airborne extra
(speed absorption plus holding) increased from 441.62 to 467.42 flight-minutes, so
reduced holding must not be reported as reduced total airborne delay.

Ground continuation used 11,703–11,712 total evaluations; mixed used 11,713–11,715.
Both remain below the 11,720 cap. All 18 methods, including the three FCFS/baseline
cases, served 54/54 flights and passed delay, capacity and occupancy audits.

Frozen-plan ETA stress (three perturbation seeds, ±2 minutes) produced mean
objectives 3646.86 for ground continuation and 3447.38 for mixed continuation.
These are still post-optimization stress checks, not uncertainty-aware fitness
or evidence of operational robustness.

## Validation

- 33 focused ATFM tests passed, including existing API, replay and background-job
  integration plus new incumbent, tight-budget, mutation and exact-search checks.
- 18 small-case benchmark records had zero optimality gap: three cases, two measure
  sets and three GA seeds. A one-flight optimum is also checked by hand calculation.
- Full regression verification: 241 tests passed initially; the remaining airport
  test passed when rerun from the project directory. Its first failure was a
  relative-path lookup caused by running from Downloads. All 242 cases passed.
- Updated JavaScript passed Node's syntax check.

## Run

From `C:\Users\Lenovo\Downloads\MOSAIC_project`:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_atfm_experiment
# Optional total evaluation cap per continuation, INCLUDING preparation:
.\.venv\Scripts\python.exe -m scripts.run_atfm_experiment --max-evaluations 8000
.\.venv\Scripts\python.exe main.py --mock --profile tsn_tma --port 8052
```

The ATFM page is `/atfm`. Restart an existing server to load the revised modules
and saved results. CLI exports now also include `exact_checks.csv` and
`convergence.csv`, alongside KPI, per-flight, stress and sensitivity files.

## Next development stage

Optimize across separate ETA/capacity realizations and assess on unseen seeds.
Then connect fitness evaluation to the procedure-based trajectory model, with
explicit merge/spacing resources. The current pooled entry schedule and schematic
replay remain the model boundaries of this update.
