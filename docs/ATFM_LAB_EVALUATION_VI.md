# ATFM Lab — tích hợp và đánh giá tạm thời

Ngày chạy: 29/09/2026. Đây là thí nghiệm giả lập trong bối cảnh VVTS, chưa phải đánh giá hiệu quả ATFM tại Tân Sơn Nhất thực tế.

## Phần đã tích hợp

- Menu MOSAIC → ATFM Lab, trang `/atfm` (profile `tsn_tma`, mock mode).
- `/api/atfm/run`: chạy experiment trong background với budget giới hạn; theo dõi qua `/api/atfm/status`.
- `/api/atfm/results`: toàn bộ inputs, plans, KPI, convergence, ETA stress và weight sensitivity.
- `/api/atfm/replay`: nạp phương án vào cùng MockConnector, clock và pipeline của dashboard.
- `/api/atfm/export.csv`: xuất KPI; `output/atfm_lab` lưu dữ liệu từng flight.
- Có ground delay và upstream speed absorption; cả hai đều bị giới hạn theo scenario.
- Replay thay thế traffic hiện tại của phiên mock khi người dùng bấm nút nạp. Scenario reset vô hiệu hóa replay và giữ chuỗi reset hooks cũ.

Mô hình tối ưu vẫn là arrival-entry flow/queue. Adapter phát lại entry/exit events lên hình học minh họa trong MOSAIC. Chưa đưa mô hình động học 4D hoặc hotspot score của MOSAIC vào fitness. Việc hình vẽ chạy được không phải independent validation của kết quả tối ưu.

## Scenario và measures

54 arrivals trong 120 phút, demand từng 15 phút là 5/6/10/10/8/6/5/4. Entry capacity 6/6/4/4/6/6/6/6 flights mỗi 15 phút; occupancy limit 8; dwell 18/20/24 phút. Sau phút 120, capacity tiếp tục 6/15 phút tới khi hoàn thành toàn bộ flights. Đây là entry budget giả định; không phải declared capacity của VVTS, runway throughput hoặc separation minima.

Decision time t=-60. 43 flights còn ở mặt đất: ground delay 0–30 phút. 11 flights đã airborne: ground delay bắt buộc bằng 0. Mọi flight có thể dùng speed absorption 0–4 phút trên đoạn upstream giả định dài 100 NM, baseline 20 phút ở 300 kt ground speed; thêm 4 phút tương ứng 250 kt. Đoạn này hoàn toàn sau decision time. Chưa mô hình hóa wind, IAS/Mach envelope, fuel hoặc upstream-sector capacity. Chưa mô phỏng đường bay thật hay holding pattern.

Speed control được dùng như biện pháp hỗ trợ upstream arrival metering/E-AMAN; không tự động phát ATC clearance. Cơ sở khái niệm: https://www.sesarju.eu/sesar-solutions/extended-arrival-management-aman-horizon

Objective: `J = Σground + 2×Σspeed_absorption + 4×Σholding + 0.2×max_total_delay`.

Trọng số chỉ là giả định weighted delay. `Airborne extra = speed absorption + holding`; phải báo cáo cả hai để tránh coi chuyển holding sang bay chậm là loại bỏ toàn bộ airborne delay.

## Thiết kế so sánh

- BASELINE: không điều tiết trước, vẫn có admission constraints và chờ upstream.
- FCFS_GROUND: chuyển baseline waiting sang ground delay cho flights đủ điều kiện, làm tròn phút và chặn ở 30 phút.
- FCFS_MIXED: thêm speed absorption cho phần waiting còn lại; đây là heuristic nghiên cứu, không phải quy trình khai thác chính thức.
- GA_GROUND: tối ưu ground delay.
- GA_MIXED: tối ưu ground delay và speed absorption.

Mỗi GA chạy seeds 11/22/33/44/55, population 60 và 100 generations. Cùng giới hạn số generations/individuals; số đánh giá unique và thời gian thực có thể khác. Mixed có nhiều biến hơn. Cả hai khởi tạo từ heuristic; kết quả thể hiện cải thiện từ heuristic đó, chưa so với exact optimum. GA ground được chạy lại trong implementation mới, nên số liệu có thể khác demo độc lập cũ.

## Kết quả định lượng

GA là trung bình 5 seeds; thời gian là tổng phút của 54 flights, ngoại trừ maximum delay là phút/flight.

| Phương án | Ground | Speed absorption | Holding | Tổng delay | Maximum delay | Objective |
|---|---:|---:|---:|---:|---:|---:|
| Baseline | 0.00 | 0.00 | 1465.12 | 1465.12 | 46.12 | 5869.70 |
| FCFS ground | 918.00 | 0.00 | 584.62 | 1502.62 | 51.37 | 3266.75 |
| FCFS mixed | 918.00 | 174.00 | 410.62 | 1502.62 | 51.37 | 2918.75 |
| GA ground | 986.00 | 0.00 | 449.62 | 1435.62 | 51.35 | 2794.75 |
| GA mixed | 922.60 | 130.60 | 404.92 | 1458.12 | 51.81 | 2813.84 |

Tất cả phương án phục vụ 54/54 flights; occupancy peak 8. Simulation thực thi capacity/occupancy ở mọi phương án nên đây không phải lợi ích riêng của GA. Queue nằm upstream và được tính vào holding; khả năng chứa queue và fuel feasibility chưa được kiểm tra.

GA ground: objective thấp hơn FCFS ground khoảng 14.45%; holding thấp hơn khoảng 23.09%; tổng delay thấp hơn khoảng 4.46%. Maximum delay cao hơn baseline khoảng 5.23 phút.

GA mixed: objective thấp hơn FCFS mixed khoảng 3.59%. So với GA ground, holding giảm khoảng 9.94%, nhưng tổng delay tăng khoảng 1.57%, objective tăng khoảng 0.68%, airborne extra tăng từ 449.62 lên 535.52 phút. Thêm measure chưa bảo đảm tốt hơn với fitness và budget hiện tại. Đây cũng có thể phản ánh độ khó tìm kiếm tăng lên; chưa phải bằng chứng optimum của mixed kém hơn optimum của ground (ground là một trường hợp con của mixed).

Thời gian experiment trên máy hiện tại khoảng 81.6 giây (bao gồm toàn bộ GA và các đánh giá phụ), không phải cam kết hiệu năng real-time.

## ETA stress và sensitivity

Giữ nguyên tất cả plans; thay ETA độc lập trong ±2 phút, dùng 3 seeds nhiễu. Đây là robustness check nhỏ, không phải validation trên real data hoặc robust optimization.

| Phương án | Objective trung bình sau ETA perturbation |
|---|---:|
| Baseline | 5974.97 |
| FCFS ground | 3639.01 |
| FCFS mixed | 3613.01 |
| GA ground | 3615.16 |
| GA mixed | 3504.48 |

GA ground gần như mất lợi thế so với FCFS ground (còn khoảng 0.66%). Mixed tốt hơn ground khoảng 3.06% trong tập nhiễu nhỏ này. Kết luận: plans nhạy với ETA; cần tối ưu qua nhiều realizations thay vì chỉ perfect forecast.

Re-score các plans cũ khi thay trọng số speed; không re-optimize:

| Speed weight | GA ground | GA mixed |
|---|---:|---:|
| 1 | 2794.75 | 2683.24 |
| 2 (mặc định) | 2794.75 | 2813.84 |
| 4 | 2794.75 | 3075.04 |

Thứ tự xếp hạng thay đổi theo trọng số. Chưa đủ căn cứ để diễn giải các con số thành tiền hoặc fuel savings.

## Kiểm thử

91 tests thuộc ATFM Lab, TMA profile và WebSocket đã qua. Lần đầu 3 tests bị quyền Windows Temp chặn ở fixture setup; đã chạy lại cả 3 với thư mục tạm riêng và qua. Sau sửa static asset paths, chạy lại toàn bộ 11 ATFM tests và qua.

Browser đã xác nhận 13 phương án, 54 dòng flight, tải JS/CSS đúng, replay/pause hoạt động và không có page error. Replay được kiểm tra trên MockConnector tới khi hoàn thành đủ flights, và được đưa qua Pipeline/CycleStore/HTTP serialization. Replay GA_GROUND_22 và GA_MIXED_11 còn được chạy qua HTTP trên server thật tới 54/54 flights; log ở output/atfm_lab/live_replay_acceptance.json. Việc này kiểm tra tích hợp phần mềm, không xác nhận flight trajectories đủ an toàn để khai thác.

## Kết luận tạm thời

**GA có ích trong scenario deterministic hiện tại; bản ground-only là lựa chọn đơn giản hơn và tốt hơn về objective mặc định. Multi-measure đã chạy được nhưng chưa cho lợi thế tổng thể ổn định.** Chưa nên tuyên bố giảm delay/fuel thực tế ở VVTS.

Ưu tiên tiếp theo:

1. Tối ưu kỳ vọng/worst-case trên nhiều ETA/capacity realizations; tách các noise seeds dùng tối ưu và kiểm tra.
2. Thử representation hoặc mutation giữ timing tương đương giữa ground/speed để tìm kiếm hiệu quả hơn; so với heuristic mạnh hơn và exact solution cho case nhỏ.
3. Kiểm tra fairness, ground availability, speed envelopes và upstream congestion.
4. Thay assumption bằng planned demand/readiness và real trajectory; calibrate capacity/dwell với nguồn phù hợp.
5. Nếu đưa separation/hotspot vào mục tiêu, phải gọi mô hình động học thực trong evaluator và xác nhận constraint handling; replay minh họa hiện tại chưa làm bước đó.

## Chạy lại

Tại thư mục `MOSAIC_project`:

```powershell
.\.venv\Scripts\python.exe main.py --mock --profile tsn_tma --port 8052
```

Mở http://127.0.0.1:8052/atfm. Chọn phương án rồi bấm **Thay traffic bằng replay**; radar dùng cùng clock. Có thể Pause tại ATFM Lab hoặc Resume từ radar. Tốc độ replay mặc định 60x.

Chạy batch:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_atfm_experiment
```

Kết quả nằm trong `output/atfm_lab/`.
