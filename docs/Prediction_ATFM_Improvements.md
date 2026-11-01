# Trajectory, forecasting, hotspot and ATFM improvements

## Prediction and detection

TMA profiles now retain their requested horizons and add a 15-second grid through the configured lookahead. This also applies when route intent is unavailable. DBSCAN and complexity assessment consume these intermediate snapshots, so short encounters can create provisional tracks before a full-minute sample would see them.

Procedure prediction advances each aircraft incrementally between horizons, carrying its remaining legs and vertical targets. Completed procedures disappear from subsequent snapshots. This avoids repeatedly replaying the whole route from its origin. The baseline and FIR horizon defaults are retained.

## Hotspot polygons

The live pipeline now samples one shared trajectory timeline for the active track members. Route following, procedure vertical profiles, landing profiles and no-route fallback all use the same trajectory engine. The existing `hotspot_boxes` API name is retained, but its polygon is a convex envelope of the aircraft positions during an interaction, with a small configurable display margin, rather than a fixed rectangle.

The envelope covers the earliest continuous near-separation episode, ending when the aircraft recover separation or leave the assessment volume. A later, disconnected episode is not joined across the clear interval. Near-separation thresholds are capped at 1.5 times the configured conflict thresholds and by the configured hotspot buffers. Three-or-more-aircraft crossing or vertically diverse flows also contribute workload geometry within the clustering thresholds. Vertically separated traffic is excluded. The polygon is built from predicted paths, independently of whether a forecast peak beats a historical maximum.

Timing accuracy is limited by `hotspot_conflict_sample_step_s` (5 seconds in the VVTS profile). The convex envelope can enclose some clear space around bent paths; it is an area-of-interest overlay, not a protected airspace boundary. Separate simultaneous patches belonging to one track still share one envelope. FIR detection remains on its configured horizon grid, although its displayed geometry uses the shared sampling model.

## Forecast behavior

Evaluated horizons where the associated cluster is absent contribute zero complexity, allowing dissipation to be estimated. Missing horizon keys remain unknown. A provisional track starts at the current cycle time with no observed hotspot, rather than treating its future anchor as already critical. Short-lived hotspots can use a matched point plus evaluated disappearance as evidence.

Future peak time and score are recomputed each cycle, separately from historical `peak_complexity` and `peak_time_s`. `predicted_peak_complexity` is exposed in telemetry and used for the dashboard display. Forecast confidence is an evidence/lead-time heuristic, not a calibrated probability; recomputing the same forecast no longer repeatedly multiplies down the previous confidence.

## TMA ATFM measures

TMA resolution now produces planning proposals under `atfm_measures`, displayed in the candidate panel:

- Arrival metering: target time and delay at a common procedure fix.
- Departure release coordination: target timing to coordinate upstream releases. Existing airborne departures are explicitly not given ground holds.
- Flow-rate target: converts configured time spacing to flights per hour at the selected bottleneck.

The FIFO schedule includes all snapshot traffic with known intent passing the shared fix, including aircraft outside the hotspot membership. Delays exceeding the configured maximum are marked `CAPACITY_REVIEW_REQUIRED`; they are not silently clipped into infeasible slots. The earliest shared fix is selected per track to avoid issuing competing independent slot times along the same route. No shared route intent means manual review, not a fabricated slot.

TMA proposals replace the blanket procedure-resolution bypass and the ACC-style tactical speed/heading/flight-level menu. FIR tactical candidates retain their existing behavior. These proposals are advisory coordination plans: they do not change the simulator, certify a conflict-free trajectory, model wake/runway capacity, or claim a validated complexity reduction. Airborne tactical conflict handling still requires local control. Holding patterns, direct-to shortcuts and altitude jumps are not generated as TMA ATFM actions.

## Configuration and validation

New validated positive finite settings: `terminal_prediction_step_s=15`, `atfm_spacing_s=90`, `atfm_max_delay_s=600`, and `hotspot_polygon_padding_nm=0.25`. These are study parameters, not operational separation or capacity rules.

Regression coverage includes short crossings missed at full-minute endpoints, incremental multi-leg turn/descent equivalence, encounter/recovery polygon limits, vertical exclusion, external-traffic slot occupancy, delay-limit flags, departure coordination semantics, provisional timing, peak revisions, repeat-call confidence stability and telemetry integration. Existing trajectory, hotspot, resolution, tracking and reset scripts are also checked.
