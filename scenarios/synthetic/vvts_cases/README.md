# VVTS TMA synthetic case-study scenarios

These three two-hour scenarios are deterministic **reconstructions for simulation**.
They are not verified flight plans, airport movement logs, AirNav playback exports,
or ATC clearances. They are stored separately from `scenarios/recorded/vvts_cases`.

| Case | Local window (ICT) | Planned movements | Combined slot reference |
| --- | --- | ---: | ---: |
| Bad weather | 7 Oct 2026, 17:00–19:00 | 70 | 48, assumed storm reduction |
| Nominal | 8 Oct 2026, 09:00–11:00 | 66 | 88, 44/hour reference |
| Holiday peak | 22 Feb 2026, 10:00–12:00 | 96 | 92, published 46/hour slot parameter |

`manifest.json` lists every flight's origin, type, planned event time, assigned
simulated slot, 25R STAR or 25L SID, direct-to merge fix, and field-level
provenance. `flights.csv` and `fpl.csv` are **scenario inputs** even where a
callsign is grounded in the partial FlightAware airport board. No filed FPL was
obtained. Planned demand is counted in 15-minute bins in `demand.csv`;
`capacity.csv` contains combined runway/ATC movement references. It is not an
arrival-only capacity. Sequencing can spill flights beyond the study window.

`reference_tracks.json` contains six **partial observed FlightAware tracks**
for the bad-weather case. They are evidence references only: one recorded final
approach is eastbound while this simulation uses 25R westbound. The active
`observations.json` is empty and `tracks.csv` contains only synthetic
procedure tracks for all planned flights, including counterfactual 25R tracks
for the six observed identities, sampled every 20 seconds. Their simulated
slots and routes are alternatives, not continuations of the observed tracks. Thus
`astra.studies.vvts_cases.dataset_for_case(folder)` loads a coherent
counterfactual replay without mixing runway configurations. Synthetic tracks
retain the full queue tail after the two-hour demand window. Observed tracks
stop near 18:32 ICT. Their actual VVTS
landing times and runways are unknown; no later position is invented as an
observation. The synthetic arrival tracks use the existing STAR/ILS profile,
sampled with the 2,000 ft/min climb/descent cap and direct-to from a fan fix to
SOKAN or BOMSU. Every generated direct-to passes an altitude-window check at
the merge. Synthetic arrival pairs are sequenced against sampled TMA routes
for 10 NM horizontal and 20 NM similar-heading spacing within the TMA,
regardless of vertical separation. They are geometric study paths, not controller
instructions.

The October 7 METAR includes +TSRA, northeast wind, and an R07R runway visual
range report. Thus 25R synthetic approach geometry in that case is explicitly
counterfactual. October 7 and 8 `weather.csv` copy archived METAR/TAF evidence.
No February 22 METAR is available, so its fair-weather condition is an
assumption in the manifest; its `weather.csv` is header-only.
The bad-weather capacity assumption varies by 15-minute bin as
9, 8, 5, 3, 3, 5, 7, 8 combined movements, with its lowest values around the
observed 18:00 +TSRA report and later recovery. Those numbers are not
published airport capacity.

The `summary.json` separation audit counts aircraft pair-minutes inside the
40 NM TMA at 3,000–16,570 ft under 10 NM horizontal and under 20 NM with
similar heading. It is a diagnostic of these candidate trajectories, not an
ATC safety finding. The candidate baseline has close pairs that must be
resolved in the next traffic-behavior test before claiming realistic traffic
operation. Spacing, wake, runway throughput, weather effect, and actual
point-merge clearances need validation with playback material.

Regenerate deterministically in this project with
`.\.venv\Scripts\python.exe scripts\build_synthetic_vvts_cases.py`.
Add `--check` to compare the saved files to a fresh build and parse each saved case through the replay
adapter. No GA or ATFM measure optimization is run by this script.

Sources for scale and capacity context:

- [CAAV Tết 2026 outlook, about 1,025 VVTS flights planned on 22 Feb](https://caa.gov.vn/hoat-dong-nganh/cang-hkqt-noi-bai-va-tan-son-nhat-san-sang-phuong-an-phuc-vu-hanh-khach-dip-cao-diem-tet-nguyen-dan-2026-20260209144210927.htm)
- [CAAV temporary 46 movements/hour slot parameter for 2 Feb–3 Mar 2026](https://caa.gov.vn/hoat-dong-nganh/dieu-chinh-tham-so-dieu-phoi-slot-tai-cang-hang-khong-quoc-te-tan-son-nhat-20251023163405728.htm)
- [CAAV August 2026 traffic scale, about 740 flights/day](https://caa.gov.vn/hoat-dong-nganh/cang-hkqt-noi-bai-tan-son-nhat-trien-khai-dong-bo-cac-phuong-an-khai-thac-san-sang-phuc-vu-le-quoc-khanh-02-9-20260828093847766.htm)
- [CAAV April 2026 44/hour ordinary reference raised to 46/hour temporarily](https://caa.gov.vn/hoat-dong-nganh/dieu-chinh-tham-so-dieu-phoi-gio-ha-cat-canh-tai-cang-hang-khong-quoc-te-tan-son-nhat-dip-nghi-le-30-4-1-5-2026-20260414082347431.htm)
- [VATM storm response context reported by Báo Xây Dựng](https://baoxaydung.vn/mua-dong-phuc-tap-tai-tan-son-nhat-quan-ly-bay-tang-cuong-ung-truc-192261009182310606.htm)

The scale references do not establish the true traffic count in any of these
two-hour windows. The partial October 7 FlightAware board and six track
sources are documented under `scenarios/recorded/vvts_cases/bad_weather`.
