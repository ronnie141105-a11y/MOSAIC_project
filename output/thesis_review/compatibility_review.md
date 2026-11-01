# Review before writing Chapter 4

Reviewed on 30 October 2026. This is a compatibility review and writing plan, not a Chapter 4 draft. The supplied Word file has not been edited.

## Scope and assessment

Our deliverable is Chapter 4, eventually at least ten pages, with appropriate tables, plots and simulator pictures. Chapter 5 is outside this review. Changes to Chapters 1–3 should be targeted corrections agreed with the other author.

The draft provides a useful ATFM and GA background. Its experimental model, however, differs substantially from the implemented study. Writing Chapter 4 against the current Chapter 3 would make the methods and results inconsistent. The practical solution is to align the method description with the implementation before producing the final results chapter.

The source contains two versions of Chapter 3 and a repeated Section 2.4. References to Section 3 below generally concern the second, expanded version. Consolidate these versions first so that later corrections have one destination.

## 1. Corrections that affect the research question

| Location | Draft description | Implemented study and recommended correction |
|---|---|---|
| Chapter 1, especially scope and objectives | Mainly arrival-flow regulation into TSN; ground delay applied before inbound flights depart their origin | Both arrivals and departures are simulated. Every arrival is already airborne at startup. Ground-delay decisions apply to eligible local departures; eligible arrivals receive upstream speed control. State this explicitly. |
| Sections 1.3, 3.5 | One-hour study, time slots, three light/medium/heavy demand levels | Two constructed cases: nominal **20 aircraft = 11 arrivals + 9 departures**; overload **60 = 36 + 24**. The reporting window is three hours, with simulation continued through the completion tail. These counts are cohorts, not aircraft/hour. |
| Sections 2.4.1, 3.2.2–3.2.3 | Capacity 42 arrivals/hour, maximum 47/hour; squared excess per time bin | The current objective uses simultaneous airborne occupancy in individual sectors. These are different quantities and cannot be substituted for each other. |
| Sections 2.4, 3.2, 3.4 | Capacity never exceeded; no new hotspots | Capacity excess is penalized and remains positive in the overload results. Modeled separation/runway protection and capacity compliance are separate outcomes. Remove claims that every published solution satisfies all capacity limits. |
| Sections 3.4–3.5 | Hotspot-focused rolling optimization every 15–30 minutes; forecast 5–10 minutes | The saved case-study experiments optimize a batch using complete modeled trajectories. DBSCAN/PCA exists in the platform, but hotspot counts are not an explicit term in this experiment's objective, and the saved experiments do not demonstrate rolling online reoptimization. |
| Section 3.5 | Fixed ten-minute ground-delay baseline; possible PPO comparison | Actual methods are safety-sequenced Reference, FCFS, GA ground and GA mixed. No PPO experiment is included. |

**GDP terminology needs care.** A GDP targeting inbound demand normally meters flights at their departure airports. The current experiment cannot ground-delay TSN arrivals that are already airborne. Describe its implemented control as departure ground-delay/CTOT regulation at TSN plus upstream arrival speed management. The general GDP explanation can remain in Chapter 2, with this distinction. The [FAA GDP definition](https://www.faa.gov/air_traffic/publications/atpubs/foa_html/chap18_section_10.html) supports the distinction between arrival-slot assignment and ground holding before departure.

Current sector capacities are synthetic assumptions, not declared operational capacities:

| Sector | Simultaneously airborne aircraft |
|---|---:|
| VVTS Approach | 6 |
| HCM-S1 | 4 |
| HCM-S2 | 3 |
| HCM-S5 | 3 |
| HCM-S6 | 3 |
| HCM-S7 | 3 |

Approach membership within 40 NM takes precedence; the Centre sectors use the saved lateral and vertical boundaries. Ground aircraft and aircraft in other sectors do not count against a sector's limit. The source's 42/47 hourly values have not been established here as actual VVTS operating capacities. Either support them with a dated local source as background, or remove them from the implemented model description. They should not be presented as the capacity used in our experiments.

## 2. Mathematical corrections

### Speed reduction and delay: Section 3.2.2

The constant-distance, uniform-speed formula in the draft is correct under its stated assumptions:

\[
\Delta T=T_0\left(\frac{1}{1-r/100}-1\right).
\]

However, replacing it by `0.5 × r` minutes is inconsistent with the stated original travel time of 10–15 minutes:

| Speed reduction | Exact added time for a 10–15 min segment | Draft shortcut |
|---|---:|---:|
| 10% | 1.11–1.67 min | 5.00 min |
| 15% | 1.76–2.65 min | 7.50 min |

For small reductions the first-order approximation is `T0 × r / 100`, so the coefficient would be about 0.10–0.15 for that segment duration, not 0.5. For our implementation, describe trajectory propagation and measurement of the resulting runway event time rather than using a fixed conversion coefficient. The displayed Chapter 2 formulas for travel time, MIT, MINIT and delayed arrival time are reasonable simplified expressions; their assumptions and units must remain explicit.

### Capacity objective: Sections 2.4 and 3.2.2

For the implemented study, define:

\[
E=\frac{1}{60}\sum_s\int_0^T\max\{n_s(t)-C_s,0\}\,dt,
\]

where time is in seconds, `n_s(t)` is simultaneous airborne occupancy and `C_s` is the sector limit. `E` is measured in aircraft-minutes. The implementation approximates this integral using sampled occupancy: 20 seconds for fast screening and one second for final native execution.

Among plans passing the modeled safety checks, the executed objective is:

\[
J=D_{dep}+2D_{arr}+10\,000E.
\]

`D_dep` and `D_arr` are summed positive increments in departure takeoff time and arrival touchdown time relative to the safety-sequenced reference. They are not simply the proposed genes, time spent at stand, or measured airline schedule delay. The arrival term includes any additional arrival event delay, not only the nominal speed proposal. The search also applies a separate scenario-scaled barrier for modeled safety/order violations, and final selection uses complete simulator execution.

The draft instead uses weight 1.5 per ground-delay minute, weight 1 per percentage point of speed reduction, lambda 1,000 and squared hourly excess. That is a different objective. Weights with different physical inputs can be defined in common cost units, but the conversion and units must be explicit. Our current weights are assumed priorities, not calibrated monetary costs or measured fuel savings.

The statement that differentiability is important for GA convergence should be removed. This discrete GA does not use gradients. A squared penalty is a possible modeling choice, but differentiability does not establish its suitability for this algorithm. Similarly, a large finite penalty does not itself prove that capacity violations disappear.

### Decision domains and feasibility: Sections 3.2.1, 3.2.3, 3.3.1

The `(measure, level)` concept remains compatible with the implementation. Its domains need updating:

- Eligible departure: no action or **1–60 minutes** of proposed ground delay, in one-minute steps.
- Eligible upstream arrival: no action or **1, 2, 3, 5, 10, 15%** speed reduction.
- Ineligible flight/action: excluded from that flight's domain. Already-airborne arrivals cannot receive ground delay.
- Parked departures can exchange sequence positions through the decoder; already-committed aircraft retain priority.

The domain size is flight-specific. For the action-vector component it is the product of the individual domain sizes, not universally `8^N`. The draft's arithmetic `8^20 ≈ 1.15 × 10^18` is correct for its assumed eight-action model, but that assumption is not our implemented domain. Sequence decoding adds another part of the search design.

Legal individual genes do not guarantee a safe or capacity-feasible combined solution. Interacting trajectories still need validation.

### Speed and separation assumptions

The draft should not present 20 minutes of GDP or 15% speed reduction as universal technical/regulatory limits. They are selected study bounds unless a specific applicable source establishes otherwise. The [FAA GDP information page](https://www.fly.faa.gov/ais/Help/ais_message_help.html) describes delays as depending on demand and acceptance rate, and includes an example with maximum delay above 30 minutes. This is sufficient to reject a universal 20–30-minute ceiling attributed generically to the FAA.

Distinguish the simulator's ground-speed trajectory variable from operational IAS/Mach instructions. [FAA speed-adjustment guidance](https://www.faa.gov/air_traffic/publications/atpubs/atc_html/chap5_section_7.html) discusses aircraft performance, altitude, time to achieve a speed, and IAS/Mach. It is a useful reference, not a substitute for applicable Vietnamese procedures.

Describe the actual conditional model rules rather than a blanket 10 NM everywhere: Centre uses the study's 10/20 NM policy, while terminal mixed arrival/departure pairs use 5 NM or 1,000 ft when both aircraft meet the 40 NM/10,000 ft conditions. Other pair rules remain in force. The model also imposes 120-second arrival transfer and departure takeoff spacing. Do not use “RVSM” as a blanket explanation of every 1,000 ft check at every altitude.

Runway release in the current cases requires full previous-arrival runway evacuation, the next arrival outside 6 NM when the departure roll starts, and more than 30 seconds from wheel-off to the next touchdown. These are declared simulator assumptions shared by all methods, not a claim of certified operational separation.

## 3. Algorithm settings and flowchart

| Item | Draft Chapter 3 / embedded flowchart | Current case-study implementation |
|---|---|---|
| Population | 80 | 60 |
| Generations | 150, sometimes 150–300 | At most 120 |
| Fast evaluations | Not clearly specified | At most 6,000 per method/seed, including fine/coarse FCFS warm starts |
| Simulator feedback | Final replay mainly | Up to four separately counted complete execution checkpoints per method/seed |
| Repeated runs | 10–20 | Three seeds: 11, 22, 33 |
| Initialization | 70% random, 30% hotspot heuristic | Fine/coarse FCFS warm starts, no-action plan and mutations |
| Selection | Tournament 3, sometimes 3 or 5 | Tournament 3 |
| Elitism | 10% | Approximately 10%, minimum two individuals |
| Crossover | One/two point, Pc = 0.8 | Route-cohort crossover and sequence-aware operations |
| Mutation | Uniform/Gaussian, Pm = 0.1 | Sequence swaps, coordinated arrival changes, local minute refinement and random exploration |
| Stagnation | Stop after 30–50 generations | Diversity restart after ten stagnant generations; continue within budget |
| Final plan | Best fitness candidate | Best measured native incumbent, with tested FCFS fallback |

The embedded algorithm flowchart repeats the old population, probabilities, initialization and stopping rule. Redraw it after consolidating Chapter 3. Do not retain it alongside updated prose.

The general discussion of selection/crossover/mutation can remain in Chapter 2, provided generic examples are not represented as the implemented operators. Statements such as a universal “Pm above 0.15 becomes random search” need qualification. The meaning of the mutation probability and the problem encoding matter.

## 4. What the present evidence supports

The latest saved experiments use evaluator `full-route-hybrid-ga-8`:

- Nominal: `20261030T141243Z-bb5aa8fc`.
- Overload: `20261030T140230Z-a23210aa`.

These should be pinned when preparing Chapter 4. Older screenshots and reports may use earlier surface, runway-gap or separation rules. The legacy folder name `workbook_peak_50` now contains the 60-aircraft overload case; never label it as 50 aircraft in the thesis.

All methods in nominal have zero **additional** delay and zero sector excess. This does not mean the nominal simulation has no stand waiting, taxiing or safety-sequencing delay; those may already be embedded in the reference.

Overload results below are complete simulator execution measurements. GA entries summarize all three seeds using the sample standard deviation:

| Method | Additional delay, aircraft-min | Sector excess, aircraft-min |
|---|---:|---:|
| Reference | 0.00 | 46.18 |
| FCFS | 518.37 | 28.32 |
| GA ground | 626.37 ± 0.00 | 19.98 ± 0.00 |
| GA mixed | 555.07 ± 123.49 | 19.25 ± 1.27 |

GA mixed reduces sector excess by about **32.0%** relative to FCFS while adding about **36.7 aircraft-minutes**, or **7.1%**, of additional delay. This is evidence of a congestion–delay trade-off. It does not support a claim that GA reduces both delay and congestion in these experiments.

GA ground versus FCFS is the main comparison with comparable control availability. GA mixed has additional arrival-speed controls, so its advantage combines the search method and a broader action set. Do not attribute the entire difference solely to GA.

The final saved executions report zero modeled spatial separation, runway protection and transfer violations. Residual overload remains. All arrivals already being airborne also limits what local departure holds can achieve. No holding circuits are introduced, so an airborne-holding reduction claim cannot be established from these cases.

Three seeds provide pilot evidence, not the 10–20 runs promised in the draft or proof of statistical superiority. Either revise the draft to match three pilot runs, or later expand the experiment before finalizing the thesis. No new experiments were run for this review.

Do not confuse sample SD across seeds with fairness across aircraft. The draft's fairness criterion requires the distribution of individual flight delays, and it is not currently an explicit objective term.

Full saved experiment elapsed times are about 25.4 seconds for nominal and 786.8 seconds for overload. These cover different workloads and include multiple methods, seeds and validation. They do not establish an online decision latency or a controlled runtime comparison with PPO.

**A reporting label also needs correction before Chapter 4:** the current `completed_in_original_window` field counts takeoff/touchdown event timestamps inside the three-hour window. It does not count complete arrival taxi-to-stand journeys. Label it as runway movements within the window, or compute a separate whole-journey completion measure from `completed_s`. The current comparison report's “Completed in first 3h” heading is ambiguous.

## 5. Draft structure and reference corrections

Consolidate the duplicate Chapter 3 and repeated Section 2.4; remove the repeated GDP scope paragraph in Section 2.2.2.1. Complete the empty headings, the Chapter 1 programming-language placeholder, and equation/section numbering. Preserve useful Chapter 2 theory, distinguishing general examples from adopted model assumptions.

Several in-text citation numbers point to unrelated bibliography entries. For example, Goldberg/Eiben–Smith and Hansen/Xiao discussions do not consistently map to the authors listed under the cited numbers. Rebuild citations from a single reference list rather than repairing isolated numbers manually.

Primary-source metadata checks identified concrete bibliography errors:

- **[6] Xiao, Cai and Abbass (2018):** volume 115, pages **35–55**, not 1–20. [Publisher record](https://www.sciencedirect.com/science/article/abs/pii/S1366554517310049), DOI `10.1016/j.tre.2018.04.011`.
- **[7] Knee-guided ATFM paper:** the authors are **Tong Guo, Yi Mei, Ke Tang and Wenbo Du**, not Y. Zhang et al. The author's own record gives **28(4), 994–1008**, rather than 28(2), 345–358. Check the publisher's online-first versus issue year when formatting the final entry. [Author publication record](https://buaaguotong.github.io/publication/knee-guided-evolutionary-algorithm).
- **[10] Dynamic-capacity/co-evolutionary GA paper:** the authors are **Xuejun Zhang, Yan Zhou, Bo Liu and Zheng Wang**, with proceedings pages **580–585**, not L. Weigang et al., 1–6. [Author's institutional repository](https://eprints.gla.ac.uk/209603/), DOI `10.1109/ITSC.2007.4357707`.

This is a targeted check, not verification of every bibliography claim. General ICAO/FAA references alone do not establish TSN-specific hourly capacity values or economic coefficients. Assertions that GA is cheaper, faster or more transparent than PPO also need a defined comparison or more restrained wording.

## 6. Proposed Chapter 4, approximately 12–14 pages

Preserve the source's main sections, **4.1 Kết quả nghiên cứu** and **4.2 Thảo luận**. Suggested subsections and page allocation:

| Section | Content | Approx. pages |
|---|---|---:|
| 4.1.1 Thiết lập mô phỏng và phương pháp đánh giá | Data provenance, system boundary, two cases, capacity units, common rules, methods and exact settings | 2.5 |
| 4.1.2 Kết quả kịch bản danh định | Traffic overview, occupancy, no-unnecessary-intervention result and interpretation | 1.5 |
| 4.1.3 Kết quả kịch bản quá tải | Traffic overview, FCFS and GA outcomes, remaining overload, representative executed controls | 2.5 |
| 4.1.4 So sánh phương pháp đối chứng và phương án GA | Common-axis results, delay/congestion trade-off, ground-only versus mixed capabilities | 2.0 |
| 4.1.5 Độ hội tụ, biến động giữa các lần chạy và thời gian tính toán | Projected versus executed objective, all seeds, budgets and qualified runtime | 1.5 |
| 4.2 Thảo luận | Interpretation, limits, model assumptions, applicability and comparison with relevant literature | 2.0 |
| **Total** | Final pagination to be checked after Word layout | **12.0** |

Use figures and tables to explain evidence rather than fill pages:

1. System/data-flow diagram: Centre → Approach → Tower, proposed controls → simulator execution → evaluation.
2. Scenario and data-provenance table: 20/60 aircraft, arrival/departure counts, route families, startup states and constructed versus workbook-derived fields.
3. Common assumptions and GA/FCFS settings tables.
4. Supervisor screenshot showing the connected views; a Tower ILS/apron screenshot explaining ground and arrival behavior.
5. Sector occupancy time series with capacity lines and identical scales across methods. Include the sector driving overload and explain any initial/inherited excess.
6. Native-results table for all four methods; plots of additional delay and sector excess with seed variability.
7. Convergence plot distinguishing raw projected score from the measured native incumbent. These histories are different quantities.
8. Individual-flight delay distribution and selected CTOT/TOBT/control examples, if used to discuss fairness and execution.

Existing useful pictures include `output/north_tower/supervisor_ils_apron.png`, `output/north_tower/tower_ils.png` and `output/arrival_gap/tower_departure_gap.png`. Check their scenario/version and capture fresh results views when assembling the final chapter. A simulator screenshot demonstrates behavior; numerical performance claims must come from the exported executed results.

The supplied Word document uses A4 portrait with one-inch margins. Preserve its agreed thesis formatting when appending Chapter 4, then verify the actual page count and placement of captions, tables and figures. No page count or layout quality has been confirmed in this review: text, native equations and embedded pictures were inspected, but the packaged Word renderer was unavailable.

## 7. Evidence files for the next writing step

- Source Word document: [supplied thesis draft](<C:/Users/Lenovo/Downloads/MOSAIC_project/Tối ưu biện pháp điều tiết luồng không lưu tại sân bay Tân Sơn nhất sử dụng thuật toán di truyền (GA).docx>).
- [Executed comparison report](C:/Users/Lenovo/Downloads/MOSAIC_project/output/fcfs_ga_comparison/report.md), [all native trials](C:/Users/Lenovo/Downloads/MOSAIC_project/output/fcfs_ga_comparison/all_native_trials.csv) and [comparison CSV](C:/Users/Lenovo/Downloads/MOSAIC_project/output/fcfs_ga_comparison/comparison.csv).
- [Expanded GA design](C:/Users/Lenovo/Downloads/MOSAIC_project/docs/Expanded_GA_design.md).
- Implementation: [full-route evaluator](C:/Users/Lenovo/Downloads/MOSAIC_project/astra/optimization/full_route_cases.py), [hybrid GA](C:/Users/Lenovo/Downloads/MOSAIC_project/astra/optimization/hybrid_ga.py), [FCFS](C:/Users/Lenovo/Downloads/MOSAIC_project/astra/optimization/fcfs.py), [sector definitions](C:/Users/Lenovo/Downloads/MOSAIC_project/astra/studies/study_sectors.py).

Source DOCX SHA-256 at review: `5812ad0d19684d0b655f30b8ba2f80d225a05e6dc5f58b3e634d5a5bfb082840`.
