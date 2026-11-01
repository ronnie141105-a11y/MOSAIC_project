# Review and integration of the teammate's GA — 20 October 2026

## Decision

Use the teammate's GA design, with corrected operators and MOSAIC's existing
case-study evaluator. The supplied implementation is a useful capacity-only
prototype. Using it unchanged would omit the project's separation constraints
and could assign GDP after an aircraft has departed.

The teammate's original source is preserved byte for byte under
`reference/teammate_ga/`. Credit for the categorical GA design belongs to the
project teammate; the integration and fixes are an adaptation of that contribution.

## Review findings

1. **High: elitism loses evaluation.** New `Individual` objects for elites copy
   genes but reset fitness to zero. An elite that had fitness 1.0 becomes 0.0;
   ranking and tournament selection then treat it as poor. Fixed by cloning both
   genes and objective; fitness is derived from that objective.
2. **High: incomplete constraint model.** Original penalty counts only excess
   arrivals in hourly bins. `sector_slot` is unused. Zero penalty cannot establish
   horizontal separation, arrival/departure separation or GDP eligibility. The
   integrated engine delegates scoring and gene legality to `VideoCaseEvaluator`.
3. **Medium: last generation can be discarded.** The original generates a final
   population and exits without comparing it with the archived best. The new
   search archives every evaluated improvement and includes the final generation.
4. **Medium: crossover fails for one flight.** `randint(1, 0)` raises `ValueError`.
   Empty/single-gene crossover now returns safe copies.
5. **Medium: malformed chromosomes are accepted.** An empty chromosome evaluated
   against one flight returns fitness 1.0 and zero penalty. The adapter validates
   one legal gene per flight, integer types, allowed levels and flight eligibility.
6. **Model assumption: speed-to-delay conversion.** `int(level * 0.5)` does not
   follow flight distance/time and truncates fractional minutes. The integrated
   model uses `T * r / (100-r)` with an explicitly assumed T=20 minutes upstream.
   It shifts terminal timestamps; it does not simulate a speed command on the
   newly added Centre routes.
7. **Experiment weakness: the demo needs no control.** Its 20 flights fit below
   capacity 42. The zero-control plan has exactly zero cost and zero capacity
   penalty. Reproducing this result demonstrates execution, not congestion relief.
   Our actual cases have only 23 and 37 optimized arrivals in their entire two-hour
   windows. An arrivals-only capacity limit of 42/hour therefore cannot activate
   on either case, regardless of the chosen delays. Fixed departures and terminal
   separation must be included for the optimizer to address these scenarios.
8. **Reproducibility:** replace global random state with a per-run RNG and save
   seeds, code/input hashes, objective histories and evaluation counts. Remove
   duplicate GDP=0/speed=0 representations; use the single no-action gene (0,0).

## What is retained and what changes

| Part | Integrated implementation |
|---|---|
| Chromosome | One (measure, level) gene per arriving flight |
| Measures | No action, GDP 5/10/15/20 min, speed reduction 5/10/15% |
| Selection | Tournament k=3 |
| Crossover | One point, probability 0.8, two children |
| Mutation | Probability 0.1 per gene; resample a legal measure then a legal level; categorical, not Gaussian |
| Elitism | At least one and ceil(10% of population), copying evaluation |
| Fitness | 1 / (1 + objective) |
| Stop | Generation limit, unique-evaluation budget, 30 stagnant generations, or zero-cost feasible plan |
| Initialization | No-control + greedy incumbent; half exploration, half mutations of incumbent |
| Constraints | Existing MOSAIC case evaluator, including fixed departures |
| Original costs | GDP 1.5/minute and speed 1/percentage point are recorded in the reference only |
| Integrated costs | Existing MOSAIC GDP 1/minute and speed 2/minute of induced delay, retained for comparability |
| Original penalty | Squared capacity excess only |
| Integrated penalty | Existing linear capacity excess + violating pairs + new violating pairs; lambda=1000 |

The objective formulation was deliberately kept on the existing MOSAIC scale.
Changing costs or penalty powers at the same time would confound comparison of
search algorithms. All costs remain assumed research units, not monetary costs.

## Experiment and comparison

Both approved cases use the same reconstructed source manifests/tracks as before.
Only arrivals receive controls; departure schedules stay fixed. Ground eligibility
uses the existing planning time (60 min before the window) and assumed origin
takeoff (95 min before requested landing). No constraint is relaxed to make GA
appear feasible.

Comparators are no control, deterministic two-pass coordinate greedy (GDP and
mixed), and the previous GA (GDP and mixed). Both GA engines start from the same
deterministic GDP incumbent, use the same evaluator and receive the same total
budget including preparation. The teammate GA stops after 30 stagnant generations;
the previous engine uses 40. Population initialization and mutation differ.
The new benchmark is a fresh protocol: its numbers should not be directly treated
as a reproduction of the October 13 experiment, which prepared an incumbent with GA.

Search checks are sampled every 20 s. Selected best teammate plans, no control and
greedy mixed are checked again at 5 s. The selected plan is ranked by the 20 s
objective; the 5 s check can discover additional violations and is reported
separately. A positive unavoidable-pair bound proves infeasibility only within
these discrete actions, eligibility assumptions and sampled terminal paths.

Capacity is 42 combined arrivals/departures in fixed 60 minute bins relative to
case start, including the delayed tail; it is not a rolling-hour constraint or
verified declared VVTS capacity. Arrival pairs use 10 NM / 20 NM when heading
difference is at most 25 degrees; they do not use vertical separation. Arrival vs
departure is a diagnostic at 5 NM and 1,000 ft. Checks cover 40 NM and
3,000–16,570 ft. Centre/FIR extensions are outside this evaluation.

## Run and use

```powershell
.venv\Scripts\python.exe -B -X utf8 scripts/run_teammate_ga.py
```

Defaults: both cases, ten seeds (11…110), population 80, maximum 150 generations,
6,000 unique evaluations per method/seed. `--case nominal --seeds 11` is a short run.
`--no-legacy-comparison` skips the older GA. Results and CSVs are in
`output/teammate_ga/<run_id>/<case>/`.

Open `/case-scenarios` → **Chạy GA trên hai ca nghiên cứu**. Select a case,
run or inspect saved results, then **Nạp phương án phối hợp mới lên radar**.
The new **GA cộng tác** replay choices also appear in the method selector.
The current simulation clock is unaffected while a job computes.

Published tracks and results live in immutable
`scenarios/reconstructed/vvts_video_cases/<case>/variants/team_ga/<run_id>/`.
The `latest.json` pointer changes only after a complete publication; older runs,
the original FCFS cases, and October 13 GA variants/results remain available.
Each manifest stores its optimizer run ID and the finer validation metrics.

## Remaining limitations

The attached algorithm cannot recover missing flight plans or make incompatible
constraints feasible. Nominal arrivals are synthetic; other identities came from
screen recordings, while trajectories and timing targets are reconstructed.
Replay illustrates a retimed terminal plan, rather than physically executing GDP
at each origin airport or speed reductions along the FIR. Sampled checks do not
establish continuous or operational separation. Residual violations stay visible.
