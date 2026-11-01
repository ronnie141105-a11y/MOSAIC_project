# Traffic revision handover — 2026-11-01

**STATUS: Requested implementation completed and validated. The user asked to wrap up at 1% usage. Earlier pending lists below are historical; this final checkpoint takes precedence.**

Latest user scope: continue routing/density/runway/completion work AND start with mixed airborne departures in APP/Centre/near next-sector transfer and two arrivals near point merge without an initial direct-to-ILS shortcut. Keep historical TOBT/CTOT and freeze pre-start history/GDP eligibility. User asks for a handover before resources/context get low; no reliable external percentage is exposed.

Implemented and baseline-native validated:
- Phú Quốc PQU → RG → TRN → BITIS, new PQU_BITIS/BITIS2H family; NIXIV/VICAL feeder originates VDPP, not VVPQ.
- Nominal 20 (8 initial arrivals + 6 regional + 6 TSN departures); overload 60 (24 + 18 + 18). Regional/airborne gate demand interleaves; TSN ground readiness every four minutes, source demand every 15 minutes per airport.
- One-hour native warmup generates three nominal / four overload historical airborne departures. First is near route exit (~90 s to completion), second in Centre, remaining in APP. Negative TOBT/CTOT and pre-start tracks retained. No GDP for already-airborne flights.
- Two arrivals start on full point-merge arcs, APP transfer times -900/-600 s, distinct levels, direct-to-ILS not issued at startup.
- P5-only taxi exit and corrected 25L crossing graph retained; crossing guard now 20 s after wheel-off (not roll start).
- Replay starts at planning time zero despite historical tracks. Full-tail empty padding removed. ATFM complete triggers only when every TSN departure has left the modeled sector and CURRENT sector excess is zero. Aircraft completion counts are not fabricated. Continue arrivals resumes the tail. Full-cohort metrics/audits are not cut to that display pause.
- UI/API: historical clock annotations, normalized TSN flight-plan times even for airborne departures, status/remaining-arrival labels, original/regulated times retained. Comparison remains GA → FCFS → Reference only.

Frozen baseline generation completed: tmp/mixed_start_build.log, both promoted. Overload full arrival tail ~14435 s (4 h); operational phase ends earlier. All native airborne/surface/gate conflicts zero, genuine capacity excess remains. Do NOT promise full-tail three-hour completion; the user explicitly chose the departure-sector/no-excess operational completion rule.

Current runs:
- Nominal new study already published: 20261101T091158Z-01b86d13, single seed 11. D=140/E=0 for all methods.
- Overload GA running: tmp/mixed_start_ga_peak.log, exec session 80350; 1770 pair tables finished, native checkpoint/search now running. Uses --cache-evaluator. Trusted cache tmp/evaluator_workbook_peak_50.pkl.gz (~232 MB) avoids repeating preprocessing if export fails; key checks evaluator VERSION and all input hashes. Nominal cache ~53 MB.
- Raw old results stay immutable. Current report/figures must not recycle compact-case or 80-aircraft percentages.

Verification completed:
- tmp/mixed_start_tests.log: 34 passed (airport, operational cases, gates, crossing).
- tmp/startup_phase_final.log: 5 passed (mixed states, PQU, point merge, no fake completion, pause/continue).
- tmp/mixed_optimizer_tests.log initially found an inactive legacy speed-control helper affecting post-gate legs; fixed controlled_spec to stop at the named transfer. Retest tmp/mixed_optimizer_fixed.log pending. Active gate_flow.speed_spec behavior unchanged for the in-progress evaluator.

Still finish:
1. Check overload study completion; repair any export failure using cached evaluator, never publish unsafe variants.
2. Run published full-route replay tests for both cases. Existing mini fixture now chooses a future ground departure; count expectations updated to 60/42/18. Startup test field access verified.
3. Export scripts/export_gate_flow_summary.py once BOTH latest results validate against inputs; include fresh statistics and scope caveats. Consider adding measured operational-end timing separately from full-cohort completion.
4. Restart the local main.py --mock --profile tsn_tma server I previously started (8050) so new startup/phase APIs are loaded; inspect its owning PID before stopping. Browser verification via cua_repl, screenshot fullPage:true (ordinary getScreenshot was unreliable). Verify PQU board, initial airborne stages, PM arcs and ATFM complete/Continue arrivals. Save screenshots under output/gate_flow_revision_20261101/.
5. Final reply should clearly explain that 19.8% overload / 7.8% delay was GDP-only GA on the earlier 80-aircraft inputs; current single GA is coordinated with different cohort/routes/startup states. Never force or carry forward that result.

No Git repository. No subagents authorized. Use .venv/Scripts/python.exe. Do not create goals. User confirmed CN meant Côn Sơn VVCS.

## Checkpoint after completed studies

Both new runs published and inputs verified. Nominal run 20261101T091158Z-01b86d13: all methods D140/E0. Overload run 20261101T092015Z-2cd7a0ae: Reference/FCFS D2077.3/E79.58, GA D2081.3/E75.58, all native safe; one seed 11. Current improvement ~5.0% excess, +0.19% delay; do not claim the old 19.8/7.8 result. Regenerated implementation_results.md contains current three-method table.

Verification: 34 core/surface/gate tests, 5 mixed-start/completion tests, 13 optimizer regressions, 2 published native replay tests passed. Low-level legacy controlled_spec post-transfer speed bug fixed; active flow controller unchanged during study.

Measured operational end from actual replay sector counts: nominal 5538 s with zero arrivals remaining; overload Reference and GA both 8744 s (02:25:44), with 17 arrivals remaining. Full-cohort tail ~240 minutes remains available and all statistics cover that tail. Measurement file tmp/atfm_window_times.json.

Server restarted with fresh Python at 16:28 local time on port8050, exec session47830. Final browser verification and screenshots still to do. Latest UI makes Completed button disabled if no arrival tail exists; Continue arrivals otherwise. Preserve this handover if context/resources get low.

Measured timings and published replays verified; the native published replay tests passed 2/2 (tmp/mixed_published_tests.log). The local server is running with the new implementation on port 8050, session47830. Final UI check is loading the 60-aircraft GA in Supervisor (IAB tab13); remaining step is screenshot verification and final delivery.

## Final checkpoint — user requested wrap-up

All requested routing, 60-aircraft density, mixed startup, retained historical TOBT/CTOT, 20-second-after-wheel-off crossing and departure-sector/no-excess completion features are implemented. Published native replay tests passed for both current cases. GUI verified in Supervisor: 28 airborne + 14 TSN surface + 18 regional origin flights = 60 planned at 00:00. Initial snapshots show two arrivals on point-merge arcs, two departures in APP, one in Centre and one close to onward route exit. D001's historical TOBT/CTOT are displayed with pre-start minute annotations; airborne departures are GDP-ineligible.

GUI also verified ATFM complete at 02:25:45 (timeline has a five-second step; exact measured condition is 8744 s / 02:25:44), all displayed sectors within capacity, Continue arrivals available. There are 17 unfinished arrivals, including flights still at origins; completion means the requested operational phase, not that every aircraft has landed or all future demand vanished. Full-cohort statistics and final safety audits still include that tail.

Saved screenshots: output/gate_flow_revision_20261101/mixed_start_supervisor.png, atfm_complete.png. Supervisor IAB tab13, Centre tab14. Requested reset back to time zero and marked both as deliverables. Server running port8050, exec session47830; started by this task.

Results: nominal current run 20261101T091158Z-01b86d13; overload 20261101T092015Z-2cd7a0ae. Three-method report output/gate_flow_revision_20261101/implementation_results.md is current. Overload Reference/FCFS D2077.3/E79.58; coordinated GA D2081.3/E75.58 (single seed: ~5.0% less excess, ~0.19% more delay). Do not recycle the 19.8%/7.8% pair: that was GDP-only GA on an earlier 80-aircraft scenario.

Verification passed: 34 core case/surface/gate tests, 5 startup/operational-stop tests, 13 optimizer regression tests, 2 full published replay tests. Relevant logs tmp/mixed_start_tests.log, startup_phase_final.log, mixed_optimizer_fixed.log, mixed_published_tests.log. Prediction-table caches are local trusted tmp files (~53MB nominal, ~232MB overload), validated by input hashes and evaluator VERSION; bump VERSION if prediction semantics change.

Research caveats for later discussion, not unfinished scope: one seed only; FCFS proposals can fall back to Reference under execution repair; source GDP genes currently add delay over the constructed reference rather than freely advancing original requested releases; global handoff and same-heading constraints remain conservative study assumptions. Further optimizer/benchmark improvements require a separate task. No thesis Word files were rewritten here.
