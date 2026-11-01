# Weather and executable ATFM in the VVTS simulation

Start `python main.py --mock --profile tsn_tma`. Open **Weather & ATFM** from
the operations HMI, Airport monitor or Scenario Builder. All three pages
control the same airport/TMA traffic and simulation clock.

The METAR bar stays visible below the radar header without opening the panel.
Simulated TMA coverage is shaded on the radar with a wind indicator and a
**SIM WX** legend. This is scenario geometry, not weather-radar echoes derived
from a METAR. The weather layer follows pan/zoom and the prediction horizon;
it clears after the configured recovery time.

1. Load **Thunderstorm in TMA** to see three STAR arrivals and two airport
   departures with shared weather effects. Alternatively load
   **Heavy rain: demand exceeds capacity** from Study scenarios. Ten
   departures request release against a study capacity of 24/hour, or six
   capacity equivalents in the next 15 minutes.
2. Inspect the METAR, decoded weather, effective arrival/departure rates and
   unregulated demand. Select a preset or paste a supported VVTS METAR.
3. Choose an action and duration, or click **Use suggested measure**.
   Rates and reasons are filled from the situation; **Adjust rate & reason**
   exposes overrides. **Preview changes**
   displays affected flights, estimated times, targets and delays.
4. **Start measure**, then resume the simulation. Observe stand
   holds, runway release times, measured delay and the procedure log.
5. Cancel the active program or let its duration expire. Weather restrictions
   remain until weather changes or its separate recovery timer expires.

## What changes aircraft behavior

| Measure | Executable effect |
| --- | --- |
| Departure CTOT / stand metering | Assign wheel-off targets; delay off-block for parked flights; constrain runway entry for taxiing flights. Original off-block and CTOT requests are preserved. |
| MINIT | Enforce departure runway-entry intervals, taking the maximum of the selected MINIT, target rate and weather capacity interval. |
| Departure ground stop | Block stand releases and departure runway entry, including flights already cleared for takeoff. Flights already on the runway continue. |
| Arrival metering | Apply reversible speed factors to inbound procedure legs more than 10 NM upstream with altitude targets at least 3,000 ft. At most 20% reduction, never below 180 kt; final approach is unchanged. Prediction reads the same intent. |

Weather affects departure runway throughput, taxi speed and TMA procedure
traffic. A shared weather model changes upstream nominal speed and applies
an along-track wind adjustment, changing aircraft positions, descent timing,
ETAs and trajectory predictions. Filed routes and altitude targets remain.
Weather changes also reach newly created procedure flights. Fair weather
preserves the original no-wind baseline. Weather recovery is respected inside
long prediction steps, as well as by the simulation clock.
An applied program joins new eligible traffic automatically and expires on
simulation time. Only one program is active at a time; applying another
replaces it. A weather or eligibility change invalidates an outstanding
review. Applying recalculates reviewed targets at current simulation time.
Clearances remain separate from flow management.

The **Severe storm: suspension and recovery** study blocks departures for five
simulation minutes, then restores fair weather. Scenario save/load preserves
weather, active programs, assigned slots and the absolute simulation clock.
Reset restores the fair-weather baseline. ATFM Lab's synthetic replay has its
own precomputed schedule; the executable controls are unavailable during it.

## Weather reports and modelling limits

Preset METARs are labelled **SIMULATED**. Pasted observations are labelled
**USER SUPPLIED METAR**; there is no automatic live feed or claim of freshness.
The bounded decoder supports VVTS DDHHMMZ observation times, KT/MPS winds,
metric visibility or CAVOK, weather, cloud/ceiling heights, temperature,
dewpoint and QNH. Unsupported inputs are rejected without changing weather.
METAR field definitions follow the [Aviation Weather Center reference](https://aviationweather.gov/help/data/).

The flow procedure uses review, application, monitoring and cancellation.
The ground-stop override is consistent with the [FAA traffic management
description](https://www.faa.gov/air_traffic/publications/atpubs/foa_html/chap18_section_10.html),
but these local departure controls are study implementations, not an operational
GDP or a representation of published VVTS procedures.

Nominal capacities, reductions and movement speeds are explicit study
assumptions. Reduced capacity is estimated as nominal rate multiplied by the
weather factor. METAR surface wind is used as a uniform TMA study proxy; it
does not describe altitude-dependent wind. Nominal procedure ground speed is
treated as a no-wind speed proxy. Published numeric speed caps remain
conservative GS caps; this is not a certified IAS/TAS conversion or performance
model. Weather coverage is uniform over the simulated TMA, not a localized
convective-cell or turbulence model.
Operation remains fixed to 25L departures and 25R arrivals; runway changes,
convective avoidance, diversions, airborne holding and upstream origin-airport
GDPs are not modelled. Arrival capacity is a planning target, not a guaranteed
admission constraint. Speed metering reports unresolved delay when its envelope
cannot meet a target. CTOT accuracy depends on taxi/roll estimates and queues.

Measured results distinguish accumulated stand holds from taxi/runway holds,
show completed takeoffs and the last 15 minutes' throughput, and show remaining
assigned and residual arrival delays. Remaining-slot KPIs decrease as flights
leave the regulated pool; they are not a counterfactual comparison to a second
unregulated simulation.
