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
- GA ground searches departure timing and parked-departure order; the mixed extension is reported separately.
- Report executed outcomes; GA results average ten fixed seeds.

Say: “The main comparison uses the same ground-control options; GA can optimize the parked-aircraft sequence.”

## Slide 4 — Results

Use **comparison.png** and the four-row table in **thesis_summary.md**.

- Nominal: see the separate executed comparison; sector overload is zero.
- Sector excess changed from 55.88 to 43.38 aircraft-minutes (GA minus FCFS: -12.50). Event delay changed from 2468.33 to 2533.93 aircraft-minutes (GA minus FCFS: +65.60).
- Modelled spacing and runway checks passed.

## Slide 5 — Conclusion

- GA reduced sector excess with the reported delay trade-off.
- Residual sector overload remains.
- Two synthetic scenarios and ten fixed seeds describe this model and traffic.

## One-minute explanation

"MOSAIC connects Centre, Approach and Tower, including aircraft movements on the ground. I tested two synthetic scenarios: nominal traffic with 20 aircraft and overload traffic with 60 aircraft. I compared a strengthened FCFS baseline with a Genetic Algorithm that adjusts departure timing and parked-departure sequence. A mixed extension with arrival speed control is reported separately. Sector excess changed from 55.88 to 43.38 aircraft-minutes (GA minus FCFS: -12.50). Event delay changed from 2468.33 to 2533.93 aircraft-minutes (GA minus FCFS: +65.60). All compared executions passed the modelled spacing and runway checks. GA reduced sector excess with the reported delay trade-off. These results describe the constructed traffic, not all real operations."

Use “event delay” with its fixed readiness and uncontrolled-touchdown clocks. Quote all ten-run means, not only the best replay. Separate initialization gains from improvement after search. See source_runs.json for the exact saved experiments.
