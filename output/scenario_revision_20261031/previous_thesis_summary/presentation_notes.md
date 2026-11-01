# Presentation notes

## Slide 1 — Problem

- Traffic demand can exceed sector capacity.
- The aim is to reduce overload while preserving separation and runway protection.

Say: “This study examines the trade-off between traffic delay and sector congestion.”

## Slide 2 — Simulation

- Centre → Approach → Tower, including taxi and parking.
- Nominal: 20 aircraft. Overload: 60 aircraft.
- The two cases share sector limits and safety rules.

## Slide 3 — Comparison

- FCFS preserves departure readiness order and assigns ground delays.
- GA searches departure timing, parked-departure order and arrival speed.
- Report executed outcomes; GA results average three seeds.

Say: “The GA has more control options, so I compare the complete methods.”

## Slide 4 — Results

Use **comparison.png** and the four-row table in **thesis_summary.md**.

- Nominal: no added delay or overload for either method.
- Overload: sector excess fell from 28.32 to 19.25 aircraft-minutes — 32.0% lower.
- Added delay rose from 518.37 to 555.07 aircraft-minutes — 36.71 more.
- Modelled spacing and runway checks passed.

## Slide 5 — Conclusion

- GA reduced sector overload by accepting some additional delay.
- Residual overload remains.
- Two synthetic scenarios and three seeds are a pilot study.

## One-minute explanation

"MOSAIC connects Centre, Approach and Tower, including aircraft movements on the ground. I tested two synthetic scenarios: nominal traffic with 20 aircraft and overload traffic with 60 aircraft. I compared FCFS with a Genetic Algorithm that adjusts departure timing, departure sequence and arrival speed. Both methods handled nominal traffic without extra regulation. Under overload, GA reduced sector excess by 32.0 percent, with 36.71 additional aircraft-minutes of delay (7.1%) compared with FCFS. All compared executions passed the modelled spacing and runway checks. GA reduced sector overload by accepting some additional delay. The results are preliminary, and overload was reduced rather than eliminated."

Use “added delay,” not total airline delay: the reference already includes safety sequencing. Quote the three-run means, not only the best replay. See source_runs.json for the exact saved experiments.
