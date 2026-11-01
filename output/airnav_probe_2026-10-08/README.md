**AirNav access and extraction probe — 8 October 2026**

The signed-in account was inspected through the browser. Its subscription page identifies the plan as Business, and VVTS Airport View opens successfully. The API dashboard also exposes an active token under free billing. It initially had 100 credits, with auto-scaling off, and showed 99 credits after the test. The displayed token expiry is 2026-11-08 01:13; the dashboard did not label that expiry's timezone explicitly.

One request to `POST https://api.airnavradar.com/v2/flights/search` returned HTTP 200, `success: true`, one flight, and `cost: 1`. The request is recorded in `api_request.json`. Its UTC window represents 8 October in Vietnam, and the response retains explicit timezone offsets. No recurring polling or paid API subscription was configured.

The tested flight was VN243 / HVN243, registration VN-A399, aircraft type A321, from VVNB to VVTS. The website CSV download and API JSON both contain 698 positions. The API reports departure runway 11R and landing runway 25R. Its actual takeoff is 06:14 ICT and actual landing is 07:59 ICT. Gate arrival is absent, so actual landing must not be substituted for gate arrival.

| Access tested | Data available | Potential use in MOSAIC |
|---|---|---|
| Track CSV download | UTC timestamp, latitude, longitude, heading, altitude in feet, ground speed in knots, vertical speed in ft/min, source, squawk | Replay real traffic, compare predicted and observed trajectories, inspect approach speed and descent profiles |
| Flight-search API, with flight paths | Flight and aircraft identity, airport identity, scheduled/actual times, runways, status, timestamped positions and ground/airborne flags | Build a recorded-data adapter and assemble repeatable scenarios |
| VVTS Airport View | Arrival/departure boards, scheduled/estimated/actual displayed times, aircraft type/registration, live status, weather and runway-use percentages | Capture airport demand and contextual weather/runway conditions |
| Supplied map | Map Options exposes NAVAIDS/Waypoints by region, including Asia/Pacific, and other map overlays | Visually inspect routes and navigation context; bulk geometry export was not verified |

Files in this directory:

- `VN243_2026-10-08_track.csv`: the unchanged downloaded track.
- `VN243_2026-10-08_api.json`: the full flight-search response, with download-link token query values redacted.
- `sample_quality.json`: computed completeness, timing and coverage results.
- `api_request.json`: the exact tested body, without credentials.
- `airport_context.json`: a small transcription of the VVTS screen, with observation time and limitations.

The track spans 06:07:59 to 07:58:48 ICT. Its median timestamp interval is 6 seconds, with a maximum gap of 163 seconds. There are four zero-second intervals after the CSV's timestamps are rounded to seconds. The CSV has 298 blank altitude values, 117 blank ground-speed values, 24 blank vertical-speed values and two blank headings. Of 671 API positions marked airborne, 271 have null altitude. Within a 60 NM circle around the API's VVTS airport coordinates, there are 22 sample positions and none has missing airborne altitude. That circle is a diagnostic filter, not a verified TMA boundary.

For ingestion, preserve missing values and define a maximum age for any carried-forward state. Do not turn missing altitude or speed into zero. Keep source timestamps and a scenario-relative time; the existing `AircraftState.timestamp_s` represents seconds since scenario start. Latitude/longitude and speed/altitude/vertical-rate units already align with MOSAIC's model, while altitude datum and the meaning of track heading still need explicit treatment. This sample has no `icaoRoute` or `waypoints`, despite those properties being defined in the API schema, so it does not establish a source of filed flight plans or SID/STAR assignments.

The current API definition lists live flights, schedules, historical search, geographic search, airport details, METAR, TAF, D-ATIS and NOTAM endpoints. Only the historical flight-search request was executed. VVTS availability of the weather/NOTAM/D-ATIS endpoints was not tested. Continuous live polling costs must be measured for the intended traffic volume; a single one-credit historical result does not establish that cost.

Business website access and API billing are presented separately. Airport View is included in Business; unlimited API usage was not established. The account's subscription summary says four months of flight playback, while the public Airport View page advertises up to 365 days. The effective historical limit was not tested.

Sources: [account subscription](https://www.airnavradar.com/account/subscription), [API dashboard](https://www.airnavradar.com/api/dashboard), [VN243 track log](https://www.airnavradar.com/data/flights/VN243/2975494936/log), [Airport View](https://www.airnavradar.com/airport-view), [API documentation](https://www.airnavradar.com/api/documentation), [OpenAPI definition](https://www.airnavradar.com/api/openapi), [API pricing](https://www.airnavradar.com/api/pricing), [Airport View product description](https://www.airnavradar.com/business/airport-view). Account observations are dated 8 October 2026 and may change.
