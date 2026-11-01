# VVTS approach and area radar update — 21 September 2026

## Run and use

```powershell
.\.venv\Scripts\python.exe main.py --mock --profile tsn_tma --port 8051
```

Open http://127.0.0.1:8051/. Port 8051 allows the existing FIR dashboard on
8050 to stay running. Omit `--port` to use the normal 8050 default.

The initial/reset view fits a **100 NM radius** around TSH. The solid inner
circle remains the **40 NM TMA study boundary**, with the existing 600–5,050 m
assessment height. Geographic context and aircraft are displayed outside that
volume; the wider map does not enlarge the assessment volume.

Default layers: area/Centre routes, named area and approach fixes, navaids,
coastlines, country/FIR borders, runway geometry and the two range boundaries.
SID, STAR, full procedure-fix and approach overlays start off and remain
available under Options. Aircraft follow their assigned routes independently
of layer visibility. Selecting an aircraft/event can still display its own
predicted trajectory. The TMA map preference key was versioned so the previous
40 NM camera and enabled SID/STAR layers do not override these new defaults.

Scenario Builder supports both the terminal procedure form and the original
Centre-style airway form. The latter uses connected chains from the merged area
catalogue. For an arrival that lands, use the terminal procedure form with 25R.
The **Centre to TMA to landing** preset demonstrates ANHOA → BITIS on L637,
followed by BITIS2H → SOKAN → ILS W 25R → touchdown.

## Approach implementation

The supplied 123981/123982 PDFs describe **ILS W RWY 25R**, including its RNAV
transitions; they do not supply a 25L approach. Every 25R STAR automatically
continues from its endpoint:

- BOMSU or SOKAN → TS426 → TS424 → TS422 → RW25R → simulated touchdown.
- TS422 is retained as an on-final checkpoint/MAPt, not a turn or a holding fix.
- The tabular +600 m restrictions at TS426/TS424 are minima. Their nominal level
  segment is approximately 610 m, matching the geometric 3° descent to the
  tabular 26 m threshold-crossing altitude using the supplied coordinates.
- Touchdown is a separate, explicitly synthetic point approximately 305 m along
  the runway after the threshold, at the 10 m runway elevation. Aircraft are
  removed at touchdown, not at the IAF or at threshold-crossing height.
- Nominal speed steps are 180/160/140 kt for intermediate/final segments. These
  are simulation assumptions, not chart-mandated speeds or an acceleration model.
- 25L STARs retain their original endpoint handoff. SIDs retain their outbound
  procedure-end handoff. No unsupported 25L approach or arbitrary outbound
  Centre continuation is invented.

The common propagator still drives simulation and prediction. The missed-
approach TS420/TS500 geometry and holding information are retained as source
metadata, but automatic missed approaches, holding execution, flare dynamics,
rollout and runway occupancy are not implemented in this update.

## Catalogue and sources

The canonical catalogue now contains **191 points**. Existing workbook fixes,
including all eight approach/threshold fixes, were reused. The displayed map
has **63 fixes**, **7 navaids** and **73 route legs**; additional procedure fixes
are separately selectable. Only one displayed record per named fix is emitted.

The area-chart coordinates come from 10430.pdf and the supplied screenshot;
surrounding routes/geography reuse ASTRA's existing Centre GeoJSON. Missing local
intermediate fixes were added to route chains, including BAOMY on N500, BACHU
on W17 and MISAN on W12. DONXD is reconciled to the chart's DONXO. Coordinates
were read from printed values, not estimated from chart pixels.

`coordinate_merge_audit.json` records differing incoming coordinates. ESDOB in
the Centre catalogue differs by about 0.74 NM from the supplied area chart; the
area-chart value is retained consistently for its point and connected legs.
Source editions remain mixed, and the supplied 2025 approach documents contain
draft-labelled footers. This is a study dataset, not a current AIRAC claim.

Rebuild all generated profile data with:

```powershell
.\.venv\Scripts\python.exe scripts/build_tsn_profile.py
```

The new source PDFs are preserved under `reference/tsn_tma_handoff/source_materials`.
The builder calls `scripts/build_tsn_context.py` to merge the new context data.

## Verification

- **72 pytest tests passed**, including both approach entries, the 3° final path,
  threshold versus touchdown, predictor/mock agreement, aircraft removal,
  Centre entry, canonical route coordinates, default layers and 100/40 NM radii.
- Relevant legacy suites passed: dashboard **90/90**, interface **18/18**,
  trajectory **95/95**. The previous implementation's complete legacy run is
  documented separately; these are the suites rerun for this update.
- Browser inspection confirmed the expanded map, geographic context, default
  SID/STAR toggles and available procedure controls.

Logs: `output/tsn_tma_tests/approach_*.log`. Two pre-existing test-client dependency
deprecation warnings remain. These checks validate software consistency, not
operational approach suitability or airport capacity.

Restricted/prohibited areas such as VVR19 and VVP4 are intentionally deferred
to the next requested step; their symbols in the source charts were not added.
