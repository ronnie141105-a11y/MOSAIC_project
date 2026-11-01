# Complete chart catalogue and TMA display update

Source: `reference/tsn_complete/TSN_TMA_CHART`, extracted from the supplied archive. Reviewed table text is retained in `reference/tsn_complete/extracted_tables` for reproducible builds.

## Controls

- Options contains collapsed SID (17 procedures) and STAR (9 procedures) sections. Each checkbox controls only that procedure's route, transitions and named fixes. All start off; individual choices persist. Shared fixes retain their canonical coordinates.
- ILS 25R has one route-and-fixes checkbox, initially off.
- FIR boundaries are fixed off for TMA. The 40 NM outline, 100 NM range, subdued Area/Centre routes, navaids and runway geometry are fixed on and absent from Options. Saved preferences cannot override these fixed layers.
- Coastlines, country borders, Area waypoints and traffic display choices remain available. The ordinary FIR profile retains its existing layer controls and defaults.
- All three restricted/prohibited zones share one subdued color and translucent fill, with one group toggle. VVR19's map label is shortened to VVR19; its provisional geometry status and assumptions remain in the data.

## Procedures and simulation

The catalogue contains 17 SIDs, 9 STARs and 52 charted transitions. New base procedures are ANTRI2E/2F, LANHI2E, TANOS2D/2E, KADUM2F/2G/2K, SAPEN2K, BITIS2J, SAPEN2J and VICAL3J.

Scenario Builder offers a transition selector for the chosen procedure. RINKU joins DOVIN–TS918–TS916–TS914–TS912–RINKU–DALAP to DALAP2H or DALAP2J. STARs continue through SOKAN/BOMSU to the existing ILS W 25R landing profile. Departures remain fixed to 25L.

ANTRI2F and KADUM2F RF legs are sampled at no more than three degrees around the chart's TSC03 centre, preserving published endpoint coordinates. Synthetic samples are used by both flight motion and map geometry but are never presented as named fixes. The one-decimal chart radius is approximate relative to the supplied WGS84 coordinates and the simulator's spherical distance model.

KADUM2G, KADUM2K and SAPEN2K contain altitude-triggered CA legs. Their initial nominal endpoints assume a 5% climb along 249.1 degrees true to 150 m or 900 m. The following turn/CF intercept remains a simplified connection. These positions depend on aircraft performance in reality; they are explicitly identified as simulation assumptions. Transition portions retain the joining altitude until the base profile begins. Automatic holding, direct-to point-merge clearances and performance-dependent turn modelling are not implemented.

TS444 was corrected to 107°03′03.340″E from chart 56092. The earlier workbook-based longitude was 107°03′34.340″E. The corrected value reproduces approximately 305/288 degrees true and 10.9/10.9 km for the adjacent legs, agreeing with chart 56091; the old value produced approximately 308/287 degrees and 10.2/11.8 km.

## VVR19 assumptions

VVP4 and VVR36 retain the team's supplied coordinate definitions. VVR19 uses a provisional local-plane intersection of:

- A 75 km circle centred on TSH as a proxy for the unavailable TSN ARP reference.
- A line 15 km west of local W1 AC–ENRIN, used as the supplied AC–BU alignment proxy.
- A line 15 km north of local R468 TSH–SAPEN, used as the TSH–PNH alignment proxy.
- A line 5 km south of an east/west Biên Hòa runway at approximate chart-symbol latitude 10.976 N, using the user's 270-degree assumption.

These assumptions are also included in the GeoJSON properties. The overlays are map context; they do not automatically reject routes or impose avoidance constraints on traffic.

## Rebuild and verification

Run `.venv\Scripts\python.exe scripts/build_tsn_profile.py` to rebuild the base profile, Centre context and complete chart catalogue. The extension builder is `scripts/extend_tsn_chart_catalogue.py`.

Validation covers all procedure progressions, each layer's owned fixes, all 52 transition joins, RF radius, provisional zone geometry, fixed visibility and legacy toggle compatibility. Browser checks covered the compact menu, isolated ANTRI2F display, muted zones and DALAP2J's RINKU selector. Test logs are in `output/complete_charts_*.log`.

This note supersedes the previous deferral of RINKU and VVR19 in `VVTS_TMA_Team_Revision.md`.

## Radar visual update — 23 September 2026

TMA departures are green and arrivals blue, including future traffic positions; existing alert badges retain their status colors. Observed-position trails are on by default and independently toggleable, persist across reloads, and are clipped to 30 CSS pixels (less than twice the 17-pixel aircraft length). Trails build as positions arrive, reset with simulation time or large position jumps, and are not shown as fabricated history at forecast times.

TSH uses a compact VOR/DME symbol and a 54-pixel-diameter compass rose, with the source chart's 1-degree-west variation. AC uses a dotted NDB symbol and VTV a VOR hexagon. Other navaid symbols retain their previous representation.

Options now has larger checkbox targets, brighter labels, a two-column procedure list, and All SID / All STAR controls with mixed-selection state. The TMA display-mode box is hidden; the FIR selector remains available. Double-clicking the map still resets its extent. The 40 NM outline is amber; area waypoints remain blue-grey.

Validation: 182 pytest tests, 90 dashboard checks and the Node traffic-style tests passed. Browser verification confirmed colors, boundary contrast, compact symbols, the 17-SID and 9-STAR bulk selections, and trail preference persistence.

## Open workspace and quick traffic update — 23 September 2026

The 40 NM outline now uses a thin, translucent muted stroke. The TSH compass rose is teal and 48 CSS pixels in diameter, independent of map zoom; every radar render restores the CSS-pixel canvas transform.

A visible TMA header button, Return to overall, clears hotspot and aircraft focus, returns to current time, and prevents automatic event reselection until the user selects another event. FIR retains its existing display controls.

Scenario Builder includes + Random aircraft, with Mixed / Arrival / Departure choices in TMA. Each click adds one uniquely named flight at a named fix along a randomly selected published procedure, retaining its runway and flight profile. FIR random spawning follows an existing airway. Existing traffic and simulation time are preserved.

Outer panel backgrounds, borders and padding have been removed, and the radar receives more width. These reversible layout overrides are grouped in the Open workspace layout block at the end of dashboard.css.

Validation: 184 pytest tests passed, including TMA/FIR random spawning; the Node overall-reset regression passed. Browser checks confirmed escape from hotspot focus and one-click spawning with empty form fields (five aircraft became six), and inspected the expanded map and subtle boundary.
