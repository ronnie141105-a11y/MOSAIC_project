# TSN TMA: 40 NM seminar airspace concept

Status: first design proposal for an Air Traffic Management seminar (chuyên đề quản lý hoạt động bay). Layout and research rationale precede software implementation. This document proposes an assessment airspace; it does not establish an operational ATS boundary or a new instrument procedure.

## 1. Seminar question and scope

Suggested Vietnamese title: **Tổ chức luồng không lưu và đánh giá điểm nóng phức tạp trong vùng tiếp cận Tân Sơn Nhất, phạm vi nghiên cứu bán kính 40 NM, cấu hình đường CHC 25L/25R.**

Research question: how do arrival sequencing, departure demand and coordination constraints affect traffic concentration, controller interventions and transit time in a 40 NM TSN study area?

The seminar should present the airspace and traffic organization first. ASTRA then serves as the simulation and measurement tool. Its heuristic complexity score is one indicator, alongside traffic counts, predicted separation events, delay and intervention counts; it is not a validated controller-workload measure.

User-confirmed decisions:

- 40 NM means radius, equivalent to 74.08 km; diameter is 80 NM.
- Develop layout and seminar rationale first, followed by implementation.

Proposed initial scope, based on the supplied plan and charts:

- Runways 25L/25R; SID and STAR traffic.
- Eight RNAV SID and six STAR families as the main layout; conventional SIDs retained for a later comparison scenario.
- Arrivals terminate at the charted STAR handoff fix in this phase. No invented final approach, runway landing time or missed approach.
- Existing HCM FIR scenarios remain available unchanged when implementation begins.

## 2. Boundary and vertical structure

| Element | Proposed definition | Basis / limitation |
|---|---|---|
| Study centre | TSH DVOR/DME, 10°49′06″N, 106°39′02″E (10.8183333, 106.6505556) | Proposed choice from area chart 10430. TSH is distinct from an airport reference point or runway threshold, and is absent from the waypoint workbook. |
| Lateral assessment boundary | Geodesic circle, radius 40 NM around TSH | User's radius; centre remains an explicit design assumption. |
| Historical TMA reference | Area chart 10430, 30 March 2022; annotated 75 km TSH and 600–5050 m | 75 km is about 40.50 NM. The chart depicts a shaped outline, including the western boundary. A full circle is not a faithful digitization of that outline. |
| TMA assessment altitude band | Provisionally 600–5050 m, approximately 1,969–16,568 ft | Reuses the historical chart's label for the study. Retain source units and datum; verify the authoritative vertical definition before operational comparison. |
| Simulation extent | Entire selected procedures, including external feeder legs, holds and initial climb below the assessment floor | Simulation extent is larger than the assessment volume. Report traffic below 600 m separately from TMA occupancy. |
| Inner analysis bands | 0–10 NM, >10–25 NM, >25–40 NM | Proposed measurement bins only. They are neither CTR boundaries nor controller sectors. |
| Published airspace and special-use areas | Separate reference layers, each with edition and vertical limits | Do not give a circular study area authority over another FIR, restricted airspace or a CTR. Operational eligibility requires the actual boundary and airspace-use data. |

The 46 km MSA inset on the procedure charts is not the TMA boundary. Nor should a 25 NM speed reference measured from a runway threshold be evaluated using the 25 NM analysis ring centred on TSH.

Use the 40 NM circle for consistent experiment statistics. For an operationally constrained experiment, use the intersection with verified ATS/FIR boundaries and active airspace restrictions. Until those are digitized, describe results as the circular study case and do not claim full airspace containment or operational feasibility.

## 3. What the waypoint audit changes

The supplied workbook contains **149 waypoint records**, including runway thresholds and sequence fixes. With the proposed TSH centre, 120 points lie within 40 NM using spherical great-circle distance. The accompanying CSV retains every record and its original DMS coordinates. Implement the final boundary test with WGS-84 geodesics; the rounded distances below are for layout decisions.

| Fix | Approximate distance from TSH | Treatment |
|---|---:|---|
| SAPEN | 30.1 NM | Retain as an internal procedure fix, not a 40 NM entry point. |
| ANTRI | 40.2 NM | Preserve just outside the study circle. |
| KADUM / GOMIN | 40.3 NM | Preserve and model boundary crossing on the connecting leg. |
| LANHI | 40.4 NM | Preserve as an external procedure fix. |
| BACHU / ENPAS | 40.5 NM | Preserve as external procedure fixes. |
| XOBAV | 40.7 NM | Preserve just outside the circle. |
| BITIS / MISAN / VICAL | 40.8 NM | Preserve; do not snap to the circle. |
| DALAP | 45.1 NM | Keep feeder and hold outside the assessment volume. |
| ELSAS | 67.0 NM | Keep external feeder path to the southeast arrival stream. |
| NOKUM / SOKAN / BOMSU | 14.7 / 15.3 / 15.7 NM | Internal merge/holding/handoff nodes; roles differ by procedure. |

Create entry/exit events at route–boundary intersections, with calculated crossing time and altitude. A named fix is not automatically a boundary gate. SAPEN-origin scenarios need a declared upstream feed or must report their initial state as an in-area spawn; do not silently count spawning at SAPEN as a 40 NM entry. If a trajectory crosses the circle more than once, preserve every crossing and define whether the metric counts visits or unique flights.

## 4. Recommended lateral organization

Use the supplied published routes as the baseline geometry. The two concept maps show fix-to-fix centrelines using spreadsheet coordinates. They do not show fly-by turns, obstacle clearance or protected route widths.

### Departure network

Westbound initial climb is followed by four route groups:

1. **Northwest:** SAPEN 2D from TS616 to SAPEN.
2. **West/southwest:** BACHU 2D, MISAN 2D and ENPAS 2D share TS616–TS618 before diverging.
3. **South:** XOBAV 2D via TS641, TS642 and TS644.
4. **Northeast/southeast:** KADUM 2D turns via TS636–TS638–TS686; ANTRI 2D and LANHI 2D share the southern initial climb via TS626–TS628–TS632, then diverge.

Retain runway-specific initial segments. For the ANTRI/LANHI chart, 25L reaches TS612 and 25R reaches TS614 before TS626. On the other RNAV chart both runway branches lead to TS616. Similar route families do not imply identical runway initial geometry or climb requirements.

### Arrival network

Use two main sequencing systems:

- **Southern/eastern path to SOKAN:** SAPEN 2H passes TS498–TS496–NOKUM; BITIS 2H joins at NOKUM. They continue through TS492 to LETRO, where VICAL 3H joins. The shared path runs LETRO–VANLI–TS488–RUNSI–TS458–TS456–TS454–SOKAN. ELSAS 2H joins at RUNSI via GOMIN.
- **DALAP alternatives:** DALAP 2H uses VIKEP–TS452–TS438–TS436–TS434–TS432–SOKAN. DALAP 2J uses ANSUP–TS448–TS446–TS444–TS442–BOMSU. The latter chart also contains an ELSAS feeder to ANSUP; the overview emphasizes the DALAP branch and does not claim to draw every transition.

Named holds occur at **NOKUM, BITIS, VICAL and DALAP**, not simply at the final fix of every STAR. Model each hold as an optional state associated with its actual fix. Entering a STAR must not automatically trigger a holding loop.

### Priority monitoring locations

| Location / corridor | Why inspect it | Evidence needed to call it a hotspot |
|---|---|---|
| TS616 and westbound departure fan | Shared departure stem and branching traffic | Departure intervals, climb profiles and temporal occupancy |
| Southwest departure / SAPEN–NOKUM arrival area | Arrival and departure paths occupy a common geographical area | Simultaneous trajectories and altitude separation |
| NOKUM–LETRO | Multiple arrival streams merge | Arrival-rate imbalance, spacing and hold/sequence demand |
| RUNSI and the eastern sequencing path | ELSAS joins the common arrival path | Time-to-merge, speed constraints and downstream acceptance |
| SOKAN / BOMSU | STAR handoff demand | Declared downstream acceptance model; no landing-capacity claim |
| DALAP / northern departure interaction | Branch choice and coordination-sensitive flows | Time and altitude analysis, not line intersection alone |

These are candidate monitoring locations, not pre-certified conflict points. A map crossing at different times or altitudes is not a loss of separation.

## 5. Controller responsibilities and sectorization

Begin with **one integrated TMA simulation and two modeled responsibilities**: arrival sequencing and terminal integration/departure coordination. The area chart lists ARR and TMC services; the detailed task split below is a seminar proposal, not a transcription of their operational delegation.

- Arrival sequencing manages entry demand, holds, merge timing and STAR branch choice.
- Terminal integration/departure coordination manages the initial departure stream and arrival handoff demand near SOKAN/BOMSU.
- Record transfer requests, acceptance and interventions. TWR and ACC remain modeled interfaces in the first experiment.

Do not start with four equal compass quadrants or assign the 10/25 NM circles to controllers. They split continuous route sequences and can put transfers near merges. First measure occupancy and task distribution. Then compare an integrated configuration against a route-based division, placing a transfer on a stable leg upstream of its critical merge. Specify transfer fix, altitude/speed conditions, acceptance time and ownership on each side before implementing a sector boundary.

For the initial seminar maps, the lateral design is the 40 NM study circle plus the published flow network; the monitoring bands support analysis. Exact controller-sector polygons remain a later experimental design decision.

## 6. Vertical profiles, constraints and units

Do not apply one altitude or speed to an entire SID/STAR. Store constraints per fix or leg with value, unit, reference and type: at / at-or-above / at-or-below / window. Store holding restrictions separately. An underlined altitude, overlined altitude, boxed window and explicit “At” label must be decoded from the chart symbology; the plan's prose examples are not authoritative.

Important extraction corrections:

- The RNAV charts state heights/altitudes in metres and distances in kilometres. The conventional SID chart uses NM for DME distance while retaining metres for altitude. Units must be read per chart.
- TS454 “At 2150” appears on the common STAR chart; it is not a verified example from the RNAV SID chart as the handoff text suggests.
- The 83854 climb box scopes the 4.6% requirement to **KADUM 2D**. Do not copy it to every procedure on that sheet without source support. Preserve the separate runway-specific PDG entries.
- Speed restrictions are IAS, while ASTRA currently propagates ground speed. A realistic implementation needs an IAS/TAS/GS treatment. An initial no-wind simplification must state and test its conversion assumptions, not simply rename IAS as ground speed.
- A flight-level limit such as the BITIS holding ceiling FL200 is not interchangeable with a metre altitude on QNH. Preserve the pressure reference. Some procedure constraints extend above the proposed assessment ceiling.
- The generic 190–200 / 160–180 / 150–160 kt arrival notes have stage and threshold-distance conditions. Preserve them, but do not enforce final-approach conditions in a SID/STAR-only phase that does not model those stages.

Proposed prediction horizons for the TMA study: 1, 2, 3, 5, 10 and 15 minutes, with 30 minutes for feeder context if needed. This is a simulation setting to test. Resolve trajectory motion at smaller time steps so a conflict between sampled horizons is not missed. The existing 15 NM DBSCAN radius is a clustering parameter, not an aircraft separation standard; assess sensitivity before reusing it in the smaller TMA.

## 7. Experiment design and seminar rationale

The educational contribution is a defensible explanation of where traffic concentrates, how procedures organize it, and how flow-management choices change the outcome.

| Experiment | Change | Hold constant | Main comparison |
|---|---|---|---|
| Baseline | Published route-following traffic, low declared demand | Fleet mix, runway configuration, constraint model | Normal occupancy and journey time to STAR handoff |
| Arrival pulse | Two or more streams reach NOKUM/LETRO/RUNSI close together | Total arrivals over the full test interval | Merge spacing, delay, hold time, intervention count |
| Mixed demand | Increase departure release rate during an arrival pulse | Arrival schedule and route mix | Shared-area occupancy and predicted separation events |
| DALAP branch study | Use 2H versus 2J under a declared downstream acceptance schedule | Entry times, aircraft performance | Handoff demand at SOKAN/BOMSU and path/time cost |
| Metering response | Adjust departure release or upstream arrival timing | Demand and scenario seed | Reduction in events versus delay cost |
| Coordination sensitivity | Change availability of coordination-required procedures | Demand and declared alternatives | Which scenarios remain feasible; demand that must wait |

All six supplied STARs state a prior-coordination condition. A scenario that excludes every coordination-required route therefore has no complete arrival network from this bundle. Explicitly assume coordination granted for the baseline, or label the resulting restriction experiment accordingly. The software flag records a scenario assumption; it cannot perform real-world coordination.

Measure: unique flights and visits inside the circle, occupancy by altitude band, merge arrival intervals, transit time from boundary entry to handoff where that entry exists, airborne hold time, release delay, path extension, modeled interventions and predicted separation events under a stated criterion. Report complexity-score distributions separately. Use matched scenarios and repeated seeds when random traffic is introduced. Do not infer capacity from one synthetic run or from ASTRA's complexity threshold alone.

The ICAO airspace-concept material supports organizing a design around traffic flows and validating the assumptions through simulation. Use fast-time experiments here as academic evidence; aircraft performance and controller workload would need independent validation before operational conclusions.

## 8. Corrections to the supplied build plan

The plan is reference material. Its imperative language does not authorize unrelated project changes.

1. Separate the user-requested 40 NM study circle from the charted TMA outline; do not call one a digitization of the other.
2. Use TSH as a separately sourced navaid reference, since it is missing from the workbook. Preserve the workbook-only rule for named waypoint coordinates unless the user later approves another source.
3. The conventional chart spells the procedure/fix **DONXO**, whereas the plan uses DONXD. Neither name occurs in the workbook. AC, BAOMY and VTV also need coordinate-source reconciliation before complete conventional-route reconstruction.
4. After implementing one of 12 conventional SIDs, 11 remain; the plan's build-order statement says 10.
5. Holds are attached to their actual fixes, not uniformly to the STAR terminus.
6. Initial climb can be shared by reference but must preserve runway-specific branches.
7. Do not move existing FIR data merely to create profiles. A wrapper manifest can point to the current files.
8. The bundle mixes 2022 area/conventional charts, 2023 STAR supplements and RNAV SID sheets marked AMDT 03/24. They are not verified as a single current effective dataset. Differences between chart labels and workbook positions require an explicit source-resolution log.

## 9. Later implementation sequence

1. Add an isolated `tsn_tma` profile manifest with source editions, centre, study boundary and assessment band; leave current FIR defaults intact.
2. Import all 149 workbook fixes with raw DMS and decimal coordinates. Store TSH separately with chart provenance. Validate missing procedure references and coordinate differences.
3. Define typed procedure legs, runway variants, constraints, feeder transitions and optional holds. Preserve source values and convert only at the engine interface.
4. Implement one departure (SAPEN 2D) and one arrival (SAPEN 2H), including realistic climb/descent progression and the shared route loader.
5. Make the mock simulator, predictor and hypothetical-resolution replay consume the same procedure and performance model. Reject candidate actions that violate retained constraints; do not score an instantaneous altitude jump as a flyable action.
6. Add boundary crossing events and study-only metrics while continuing to simulate external legs. Make the dashboard show the full route context plus the 40 NM circle.
7. Add the remaining RNAV procedures and holds, then reconstruct conventional radial/DME procedures with correct magnetic-to-true handling and source reconciliation.
8. Run baseline and sensitivity experiments, and retain regression checks for HCM FIR. Only then choose controller-sector polygons or claim improvements.

No application engines, existing geographic layers or current scenarios were edited for this design stage.

## 10. Sources and delivered materials

The extracted source bundle remains under `reference/tsn_tma_handoff/`. Charts were visually reviewed because several PDFs contain little usable text and their insets are explicitly not to scale.

- [Supplied build plan](../../reference/tsn_tma_handoff/TSN_TMA_BUILD_PLAN.md).
- [10430: area chart, 30 March 2022](../../reference/tsn_tma_handoff/source_materials/10430.pdf): TSH reference, TMA annotation, surrounding airspace context.
- [10520: conventional SIDs, 30 March 2022](../../reference/tsn_tma_handoff/source_materials/10520.pdf): 12 procedures and text instructions.
- [83847: ANTRI / LANHI RNAV SIDs](../../reference/tsn_tma_handoff/source_materials/83847.pdf) and [83854: other six RNAV SIDs](../../reference/tsn_tma_handoff/source_materials/83854.pdf): route topology, initial-climb branches and chart-specific restrictions.
- [56080: common STARs](../../reference/tsn_tma_handoff/source_materials/56080.pdf), [56084: DALAP 2H](../../reference/tsn_tma_handoff/source_materials/56084.pdf), [56090: DALAP 2J](../../reference/tsn_tma_handoff/source_materials/56090.pdf): dated 28 December 2023.
- [Waypoint workbook](../../reference/tsn_tma_handoff/source_materials/Danh_Sach_Lo_Diem_Waypoints_WGS84.xlsx): `Waypoints (Lộ điểm)`, records on rows 4–152, coordinates in columns D–E.
- [ICAO airspace-concept workshop](https://www.icao.int/MID/Documents/2014/PBN%20Workshop-Tunis/04%20What%20is%20an%20Airspace%20Concept_vJUL13.pdf): general flow-led design context, not local procedure data.
- [ICAO continuous-climb material](https://applications.icao.int/tools/ATMiKIT/story_content/external_files/10260008117raft_en_CCO.pdf): simulation and aircraft-performance validation considerations; methodological context only.
- [2024-10-31 eAIP ENR 2.1 archive](https://aim.vatm.vn/images/stories/vnaic.vn/SanPhamDichVu/AIPVietNam/AIP/2024-10-31-AIRAC/html/eAIP/VV-ENR-2.1-en-GB.html): historical cross-check only, not certification of current 2026 conditions and not used to replace supplied waypoint coordinates.

Deliverables: `TSN_TMA_40NM_Concept_Maps.pdf` (departure and arrival maps), this design brief, and `waypoint_boundary_audit.csv` (149 retained records). The maps are conceptual fix-to-fix plots; exact procedure constraints and published ATS polygons remain implementation inputs to verify.
