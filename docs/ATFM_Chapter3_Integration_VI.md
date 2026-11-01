# Tích hợp bài toán tối ưu Chương 3 vào MOSAIC

Ngày thực nghiệm: 12/10/2026. Nguồn công thức: `docs/sources/bai_toan_toi_uu.md`, bản sao tài liệu người dùng gửi. Kết quả dùng dữ liệu giả lập; chưa phải thực nghiệm trên ba ca lịch sử trong đơn xin dữ liệu.

## Mô hình đã triển khai

Trang `/atfm-formulation`, mở từ menu MOSAIC hoặc ATFM Lab. Bộ tối ưu nằm trong `astra/optimization/formulation.py`; dùng chung MockConnector và cơ chế replay của hệ thống. Chế độ ATFM Lab trước đây vẫn chạy được để đối chiếu.

Mỗi flight có một gene `[m, l]`:

| m | Biện pháp | Các mức l đang thử |
|---|---|---|
| 0 | Không điều tiết | 0 |
| 1 | Ground delay | 5, 10, 15, 20 phút |
| 2 | Giảm ground speed upstream | 5, 10, 15% |

Ground delay chỉ cho chuyến còn ở mặt đất tại thời điểm quyết định. Đoạn giảm tốc phải nằm sau thời điểm quyết định. Có thể thu hẹp miền theo từng flight bằng `max_ground_delay_min`, `max_speed_reduction_pct`; các giá trị hiện tại chưa được xác minh là giới hạn khai thác theo loại tàu bay.

Với đoạn upstream có thời gian danh định T và tỷ lệ giảm tốc r, giữ nguyên chiều dài đoạn:

`speed_delay = T/(1-r) - T = T*r/(1-r)`.

Ví dụ T=20 phút, giảm 10%: speed delay=2.2222 phút, ground speed 300→270 kt. Không đồng nhất giảm 10% với chậm 10 phút. Ground delay và speed adjustment không đồng thời xuất hiện trong một gene.

`f = Σ c(m_i,l_i) + λP`, `Fitness = 1/(1+f)`.

Bảng c chưa có trong tài liệu. Thí nghiệm tạm dùng ground=1 đơn vị/phút, speed=2 đơn vị/phút delay; chi phí không điều tiết=0. JSON cấu hình hỗ trợ `cost_rates` và bảng ghi đè `cost_table` có khóa `m:l`, ví dụ `"2:10": 4.5`. Các chi phí không phải nhiên liệu, tiền hoặc chi phí hãng bay. `cost_table.csv` ghi đủ giá trị và tính sẵn có theo từng flight.

42 chuyến/60 phút được người dùng xác nhận. Kiểm tra theo giờ cố định `[0,60), [60,120), …`; chưa dùng cửa sổ trượt. Đây là tham số nghiên cứu, chưa có chứng cứ xác nhận declared capacity VVTS. Capacity sau hết các khoảng khai báo vẫn được kiểm tra tới khi tất cả flights ra khỏi mô hình.

Tài liệu chưa định nghĩa chi tiết P. Cài đặt hiện tại công khai quy ước:

`P = w_cap*Σ vượt capacity + w_occ*∫ vượt occupancy dt + w_sep*số cặp mất giãn cách + w_new*số cặp xung đột mới`.

Mặc định các trọng số bằng 1, λ=1000. Mỗi cặp chỉ đếm một lần nếu mất giãn cách ở bất kỳ thời điểm nào trong TMA. “Cặp mới” so với các cặp của phương án không điều tiết được dùng làm đại diện cho nguy cơ tạo điểm nóng. Cặp này nhận cả penalty mất giãn cách và penalty tạo xung đột mới. Occupancy dùng đơn vị tàu bay·phút, không phụ thuộc tần suất lấy mẫu. Khi bật penalty power=2, bình phương mức vượt theo từng interval hoặc mức vượt occupancy trước khi tích phân; số cặp vẫn đếm tuyến tính. Khi capacity interval chính đã là 42/60 phút, không phạt trùng cùng một resource theo giờ.

TMA có các đường bay gấp khúc giả định theo ba hướng G_N/G_E/G_W và độ cao giảm 11.000→2.000 ft. Kiểm tra giãn cách liên tục bằng CPA trên mọi cặp đoạn thẳng chồng lấn, đồng thời thỏa điều kiện ngang dưới 5 NM và đứng dưới 1.000 ft. Đây là ngưỡng nghiên cứu theo profile `tsn_tma`; kiểm tra không bao gồm upstream, đường bay thật, gió, IAS/Mach, wake turbulence hoặc điều hành runway. Khoảng thời gian trước entry bị dịch theo biện pháp, nhưng không giả lập xung đột upstream.

Khác với bộ admission/queue trước đây, evaluator mới không tự đẩy entry vào slot hoặc thêm holding. Arrival sau điều tiết được kiểm tra trực tiếp. Vì vậy phương án vẫn quá tải giữ nguyên penalty và được ghi `feasible_in_synthetic_tma=false`.

## GA và thiết kế đối chứng

Population=60, tối đa 150 thế hệ; tournament k=3, one-point crossover 0.8, mutation 0.1 (đổi loại hoặc mức), elitism 10%, dừng sau 40 thế hệ không cải thiện. Mỗi ca dùng seed 11/22/33/44/55/66/77/88/99/110.

Đối chứng: NO_CONTROL; GA_GROUND chỉ dùng ground delay; GA_MIXED được chọn ground hoặc speed cho từng flight. Hai nhánh dùng chung ground incumbent theo cùng seed. Mỗi nhánh có tổng budget 6.000 lượt đánh giá, tính cả greedy seed và tìm incumbent. Mixed không nhận incumbent miễn phí. Mean và sample standard deviation dùng 10 lần chạy; cùng dữ liệu input nên đây là độ biến thiên tìm kiếm, không phải 10 mẫu traffic thực độc lập.

`domain_diagnostics` kiểm tra các điều kiện cần ngoài GA: cặp không thể tránh mất giãn cách dù thử mọi biện pháp cho hai flight; số flights bắt buộc nằm trong một khoảng các bin so với tổng capacity của khoảng đó. Bound dương chứng minh không tồn tại phương án thỏa tất cả trong miền đã cho; bound bằng 0 chưa chứng minh có nghiệm.

Kiểm tra vét cạn 3 bài toán nhỏ × 2 miền biện pháp × 3 seed: 17/18 kết quả GA đạt nghiệm tối ưu trên miền rời rạc; một kết quả ground seed 33 có f=10 so với optimum=5. Điều này được giữ trong `exact_checks.csv`, không che bằng một tuyên bố GA luôn tối ưu toàn cục. Đây là đối chiếu cùng evaluator, không phải kiểm chứng đường bay độc lập.

## Thử nghiệm trên scenario sẵn có

Tất cả biến thể xuất phát từ 54 arrivals của ATFM Lab. Các tên ca giả lập dưới đây không đồng nhất với dữ liệu lịch sử 07/10, 08/10 và 22/02/2026.

| Ca giả lập | Thiết lập | Mean f ground | Mean f mixed | Seed đạt mọi ràng buộc đã kiểm tra |
|---|---|---:|---:|---|
| existing | Capacity 6/6/4/4/6/6/6/6 mỗi 15 phút; trần 42/giờ; occupancy≤8 | 104.597,00 | 100.937,13 | 0/10 cả hai |
| nominal | ETA gốc; capacity 42/giờ; không đặt occupancy cap | 0 | 0 | 10/10 cả hai |
| holiday_peak | ETA nén còn 55%; capacity 42/giờ; không đặt occupancy cap | 5.870,50 | 2.160,11 | 0/10 cả hai |

Ca existing: với các mức biện pháp hiện tại, có 39 flights bắt buộc entry trong `[15,105)` nhưng tổng capacity chỉ 32. Ít nhất 7 chuyến sẽ vượt capacity, độc lập với chất lượng GA. Muốn có nghiệm khả thi phải xem xét lại miền biện pháp hoặc scenario; không tự sửa giả định sau khi thấy kết quả để làm báo cáo đẹp.

Ca nominal: không điều tiết đã thỏa các ràng buộc mô hình, nên f=0 là optimum do chi phí và penalty không âm.

Ca holiday_peak: mixed giảm mean f khoảng 63,20% so với ground, nhưng phương án còn 1 chuyến vượt capacity và 1 cặp mất giãn cách. Các bound hiện tại chưa chứng minh bất khả thi; kết quả chỉ cho biết GA chưa tìm được nghiệm khả thi trong ngân sách đã chạy. Không diễn giải giảm f thành phương án an toàn hoặc hiệu quả thực tế.

Mean total delay của ca holiday_peak: ground 170,50 phút, mixed 147,56 phút. Đây là tổng delay của 54 flights, không phải delay trung bình một chuyến. Ca existing: ground 456,00 phút, mixed 464,36 phút; giảm f không có nghĩa tổng delay giảm.

## Kiểm tra MOSAIC và replay

NO_CONTROL và phương án có f thấp nhất của mỗi nhóm đi qua chính DBSCAN và bộ chấm complexity hiện tại, lấy mẫu 30 giây. Bộ chấm hiện tại dùng trọng số; chưa có fit PCA như văn bản đề xuất. Bảng kết quả lưu peak complexity, số frame hotspot và tập callsign hotspot mới. Định nghĩa hotspot mới là tập thành viên không xuất hiện trong bất kỳ frame hotspot của NO_CONTROL. Đây là chẩn đoán sau tìm kiếm, không phải penalty DBSCAN trực tiếp. `accepted_in_study` còn yêu cầu không có nhóm hotspot mới trên các frame đã kiểm tra; chỉ có cho các phương án được kiểm tra lại.

Các đường replay và đường kiểm tra CPA dùng cùng input hình học. Replay thay traffic phiên mock khi người dùng bấm nạp, rồi đi qua pipeline/dashboard của MOSAIC. Việc replay chạy được không phải kiểm chứng động học độc lập. KPI không bị thay bằng những slot admission tự giãn.

Mục 2.4 và bộ 5 chỉ tiêu chính thức chưa được cung cấp. Bộ báo cáo hiện có cost/f, total delay, vi phạm capacity, mất giãn cách/cặp mới, complexity/hotspot; thêm thời gian tính toán, convergence và độ biến thiên seed. Cần đối chiếu lại bộ chỉ tiêu trước khi viết kết luận học thuật.

## Chạy lại và dữ liệu thực

```powershell
.\.venv\Scripts\python.exe -m scripts.run_atfm_formulation --case all --out output/atfm_formulation --population 60 --generations 150 --max-evaluations 6000
.\.venv\Scripts\python.exe main.py --mock --profile tsn_tma --port 8066
```

Mở `http://127.0.0.1:8066/atfm-formulation`. GUI chạy 10 seed và xuất JSON/KPI CSV. CLI xuất scenario.json, results.json, metrics.csv, summary.csv, bảng chi phí, sensitivity λ=100/1000/10000 trên plans giữ nguyên, convergence, exact checks, biện pháp từng flight và complexity từng frame. Sensitivity chỉ re-score, không re-optimize. Nguồn công thức có hash SHA-256 trong báo cáo CLI.

Có thể sửa một `scenario.json` đã xuất rồi chạy `--scenario <đường_dẫn>`. Input cần flight ID/type, ETA entry tương đối theo phút, departure/readiness để xác định ground eligibility, thời gian upstream, dwell và các resource capacities được định nghĩa cùng khung thời gian. Dữ liệu quan sát track không tự suy ra readiness hoặc planned demand. Module này hiện dùng hình học giả định theo gate; muốn kiểm chứng trên routes thực cần bổ sung geometry/trajectory adapter và kiểm tra upstream.

Ba ca lịch sử và coverage hiện tại nằm trong `scenarios/recorded/vvts_cases` và `output/vvts_three_cases`. Chưa gán FPL, capacity hoặc demand giả lập vào các hồ sơ lịch sử. Khi nhận được dữ liệu thực, ghép FPL với track, xác minh đầy đủ demand/capacity, bảng c và giới hạn kỹ thuật trước khi chạy nghiên cứu thực tế. Tác vụ tích hợp công thức này không truy vấn thêm AirNav và không sử dụng API credits.
