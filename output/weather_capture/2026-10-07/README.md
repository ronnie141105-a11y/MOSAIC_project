# VVTS thunderstorm scenario source capture

Captured 7 October 2026, approximately 18:33–18:38 Vietnam time (11:33–11:38 UTC). This is an archived source bundle for scenario construction, not a playable simulator scenario or a complete operational reconstruction.

## Weather observations

Retrieved directly from the [NOAA Aviation Weather Center API](https://aviationweather.gov/data/api/), with the latest report independently matching the [NOAA station text](https://tgftp.nws.noaa.gov/data/observations/metar/stations/VVTS.TXT) and [FlightAware airport page](https://www.flightaware.com/live/airport/VVTS).

| Vietnam time | Observed conditions |
|---|---|
| 16:30 | Thunderstorms nearby; visibility at least 10 km |
| 17:00 | Thunderstorm rain; visibility 7 km |
| 17:30 | Heavy thunderstorm rain; prevailing visibility 4 km, minimum 1 km east |
| 18:00 | Heavy thunderstorm rain; visibility 1 km; wind 050°/16 kt; QNH 1013 hPa |

The 18:00 report gives runway 07R RVR above 2,000 m with no tendency. Clouds are scattered at 1,300 ft, scattered CB at 1,800 ft, and broken at 4,800 ft. Its trend forecasts improvement to 3 km by 18:25; that is not a measured recovery.

The TAF was issued at 12:00 local, valid 13:00 on 7 October through 19:00 on 8 October. Its 16:00–20:00 temporary group forecasts heavy thunderstorm rain, visibility 2 km, and wind 050°/15 kt gusting 26 kt. Forecast gusts are not observed gusts.

Eleven METARs were returned for the six-hour query; no report was classified SPECI. This does not prove that no SPECI was issued elsewhere. Raw reports are in `metar_history.txt` and `taf.txt`; API bodies and receipt timestamps are retained in JSON.

## Traffic and ATFM

Courtesy of [FlightAware](https://www.flightaware.com/live/airport/VVTS): 80 displayed board rows, split across recent arrivals, departures, inbound/scheduled flights, and scheduled departures. These are partial public lists with changing estimates, not 80 aircraft simultaneously airborne.

Six public track logs contain 1,664 samples: HVN133, HVN273, VJC147, MAS766, SIA186, and VJC211. Track timestamps were explicitly labelled EDT and converted to UTC. HVN273 and VJC147 show repeated circuits at approximately FL220 and FL200 east of VVTS, consistent with holding. MAS766 and SIA186 also show repeated turns southwest of the airport. Neither tracks nor circling establish the assigned holding fix, clearance, or delay cause.

VJC211's track ends at low altitude near Cam Ranh, while its detail page still said en route to SGN. Preserve this inconsistency; diversion is a candidate, not a confirmed event.

The [VATM CTOT distributor](https://atfm.vatm.vn/CTOTDistributor), queried as a guest for 7 October, displayed 28 records with VVTS as destination and constraint. Published delays span 52–117 minutes. `vatm_ctot.csv` and `vatm_ctot.json` retain those rows. The table does not label its time zone or show a revision time, GDP start/end, declared capacity, or constraint reason. Its figures conflict with some FlightAware times. Do not infer CTOT compliance or active program status from these rows alone.

## Scenario construction

Use 16:30–18:00 as the observed weather deterioration phase. Replay holding tracks across the wider arrival area, including aircraft outside the simulator's current 40 NM weather footprint. Represent the CTOT list as delays at external departure airports feeding VVTS; they are not VVTS departure slots.

Compare no intervention, arrival metering, upstream GDP, and recovery. Declare airport capacity, TMA storm-cell geometry, winds aloft, holding instructions, and recovery timing as study assumptions. METAR cannot supply these quantities. The existing simulator needs track replay/holding and upstream GDP support for a faithful functional reconstruction.

Full filed ICAO FPLs, assigned SID/STARs, ATC instructions, and live A-CDM TOBT/TSAT/TTOT were not available from these public pages. The [Vietnam AIP ATFM procedure](https://aim.vatm.vn/images/stories/vnaic.vn/SanPhamDichVu/AIPVietNam/AIP/2026-03-19-AIRAC/html/eAIP/VV-ENR-1.9-en-GB.html) describes stakeholder distribution of daily plans and CTOT coordination; the capture does not include that operational briefing.

`scenario_sources.json` combines observed weather, traffic, tracks, published CTOTs, inferred candidates, and missing inputs. Validation checked row counts, track coordinate/course ranges, and chronological UTC timestamps. The manual capture script is `scripts/capture_vvts_public_data.py`; `--cached` reparses the archived responses without fetching again.
