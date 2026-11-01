# VVTS airport and sector studies

The original workbook is preserved as evidence. Routes, levels, schedules and initial states are synthetic inputs authorized by the user.

| Case | Arrivals | Departures | Capacity objective |
| --- | ---: | ---: | --- |
| Nominal | 11 | 9 | Stay within every concurrent sector limit |
| Sector overload | 36 | 24 | Intentionally exceed sector limits |

The overload case uses all 29 arrival rows and all 21 departure rows from the original 50-row sheet, plus seven explicitly marked arrival copies and three departure copies. The user selected this larger airborne cohort, with longer upstream routes so aircraft can approach without holding stacks. Its stable ID remains `workbook_peak_50` for saved links. Every flight retains its source row, original callsign, type and wake label. Radar callsigns are A001... and D001....

## Load and initial traffic

Run `.\.venv\Scripts\python.exe main.py --mock --profile tsn_tma`. Load either case from **Scenario Builder → Presets** or **Supervisor → Test scenarios**. Both entry points use the same data and begin paused at time zero. No additional page is required.

Every arrival already exists and is moving, including aircraft upstream of BMT and the other transfer corridors. Several are already descending; the first W1 arrival has reached AC. Aircraft fly to recorded waypoint times instead of spawning at those times. One departure is prepositioned near HLD at startup. The remaining departures stay at their stands until TOBT. TOBT is computed from CTOT, estimated taxi-out/runway time and a small coordination buffer. A stand gate permits at most two committed surface departures, including taxi, HLD and runway lineup. Target and actual off-block times are saved separately.

Supervisor shares the clock between Centre, Approach and Tower. Runway chart mode also shows aircraft at stands, along stand access lanes and after arrival parking. Play, pause, restart and seeking preserve identity and progress. At 1×, 250 kt covers 4.167 NM per real minute; the default 30× runs thirty simulated seconds per real second. Duplicate Supervisor frames do not restart motion interpolation.

Arrivals land, roll out, cross/taxi and remain parked. Departures climb from Tower along their SID into Centre. The complete recovery tail is retained after the three-hour reference window.

## Routes, descent and groundspeed

| Arrival corridor | Named APP transfer |
| --- | --- |
| PLK–BMT–ENRIN–AC | AC |
| PLK–BMT–ONEBI–LKH–VETOM–DALAP | DALAP |
| PTH–MATGI–BAOMY | BAOMY |
| BIBAN–ANHOA–BITIS | BITIS |
| NIXIV–VICAL | VICAL |
| Western SAPEN feeder | SAPEN |
| TULTU–VTV | VTV |

The overload arrival mix keeps W1 as its largest stream, with BIBAN–BITIS, PTH–BAOMY, SAPEN, NIXIV–VICAL and VTV also represented. Departure study levels FL270/290 are kept below inbound cruise strata. Departures use KADUM–BMT, ANTRI–DOVIN–BMT, ANTRI–PTH, LANHI–ELSAS and XOBAV–NIXIV corridors, rather than all using SAPEN.

W1 aircraft maintain assigned FL310–410 on PLK–BMT. After BMT, targets progress to FL240/260/280 at 25% of the feeder, FL140/160/180 near the midpoint, then FL120 and a separated FL100/120/140 transfer clearance. BIBAN may use FL120/140/160. The planner selects the lowest separated candidate. Descent is bounded at 3,500 ft/min; actual crossing times come from native motion.

| Altitude | Groundspeed target |
| --- | ---: |
| FL410 | 490 kt |
| FL300 | 450 kt |
| FL280 | 350 kt |
| FL250 | 325 kt |
| FL200 | 295 kt |
| FL160 | 280 kt |
| FL140 | 270 kt |
| FL100 | 250 kt |

Targets interpolate continuously with altitude. These are groundspeeds, without an IAS/TAS or wind claim. Saved BMT–AC coordinates are 117.35 NM apart: 15.65 minutes at a constant 450 kt. Staged descent takes longer because aircraft slow. These are general study profiles, not type-specific performance models.

Airborne sequencing uses a snapshot of forward-moving inbound streams. Aircraft start at different positions and stages of the same staged-descent routes; upstream distance determines time still to fly. Both cases contain **zero airborne holding circuits**, within the requested maximum of six. Centre arrivals have a hard 10 NM horizontal floor even when vertically separated; the normal 20 NM same-heading rule remains when vertical separation is unavailable. Thus different flight levels cannot justify overlapping radar positions. Initial horizontal distance, complete Centre spacing and the maximum committed surface population are audited at one-second resolution. Upstream extensions and terminal directs remain explicit synthetic assumptions.

APP ownership changes on actual crossing of the named fix, even inside 40 NM. The research capacity assessment separately retains its geographic 40 NM Approach area. Ownership and capacity measurement therefore have explicitly different boundaries.

## Runway and taxi sequence

Arrivals use 25R and departures 25L with the user's shared interlock. Departure roll waits until a landing passes two-thirds of the complete modelled runway. An imminent touchdown blocks release during the proposed takeoff roll. Native occupancy prevents simultaneous entry onto the same runway. Cleared arrival crossings receive priority before a new departure lines up.

Successive wheel-off times are at least **120 seconds apart**. After the preceding departure clears, the next may taxi onto the runway, line up and wait. Longer CTOT waits remain at stands; only the next one or two departures commit to taxi/HLD/runway. CTOTs follow physical taxi order and include native acceleration and runway-node timing. Final CTOTs are rerun and verified against simulated takeoff to one-second resolution.

## Capacity and validation

Capacity is concurrent airborne occupancy within each sector's displayed polygon and altitude slabs, not whole-screen count or movements per hour. Ground traffic and other sectors are excluded. Membership is disjoint, with the 40 NM Approach assessment area taking precedence. Shared synthetic limits are Approach 6, HCM-S1 4 and HCM-S2/S5/S6/S7 3 each. They are not declared operational capacities.

All arrival/arrival, arrival/departure and departure/departure pairs are checked over the complete route and tail. Separation is 10 NM, or 20 NM for headings within 25°, **or** 1,000 ft vertically. Named arrival transfers are at least 120 seconds apart. Published baselines require zero one-second sampled airborne conflict pairs and zero protected runway violations. Nominal additionally requires zero sector excess. Exact peaks and excess aircraft-seconds are in each `summary.json`.

## Genetic algorithm

Planning begins at case time zero. Already-airborne arrivals cannot receive origin-airport GDP. Eligible Centre arrivals can receive 5/10/15% speed reduction; aircraft already handed to APP cannot. Departures can receive 5–60 minutes of extra surface CTOT delay. Each flight receives at most one measure; terminal speed targets remain unchanged. Native GA validation freezes every arrival’s initial position and route: it cannot repair a proposal by moving aircraft farther upstream or adding holding circuits. Speed proposals that fail native spacing are withdrawn and recorded in `native_control_adjustments`.

The objective is delay cost plus 10,000 times sector excess aircraft-minutes and spatial/runway/transfer violation counts. Surface delay costs one assumed unit/minute; extra speed delay and airborne holding cost two. These are not money, fuel or emissions. Existing airborne overload cannot necessarily be removed by delaying departures. An improved objective alone does not establish feasibility.

Search uses a 20-second assessment grid and five-second native speed projections. Selected plans receive one-second checks and full native airport execution before playback is published. Added safety metering is reported separately and included in execution delay/cost. Input hashes and evaluator versions reject incompatible runs. Only native replays with zero airborne/runway safety violations can load. Saved run metrics distinguish projections from execution.

## Evidence and reproduction

Original: `scenarios/synthetic/vvts_workbook_cases/evidence/VVTS_scenarios.xlsx`.

SHA256: `4199bdcb5a15fd8c33eab2959c75c9f51b8ff53fdb78b086864f0fcd89f7489b`.

Each case contains original rows, provenance, flight plans, waypoint times, initial profiles, one-second airborne tracks, compressed ground tracks, milestones and audits. Observed actual takeoff/landing fields remain blank. The values-only workbook reader executes no formulas, links or macros and rejects formula inputs.

~~~powershell
.\.venv\Scripts\python.exe scripts\build_workbook_vvts_cases.py
.\.venv\Scripts\python.exe scripts\build_workbook_vvts_cases.py --check
.\.venv\Scripts\python.exe scripts\run_full_route_studies.py
~~~

The populations differ in type/route mix as well as size, so they are not an isolated causal density experiment. One-second sampled model checks do not establish continuous or operational validity.
