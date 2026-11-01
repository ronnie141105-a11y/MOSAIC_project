# Ba kịch bản VVTS theo đơn xin dữ liệu

Đối chiếu bản PDF người dùng gửi ở `D:/VVTS_ATFM_data_request.pdf`, không dùng
các giờ baseline trong bản nháp cũ. Người dùng đã xác nhận khung Tết **10:00–12:00**.

| ID | Khung Việt Nam (UTC+7) | Khung UTC | Điều kiện cần kiểm tra |
|---|---|---|---|
| `bad_weather` | 07/10/2026, 17:00–19:00 | 10:00–12:00 | Quan trắc TSRA/+TSRA; gió phải lấy từ quan trắc, tách TAF |
| `nominal` | 08/10/2026, 09:00–11:00 | 02:00–04:00 | Weather tốt và cấu hình runway phù hợp |
| `holiday_peak` | 22/02/2026, 10:00–12:00 | 03:00–05:00 | Planned demand vượt declared capacity; weather tốt |

Các tên kịch bản là mục tiêu chọn mẫu. Ngày lễ không tự chứng minh quá tải;
throughput đã thực hiện cũng không phải planned demand hay declared capacity.

## Bộ kịch bản tái dựng để mô phỏng

[Bộ dữ liệu tổng hợp riêng](../scenarios/synthetic/vvts_cases/README.md) đã có
manifest, lịch dự kiến, tuyến TMA, track mô phỏng và nhu cầu mỗi 15 phút cho cả
ba khung: 70 chuyến thời tiết xấu, 66 chuyến bình thường, 96 chuyến cao điểm Tết.
Các số này là **giả định nghiên cứu**, không phải số chuyến thực tế của VVTS.
Sáu track ngày 07/10 được giữ riêng làm tham chiếu; track mô phỏng 25R ngày đó
là phương án đối chứng vì quan trắc hướng tiếp cận thực tế khác. Chưa chạy GA
hay đánh giá hiệu quả ATFM trên bộ này. Có thể kiểm tra tính tái lập và đọc
track bằng `./.venv/Scripts/python.exe scripts/build_synthetic_vvts_cases.py --check`.

Phần dưới đây tiếp tục mô tả **bộ quan trắc chưa đầy đủ** tại
`scenarios/recorded/vvts_cases/` và trang `/vvts-cases` hiện hành.

## Phần đã chạy được

MOSAIC có trang **Ba kịch bản VVTS** tại `/vvts-cases`, riêng với demo VN243 và
các bản sao traffic giả định ở `/airnav`. Bộ mới chỉ dùng track đã thu thập;
không tạo traffic thay thế để lấp các ngày thiếu dữ liệu.

Nguồn ngày 07/10: sáu track FlightAware đã lưu (HVN133, HVN273, VJC147, MAS766,
SIA186, VJC211), tổng 1.664 samples, trong đó 1.158 nằm trong khung 17–19h.
Các track kết thúc quanh 18:32; phần còn lại không được kéo dài giả tạo đến 19h.
VJC211 có dấu hiệu tới khu vực Cam Ranh, nhưng trạng thái diversion chưa được xác nhận.

Weather đã bổ sung từ NOAA cho cả hai ngày tháng 10. Raw reports giữ trong CSV;
response gốc và giờ nhận giữ tại `output/vvts_three_cases/weather_archive/`.
METAR observations, TAF forecast và các revision khác nội dung được giữ riêng.
Có đủ các METAR định kỳ trong hai khung không chứng minh rằng toàn bộ SPECI,
TAF amendments và quyết định khai thác đã được thu thập.

28 dòng CTOT ngày 07/10 đã lưu từ bảng VATM công khai vẫn có timezone chưa xác
minh. Chúng nằm trong `ctot_unverified.json`, không được chuyển sang CTOT UTC,
chấm compliance hoặc gán vào capacity timeline.

Ngày 10/10, truy vấn có flight ID VN243 lấy được dữ liệu ngày 22/02/2026 qua
AirNav API: HTTP 200, cost 1 credit, 813 positions. Chuyến đó hạ cánh trước khung
10–12h, nên chỉ chứng minh quyền truy cập lịch sử, không được đưa vào case Tết.
Các query airport-wide đã timeout; không coi response thiếu là airport không có traffic.
API billing và website subscription là hai quyền truy cập khác nhau.

Số dư free API được đọc trước/sau đợt kiểm tra: 99 → 87 credit. Response thành công
report cost 1; các request timeout không cung cấp response body để đối chiếu riêng.
Không coi timeout là request không bị trừ credit. Đã dừng các query rộng, không mua
credit hoặc bật autoscale. Chi tiết lưu tại `access_probe/access_summary.json`.

## Chạy và xem báo cáo

```powershell
.\.venv\Scripts\python.exe scripts/run_vvts_cases.py --init
.\.venv\Scripts\python.exe main.py --mock --profile tsn_tma --port 8064
```

Mở `http://127.0.0.1:8064/vvts-cases`. Có chọn kịch bản, phát/pause track, time
slider, coverage theo 15 phút, prediction errors và download CSV/JSON/Markdown.
Sau khi thêm input, chạy lại runner rồi bấm **Đọc lại báo cáo**.

`--audit-only` bỏ bước complexity pipeline. `--sample-interval-s` chấp nhận
15–300 giây, mặc định 30 giây. TMA assessment giữ profile 40 NM và altitude band
hiện có. Bối cảnh upstream giữ track trong vòng 120 NM để tránh bỏ các đoạn
chờ nằm ngoài TMA. Đây là vùng nghiên cứu, không phải ranh giới khai thác được xác minh.

Outputs: `report.json`, `report.md`, `coverage_15min.csv`, `prediction_errors.csv`
trong `output/vvts_three_cases/`. Chỉ có samples thật và bounded extrapolation;
ngày thiếu track có frames rỗng. Planned demand/capacity/throughput thiếu evidence
được xuất blank/null. Số flights trong tập track mẫu không thay các đại lượng này.

## Nhập dữ liệu khi có file

Mỗi case có thư mục riêng trong `scenarios/recorded/vvts_cases/`, với templates:

- `tracks.csv`: flight identity, timestamp UTC, lat/lon, ft, knots, track angle,
  vertical speed ft/min nếu có, source; không đổi missing thành zero.
- `flights.csv`: danh sách arrivals/departures và status; giờ scheduled, gate,
  takeoff/landing giữ ở các cột khác nhau.
- `fpl.csv`: callsign, aircraft type, ADEP/ADES, EOBT UTC, EET, Item 15, issue time
  và raw FPL. Khi nhận file thực, phải map tên cột/export format trước khi nhập.
- `weather.csv`: METAR/SPECI observation time; TAF issue/validity times và raw text.
- `demand.csv`, `capacity.csv`: start/end UTC, resource, số flights trong interval,
  evidence và source. Capacity giả định dùng `evidence=assumed`; capacity công bố
  dùng `declared`; demand từ FPL dùng `fpl`. Không dùng throughput để tự gán capacity.
- `measures.csv`, `ctot.csv`: measures, thời gian hiệu lực, lý do và revision history.

`coverage.json` lưu các cờ completeness sau khi kiểm tra bộ input; templates để
false. Đổi cờ không tự tạo dữ liệu hoặc xác nhận tính đầy đủ. Resource cho so sánh
phải trùng: `VVTS_ARRIVAL_RUNWAY`, `VVTS_DEPARTURE_RUNWAY` hoặc `VVTS_RUNWAY_TOTAL`.
Runner chỉ so interval 15 phút trùng hẳn; không tự chia một capacity 60 phút thành
15 phút hoặc suy một revision chưa biết. Với airport traffic chưa đầy đủ, throughput
của toàn airport để null; peak tracked subset chỉ mô tả các track đã có.

API response AirNav đã lưu:

```powershell
python scripts/run_vvts_cases.py --import-airnav nominal path/to/response.json
```

Mỗi response được lưu theo content hash, không thay các recording cũ. Sources
cùng callsign và aircraft type được ghép, duplicate timestamps dùng record sau.
Type/identity xung đột phải giải quyết bằng nguồn metadata phù hợp. Không suy SID/STAR
được ATC giao từ route đã bay hoặc từ tên procedure trong FPL.

Track CSV AirNav/FR24:

```powershell
python scripts/run_vvts_cases.py --import-track holiday_peak path/to/track.csv `
  --callsign CALLSIGN --aircraft-type TYPE --adep ADEP --ades VVTS
```

Importer nhận canonical CSV, AirNav CSV có `Date/Time (UTC)`, hoặc FR24 CSV có
`Timestamp, UTC, Callsign, Position, Altitude, Speed, Direction`. FR24 Unix epoch
là mốc UTC; cột UTC nếu có phải khớp. CSV thiếu aircraft identity yêu cầu metadata
từ flight page/FPL; không đoán loại tàu bay. Nếu format khác, map sang template.
VS thiếu có thể tính từ hai altitude quá khứ trong age bound, ghi `derived`.
Không có ground flag đáng tin cậy thì không tự tuyên bố trạng thái airborne/ground.

## Cần xin cô và ATFM những gì

Ưu tiên **FPL của cả ba ngày/khung**, gồm cả flights được lập kế hoạch nhưng chậm,
cancelled hoặc diverted; tốt nhất có issue/revision time và buffer hai phía khung.
Chấp nhận file FPL gốc, CSV hay XLSX; không cần văn phòng xuất thêm ngoài khả năng
hiện tại. Track thực tế sẽ ghép với FPL theo identity/ngày/ADEP/ADES đã xác minh.

Nếu cần nguồn dự phòng: FR24 Gold có lịch sử 365 ngày; Business tới 3 năm theo
support ngày 10/10/2026. Silver 90 ngày không tới 22/02. Nhờ xuất airport history
arrival/departure và track CSV/KML đúng khung giờ; khả năng playback không đồng
nghĩa export bulk/API không giới hạn. Có thể nhận các file export thay cho dùng
tài khoản của cô. AirNav API đã xác nhận truy cập ngày tháng 2, nên chưa cần FR24
để thay cho một giới hạn playback chưa được kiểm chứng trên toàn bộ sản phẩm.

Nguồn chính thức: [FR24 historical playback](https://support.fr24.com/support/solutions/articles/3000115499-is-it-possible-to-see-playback-of-past-flights-),
[airport history](https://support.fr24.com/support/solutions/articles/3000129730-how-can-i-view-airport-flight-history-),
[AirNav API](https://www.airnavradar.com/api/documentation), [NOAA API](https://aviationweather.gov/data/api/).

## Thiết kế thí nghiệm ATFM sau khi đủ input

Giữ cùng population/demand và cùng điều kiện cho các phương án: không điều tiết,
FCFS, ground delay, phối hợp ground delay + upstream speed, và tối ưu GA. Những
capacity/measures không có hồ sơ thật phải là giả định nghiên cứu, chạy sensitivity
riêng, không gán chúng thành biện pháp ATFM đã xảy ra.

KPI gồm ground delay, speed absorption, holding, total delay, maximum/P95 delay,
fairness, coverage và model constraints. Không đồng nhất giảm holding với giảm
toàn bộ airborne delay. Không gọi schedule delay là ATFM delay. FPL EOBT + EET
không tự trở thành actual landing hoặc ETA runway chính xác, vì taxi/readiness và
revisions có thể thiếu.

ATFM Lab hiện có mô hình arrival-entry và GA để tái sử dụng. Bộ ba case này trước
mắt là ingestion/replay/prediction evaluation; **chưa chạy optimization trên ba bộ
demand thực**, chưa xác minh công suất VVTS hoặc lợi ích ATFM thực tế. Khi nhận
FPL/traffic population, cần nối planning inputs vào evaluator và khai báo mọi
assumption trước khi báo cáo kết quả so sánh.
