# Two synthetic VVTS airport and sector studies

- `workbook_low_20`: nominal, 11 arrivals + 9 departures.
- `workbook_peak_50`: sector overload, 36 arrivals + 24 departures (60 total; stable legacy ID). The larger airborne cohort uses longer upstream routes.

Load either case directly from **Scenario Builder presets** or **Supervisor's Test scenarios menu**. Both include stand → taxi/HLD/CTOT → takeoff → SID/Centre departures, and upstream → STAR → landing/rollout → taxi → stand arrivals. All arrivals are already airborne at time zero; one departure starts near HLD, while the others wait at stand for their TOBT. At most two departures commit to taxi/HLD/runway at once. Arrivals remain parked at the end.

Capacity counts concurrent airborne aircraft inside each displayed ACC sector's lateral/vertical boundaries, with a separate 40 NM Approach assessment area, separate from named-fix APP ownership. Limits are shared synthetic study assumptions, not operational declared capacities. Nominal remains within every limit; overload intentionally exceeds capacity. Both baselines pass one-second airborne and protected runway safety checks.

The shared runway interlock blocks departure release until a landing aircraft passes two-thirds of the modelled runway and protects imminent touchdown during takeoff roll. W1/AC/LKH/BMT, PTH/BAOMY, BIBAN/BITIS, NIXIV/VICAL, SAPEN, VTV and XOBAV corridors replace the previous SAPEN concentration.

The optional `/case-scenarios` page provides saved three-seed GA results and full native execution replays. Already-airborne arrivals receive eligible Centre speed control; departures receive surface CTOT delay. Saved metrics report remaining sector excess.

The unchanged original workbook is in `evidence/VVTS_scenarios.xlsx`. Each folder contains source rows, provenance, flight plans, airborne tracks, native ground tracks and audit summaries. Rebuild or check with `scripts/build_workbook_vvts_cases.py [--check]`; rerun saved studies with `scripts/run_full_route_studies.py`.

See [study design and validation](../../../docs/VVTS_Workbook_Case_Study.md) for route assumptions, capacity values and model limits.
