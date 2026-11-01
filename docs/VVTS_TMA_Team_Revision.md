# Team revision — 21 September 2026

Implemented from the team's one-page “Ghi chú chỉnh sửa Astra” PDF.

| Request | Result |
|---|---|
| Separate Area and APP fixes | Independent Area waypoints and APP waypoints controls; canonical coordinates retained. |
| SID/STAR fixes follow their route toggles | Each route/fix pair shares a toggle, initially off. Group choices persist across reloads. |
| Empty 40 NM boundary | Outline only; no polygon fill or central label. |
| More distinct colors | Slate UI; subdued Centre routes, blue SID, amber STAR, violet approach fixes, gold navaids. |
| Aircraft visibility and details | Cyan aircraft silhouettes with dark outlines. Hover shows callsign, current FL and speed. Click shows current position, altitude, type, procedure, runway, next fix/phase, approach, heading and vertical speed. |
| Zoom distortion | Fixed local projection aspect, common zoom factor at limits, CSS-pixel mouse coordinates, manual gestures cancel fit animations. |
| Fixed runway operation | SID departures use 25L; STAR/approach arrivals use 25R. Invalid assignments are rejected, including incompatible saved scenarios before reset. Physical runway endpoints remain in map geometry. |
| VVP4 / VVR36 | Toggleable translucent overlays: supplied VVP4 polygon and supplied 15 km VVR36 circle. Display overlays only. |
| VVR19 | Pending verified reference geometry or a decision to accept an explicitly provisional outline. |
| RINKU point merge | Deferred as requested, pending the complete SID/STAR dataset. |

VVR19 needs the reference geometry for AC–BU, TSH–PNH, Biên Hòa RWY 27L/09R and the TSN ARP. The archived [official AIP ENR 5.1](https://aim.vatm.vn/images/stories/vnaic.vn/SanPhamDichVu/AIPVietNam/Related%20Links/2023-01-AMDT/html/eAIP/ENR-5.1-en-GB.html) repeats the offset definition but does not supply those coordinates in the zone entry. No invented polygon has been added.

Validation: 74 pytest tests pass; legacy dashboard 90/90, interface 18/18 and trajectory 95/95 checks pass. Node tests cover 900 zoom steps across three viewport shapes and hover/click/zoom at device pixel ratios 1, 2 and 3. Browser inspection confirmed map rendering, separate/grouped controls, aircraft click details and saved SID toggle restoration. Hover behavior is covered by the event-handler test; it was not directly exercised with browser pointer movement.

Run the study preview with `.venv\Scripts\python.exe main.py --mock --profile tsn_tma --port 8051`.

This update supersedes earlier descriptions allowing arrival handoff on 25L or departures on either runway in the prior implementation notes.
