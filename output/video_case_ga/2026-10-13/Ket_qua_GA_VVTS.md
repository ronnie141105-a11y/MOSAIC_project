# Kết quả GA trên hai ca VVTS, 13/10/2026

10 seed mỗi phương pháp. 80 cá thể, tối đa 160 thế hệ và 6.000 đánh giá, gồm chuẩn bị nghiệm.
GA chỉ xét chuyến đến. Chuyến đi giữ lịch mô phỏng. Đầu vào gồm nhãn video và đường bay giả định.
Năng lực 42 tổng lượt đến/đi mỗi giờ là tham số nghiên cứu của mô hình Chương 3.

| Ca | Phương pháp | Cặp vi phạm TB ± SD | Chi phí biện pháp | Tổng điều tiết (phút) | Khả thi |
|---|---|---:|---:|---:|---:|
| nominal | GA_GROUND | 4.90 ± 0.57 | 100.00 | 100.00 | 0/10 |
| nominal | GA_MIXED | 2.00 ± 0.67 | 104.58 | 97.04 | 0/10 |
| holiday_peak | GA_GROUND | 33.30 ± 0.48 | 145.50 | 145.50 | 0/10 |
| holiday_peak | GA_MIXED | 23.60 ± 0.84 | 177.43 | 161.22 | 0/10 |

## Cách đọc kết quả

- Đối chứng không điều tiết có 15 cặp ở 08/10 và 61 cặp ở 22/02. Đây là đường bay neo vào yêu cầu chưa điều tiết, khác bản FCFS đã giãn cách trên radar.
- GA phối hợp giảm số cặp vi phạm so với GA chỉ GDP khoảng 59,2% ở 08/10 và 29,1% ở 22/02.
- Cả hai ca vẫn 0/10 phương án khả thi. Miền phối hợp có 1 cặp bắt buộc vi phạm ở 08/10 và 5 cặp ở 22/02 với mọi tổ hợp biện pháp hiện tại.
- Chi phí biện pháp tăng ở cả hai ca. Tổng phút điều tiết ca Tết tăng từ 145,5 lên 161,2. Không coi giảm điểm mục tiêu là giảm nhiên liệu hoặc giảm toàn bộ chậm trễ.
- Ground Delay áp dụng ở sân bay xuất phát của chuyến đến VVTS. Chuyến đã cất cánh trước lúc lập phương án không đủ điều kiện GDP.
- Nguồn thời điểm xuất phát là giả định 95 phút trước mục tiêu runway. Quyết định lập trước đầu khung 60 phút.
- Các bảng chỉ kiểm tra giãn cách theo mẫu. Kiểm tra 5 giây áp dụng phương án tốt nhất của từng phương pháp, vẫn không chứng nhận an toàn liên tục.
- Ca 08/10 còn thiếu video đến nên 23 chuyến đến mang mã MOSN vẫn là giả định.

## Tái lập

`python scripts/run_video_case_ga.py`

Chọn phương án ở /case-scenarios rồi nạp lên radar. Bản dựng FCFS giữ riêng và không bị ghi đè.
Các file results.json, summary.csv, metrics.csv, convergence.csv và GA_*_flights.csv giữ số liệu chi tiết.
