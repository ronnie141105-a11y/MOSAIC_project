# Synthetic system tests — updated 21 October 2026

Open **Supervisor** at `/supervisor`. Select a test, click **Load**, then **Play**.
Use speed, pause, the time slider and Restart to inspect the same instant in
Centre, Approach and Tower. The expand button enlarges one view; All views restores three.

| Test | Traffic | Purpose | Minimum arrival transfer gap |
|---|---|---|---|
| T1 · Arrival handoff stream | 4 arrivals, BITIS2H | Centre → Approach → Tower, same-track sequence | 8 min 20 s |
| T2 · Arrivals and departures | 2 arrivals, 2 departures | Both directions and the Tower initial-climb display | 13 min 59 s |
| T3 · Three arrival routes | 6 arrivals via BITIS2H / DALAP2H / VICAL3H, 2 departures | Several feeds, merge sequencing and shared displays | 2 min 49 s |
| T4 · Full cycle · 10 departures + 10 arrivals | 10 A320/A321 departures and 10 A320/A321 arrivals | Stand/taxi/runway/Approach/Centre in both directions | 3 min 29 s |

## T4: complete departure and arrival journeys

Choose **T4 · Full cycle · 10 departures + 10 arrivals**, click **Load**, then
**Play**. The scenario lasts **2 h 11 min 7 s** of simulated time, about **4 min
22 s at 30×**. All test clearances are automatic. Pause, seek, and Restart work
for ground and airborne movements together.

- **TDEP01–TDEP10:** ten separate stands → taxi → hold/clearance → runway
  **25L** → initial climb → SID → Approach/Centre handoff → FIR route exit.
- **TARR01–TARR10:** saved airway feeder starting approximately **130 NM** out
  → descent along the STAR → Approach handoff → final → runway **25R** →
  rollout/exit → taxi → assigned stand, where the aircraft stops.
- Departure SIDs repeat **SAPEN2D, XOBAV2D, ANTRI2D, KADUM2D**. Arrival STARs
  repeat **BITIS2H, DALAP2H, VICAL3H**. Flight types alternate between the
  existing A320 and A321 labels; they use the current nominal performance model.
- Centre flights use a requested **FL300**. Actual altitude follows the existing
  connected route and procedure constraints; terminal climb/descent is limited
  to **2,000 ft/min**. Taxi speed is approximately **22 kt** when moving.

Tower's **Runway chart** hides parked aircraft and stand spurs to keep the
Supervisor chart clear. Choose **Full airport** in the Tower toolbar to watch
the actual departure stands and arrival parking positions.

Useful elapsed-time bookmarks:

| Flight / event | Scenario time |
|---|---|
| TDEP01 leaves its stand | 00:30 |
| TDEP01 takes off | 02:24 |
| TDEP01 enters the airborne Approach model | 03:08 |
| TDEP01 transfers to Centre | 13:31 |
| TARR01 transfers to Approach | 16:23 |
| TARR01 touches down | 47:54 |
| TARR01 reaches its stand | 50:25 |
| Last arrival reaches its stand | 2:10:32 |

The complete native airport and procedure simulator runs at one-second steps
before this fixture is saved. The final shared-ground run is audited, including
timing changes caused by taxi queues and runway occupation. All **190 airborne
flight pairs** pass the requested criteria; all ten arrivals have handoff gaps
of at least 120 seconds. Ground traffic uses the existing taxi-following and
runway-occupation checks. The airborne 10/20 NM rule is not applied to taxiing
aircraft on the airport graph.

T4 also stores `ground_tracks.json.gz`: native positions, routes, and ground
states. It restores them on seek instead of fabricating a new taxi path during
playback. A flight counts as completed only after **FIR exit** for a departure
or **stand arrival** for an arrival. `manifest.json` lists every callsign,
stand, route, slot, handoff, lifecycle event, and separation check.

## Separation checks

The test rules are 10 NM horizontally, 20 NM for heading differences of at most
25 degrees, **or** at least 1,000 ft vertically. The rules apply to the complete
airborne test paths, including the FIR continuation. Every arrival transfer at
the 40 NM boundary is at least 120 seconds after the preceding arrival transfer,
even when they use different gates.

Admission uses a conservative margin: 20.3 NM for any heading or 1,100 ft
vertically. Candidate start times move in ten-second steps until they satisfy
all previously admitted paths and transfer times. A separate audit then checks
the requested 10/20 NM and 1,000 ft criteria on a one-second grid. All four
saved fixtures have **zero violating pairs**. Margins and audit sampling are
recorded in each manifest; this is a functional test, not operational certification.

The 40 NM intersections are named `VVTS_40NM` test transfer points. Their
coordinates, times and associated procedures are saved in `transfer_events`.
They represent the project's study boundary, rather than published ACC/APP agreements.

## How to inspect a handoff

1. In the manifest, find an arrival in `separation_audit.transfer_events`.
2. Move the Supervisor slider just before and after its `time_s`.
3. Outside 40 NM it is owned by Centre. Inside, Approach owns it; Centre keeps a
   gray track while altitude is at least 7,000 ft. Below 7,000 ft it disappears
   from Centre while remaining on Approach.
4. On the last 8 NM, Tower shows the same aircraft identity on its approach extension.

Both radar trails show at most 10 NM of past movement, independent of zoom and
with past samples restored after reload/seek. Supervisor distributes the same
matched radar/airport frame to all three monitors; it does not advance three simulators.

## Rebuild

```powershell
.venv\Scripts\python.exe -B -X utf8 scripts/build_system_tests.py

# Rebuild only the complete 20-flight test:
.venv\Scripts\python.exe -B -X utf8 scripts/build_system_tests.py test_full_cycle
```

Files: `scenarios/synthetic/system_tests/<test_id>/manifest.json` and `tracks.csv`.
Manifests contain flight identities, synthetic procedure metadata, start times,
pair audits, transfer events and the minimum transfer interval.

These fixtures use generated procedure tracks with saved timing. They can be
played and sought; tactical changes during their replay are disabled so the
saved separation audit remains applicable. Live Scenario Builder and airport
presets support interactive flight/taxi controls. T1–T3 departures start at
the runway; T4 includes the complete native ground movements. Real FPL data can be
added later without treating these test identities as observations.
