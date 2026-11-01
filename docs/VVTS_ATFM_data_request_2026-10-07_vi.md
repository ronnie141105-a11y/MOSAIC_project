# Xin phép trích xuất dữ liệu VVTS

Xin phép trích xuất cùng bộ dữ liệu cho ba khung thời gian sau (giờ Việt Nam, UTC+7):

- **Bad weather:** ngày **07/10/2026, 17:00–19:00 (10:00–12:00 UTC)**.
- **Baseline:** **17:00–19:00** một ngày thường gần 07/10/2026, weather tốt, runway configuration tương tự; nhờ ATFM chọn ngày phù hợp.
- **Holiday peak:** **3–4 giờ cao điểm dịp Tết 2026**, ưu tiên ngày **22/02/2026**, weather tốt và planned demand vượt available capacity; nhờ ATFM chọn ngày/khung giờ phù hợp.

Dữ liệu cần trích xuất cho mỗi trường hợp:

1. **Arrival/departure:** callsign, aircraft type, ADEP/ADES, status; scheduled/estimated/actual times, EOBT, EET, runway, filed route và assigned SID/STAR, FPL, flight route. Bao gồm delayed, cancelled, holding và diverted flights.
2. **ATFM:** ADP/restrictions, capacity changes, thời gian áp dụng; affected flights, CTOT, ATFM delay và revision history, bao gồm cả GDP, ground stop, MINIT/MIT. Bao gồm upstream measures đối với flights đến VVTS. Kèm planned demand và declared capacity theo interval 15/60 phút.
3. **Weather:** raw METAR/SPECI và TAF áp dụng trong khung giờ, kèm amendments.
4. **Nếu có:** holding fix/level, entry/release times, diversion details, radar tracks có timestamp; A-CDM TOBT/TSAT/TTOT và revisions; runway closure/reopening, weather radar.

**Định dạng:** CSV/XLSX; weather dạng TXT. Ghi rõ ngày/khung giờ, timezone và data cutoff của từng trường hợp.

Xin cảm ơn!
