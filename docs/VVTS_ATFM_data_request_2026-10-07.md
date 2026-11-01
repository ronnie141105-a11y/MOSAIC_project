# VVTS weather and ATFM scenario — data request

We are building a research/training simulation of the heavy-rain disruption at Tan Son Nhat (VVTS) on **7 October 2026**. Please provide the following data, within what you are authorised to share.

**Main analysis window:** 17:00–19:00 Vietnam time (UTC+7), equivalent to **10:00–12:00 UTC**. We will compare 17:00–18:00 with 18:00–19:00.

**Context window:** 16:30–19:30 Vietnam time, equivalent to **09:30–12:30 UTC**, where available. Please include the latest applicable weather forecast and ATFM instruction issued before the window, plus any revisions affecting it. If exporting before the window ends, identify the data cutoff and provide a completion export later.

## Essential exports

### 1. Arrival and departure flight list

Include flights that **actually arrived/departed, were scheduled or expected to arrive/depart, or were cancelled/diverted** during the main window. Include VVTS-bound flights held or diverted before landing, and delayed VVTS departures that had not taken off by 19:00. This avoids excluding the flights most affected by the disruption.

One row per flight, with these fields where available:

- Unique flight identifier, operating date, callsign/flight number, aircraft type, departure and destination ICAO codes, status, and diversion airport.
- Scheduled and estimated arrival/departure times, with clear labels for **gate/block times versus runway landing/takeoff times**.
- Actual off-block, takeoff, landing and in-block times (AOBT, ATOT, ALDT, AIBT), where available; actual runway used.
- Filed EOBT and estimated elapsed time; relevant revisions and their issue timestamps.
- Filed route (FPL Item 15), requested speed/level, and assigned SID/STAR/approach if recorded. Please distinguish filed procedures from actual ATC assignments.

Blank or unavailable values are fine. Please retain flights with missing actual times rather than removing them.

### 2. ATFM measures and capacity timeline

- GDP, ground stop, MINIT/MIT or other restrictions affecting VVTS, including upstream airports regulating VVTS-bound flights.
- Measure/program ID; constrained airport/sector; stated reason; issue, effective-start, end/cancellation times; and revisions.
- Declared arrival/departure capacity and changes during the window, including whether the figures are separate or combined; interval and units.
- Affected-flight list: flight ID/callsign, EOBT, assigned CTOT, ATFM delay, exemption/cancellation status, and actual takeoff time if recorded.
- **CTOT revision history**, if available, rather than only the latest value. Include the definition used for the delay field and compliance window.
- The relevant ATFM Daily Plan or operational restriction bulletin, if shareable.

### 3. Weather reports

- Raw VVTS METAR and SPECI reports covering the context window.
- The TAF applicable at the start of the window, with amendments/replacements affecting the window.
- Report observation, issue and receipt times where available.
- Any recorded weather-related runway/approach restrictions or operational suspension/reopening times. Please distinguish a weather report from an operational decision.

## Optional, especially useful for realism

### 4. Holding, deviations and diversions

For affected VVTS-bound flights: holding start/end times, fix or approximate area, altitude/flight level, reason, release time and diversion decision/destination, if recorded. Timestamped tracks at approximately **30–60-second intervals** would help: flight ID, UTC time, latitude, longitude, altitude with reference/unit, groundspeed and track angle. Include relevant holding outside the immediate TMA; the geographic extent should follow the affected flights.

### 5. A-CDM milestones and weather geometry

- For VVTS departures: TOBT, TSAT, TTOT and revision timestamps, linked to flight IDs and actual milestones; turnaround/readiness delays and reason codes, if available.
- Timestamped weather-radar imagery or storm-cell locations affecting arrival/departure routes, and winds aloft, if available from an authorised source.
- Runway configuration changes, outages/closures, and recovery times relevant to the event.

## Format and minimum useful delivery

**CSV or XLSX is sufficient**, with separate files/sheets for flights, measures/capacity, CTOT history and optional milestones/holding. Raw weather reports can be TXT. Please include a short field dictionary, timezone, units, export cutoff, source and any coverage gaps. Use UTC ISO timestamps where possible; clearly label any local timestamps. Keep scheduled, estimated, target and actual times separate.

The minimum useful package is **the flight list + restriction/CTOT records + METAR/SPECI/TAF**. Please prioritise those before optional tracks or A-CDM details. Database credentials, passenger/crew information and unrelated records are not needed.

These exports will let us build a scenario separating observed traffic/weather from assumed clearances or capacity, and compare the effects of holding, upstream departure regulation and recovery.
