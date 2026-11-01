# ATFM uncertainty optimization — 3 October 2026

This milestone extends MOSAIC's synthetic arrival-entry GA with uncertain ETAs
and entry capacities. It compares nominal optimization with a finite training
ensemble, then evaluates the frozen plans on a separate test ensemble. The
earlier deterministic milestone remains documented in
`ATFM_GA_Search_Improvement.md`.

## Model and objective

- The nominal scenario has 54 flights. Both searches use the existing mixed
  ground-delay and upstream speed-delay decisions and queue evaluator.
- Each perturbed flight receives independent uniform travel-time jitter in
  [-2, +2] minutes by default. ETA and travel time change together; reference
  takeoff time and ground eligibility stay fixed.
- Each 15-minute entry-capacity bin independently loses one slot with probability
  0.25 by default. Tail capacity is sampled in the same way and stays positive.
  These are explicit study assumptions, not measured VVTS forecast distributions.
- Uncertainty fitness is `(1 - risk_weight) * mean_cost + risk_weight * worst_cost`
  over the training ensemble. The default risk weight is 0.25. Cost uses the
  scenario's existing ground, speed, holding and maximum-delay weights.
- Every realization is checked with the existing feasibility audit. Invalid
  capacity, timing and jitter configurations fail before optimization.
- “Worst” means the maximum cost among the finite sampled scenarios. It is not
  a bound for every possible operating condition.

## Selection, evaluation and equal budgets

Training consists of the nominal scenario plus perturbation seeds
201/202/203/204 (five scenarios). Test uses seeds 1001–1012 (12 scenarios), with
no overlap. Test inputs never enter the fitness callback, incumbent search or
plan selection. The same test realizations are paired across methods and GA
seeds; they are not fresh independent samples for every run.

For each GA seed 11/22/33/44/55:

1. Prepare a shared ground-only incumbent using up to 1,200 nominal simulations.
2. Refine it with a deterministic mixed GA using nominal cost.
3. Refine the same incumbent with an uncertainty mixed GA using training risk.
4. Freeze both plans and report their nominal, training and test performance.

Both refinements have a total cap of 6,000 underlying scenario simulations,
including incumbent preparation. A deterministic candidate costs one simulation;
an uncertainty candidate costs five. Duplicate candidate scores reuse the cache.
Population is 40. The uncertainty refinement allows 60 generations; the nominal
refinement allows 200 so it can use the matched simulation budget. Both hit the
6,000 cap in the saved full experiment. This comparison equalizes simulator work;
it does not equalize generations or distinct candidates.

The incumbent is physically computed once per seed, while its cost is charged to
each refinement's standalone total. Whole-experiment search work is therefore
54,000 simulations, rather than the sum of both inclusive totals. Final nominal,
training and test reporting costs another 234 simulations; FCFS preparation costs
three. These reporting costs are recorded separately from search caps. Overall
runtime includes reporting and was 66.62 seconds on this machine.

## Saved experiment

The table averages metrics across the five GA seeds. “Test worst” averages each
seed's maximum cost over the same 12 test scenarios.

| Metric | Deterministic mixed GA | Uncertainty mixed GA | Change |
|---|---:|---:|---:|
| Nominal weighted cost | 2,594.43 | 2,834.06 | +9.24% |
| Training mean weighted cost | 3,319.28 | 3,156.03 | -4.92% |
| Training worst weighted cost | 3,737.76 | 3,481.15 | -6.87% |
| Test mean weighted cost | 3,872.51 | 3,795.65 | -1.98% |
| Test worst weighted cost | 4,718.72 | 4,769.38 | +1.07% |
| Test mean total delay, flight-minutes | 1,753.20 | 1,709.17 | -2.51% |
| Total search simulations per seed | 6,000 | 6,000 | equal |

The uncertainty plan improves test mean cost in four of five GA seeds. Its
average sampled worst cost increases, and nominal cost increases. This experiment
supports a modest average benefit under the assumed distribution; it does not
establish improved test-tail protection. Keep the separate mean and worst columns
when presenting these results. The held-out ensemble was not used to tune this
implementation after inspecting its outcomes.

The test mean costs for BASELINE, FCFS_GROUND and FCFS_MIXED are respectively
6,634.03, 4,124.17 and 3,966.14. Their shared test inputs are identical to the GA
inputs. There is no new exhaustive optimum claim for the uncertainty search.

## Use and exports

Restart the MOSAIC server and open ATFM Lab (`/atfm`). The new default UI mode is
“ETA và capacity bất định”. Controls include risk weight, ETA jitter, capacity
drop and simulation budget. The results show separate nominal KPIs, training/test
summaries, and convergence curves with their respective objective contexts.
Replay always uses nominal event times; it does not replay a test realization.
Legacy deterministic result files still load.

Run the full experiment from the project directory in PowerShell:

```powershell
& .\.venv\Scripts\python.exe -m scripts.run_atfm_experiment --uncertainty
```

Uncertainty CLI output defaults to `output/atfm_uncertainty`; deterministic CLI
output remains `output/atfm_lab`. The saved full uncertainty experiment includes:

- `results.json`: configuration, seeds, plans, nominal rows, convergence and all
  realized scenarios.
- `uncertainty_summary.csv`: separate training/test mean, worst and risk costs.
- `held_out_realizations.csv`: every method on each of the 12 test scenarios.
- `uncertainty_realizations.json`: exact training/test inputs for reproduction.
- `convergence.csv`: objective context and inclusive simulation counts.
- `metrics.csv` and per-method flight CSVs: nominal KPIs and replay rows.

The dashboard's active snapshot is `output/atfm_lab/results.json`, now containing
this uncertainty experiment. Existing deterministic CSVs in that folder remain
from the prior milestone. Use the dedicated uncertainty folder for this study's
CSV exports. HTTP exports include `/api/atfm/uncertainty.csv` and
`/api/atfm/uncertainty-realizations.json`; `/api/atfm/export.csv` remains nominal.
Installation preserves previous source files and the old active JSON in a dated
backup under `output/uncertainty_upgrade`.

## Validation and remaining scope

All 321 tests passed: existing model/search checks plus reproducibility,
realization consistency, training/test isolation, rollout caps, fitness weighting,
input validation, API persistence and CLI/export integration. JavaScript syntax
and rendering smoke checks passed for both new and legacy saved results. Every
saved nominal and perturbed plan passes the model's feasibility audit.

This remains a synthetic queue study. Ground delays and upstream speed delays do
not implement an operational GDP or a full MIT/MINIT spacing policy. The model
does not validate 4D aircraft separation, forecast accuracy, actual TMA capacity
or operational safety. A later study should calibrate and correlate uncertainty
inputs using appropriate data and reserve a new test ensemble before any further
parameter tuning. The present test results should remain a recorded benchmark.
