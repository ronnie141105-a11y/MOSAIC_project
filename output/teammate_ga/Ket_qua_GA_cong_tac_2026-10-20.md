# Kết quả tích hợp GA cộng tác — 20/10/2026

Mã gốc do thành viên nhóm đóng góp. Bản tích hợp giữ mã hóa (biện pháp, mức độ), 
tournament, lai ghép một điểm, đột biến phân loại và elitism; sửa lỗi và dùng bộ kiểm tra MOSAIC.

## Cách chạy và đọc bảng

- Mỗi ca: 10 seed, 80 cá thể, tối đa 150 thế hệ, 6.000 đánh giá duy nhất/phương pháp/seed, gồm chuẩn bị nghiệm.
- Hai GA dùng cùng dữ liệu, chi phí, miền hành động, nghiệm GDP khởi đầu và ngân sách. GA cộng tác dừng sau 30 thế hệ không cải thiện; GA trước đây sau 40.
- Greedy: hai lượt tối ưu lần lượt từng chuyến, không chọn lọc/lai ghép/đột biến.
- Bảng chính dùng lưới thời gian 20 giây. Cặp vi phạm được đếm một lần nếu có ít nhất một thời điểm vi phạm; không phải số lần cảnh báo hoặc số tai nạn.
- TB ± SD: trung bình và độ lệch chuẩn mẫu qua các seed; greedy/không điều tiết là một phương án xác định.
- Chi phí C: GDP 1 đơn vị/phút; giảm tốc 2 đơn vị/phút chậm phát sinh. Đây là đơn vị giả định, không phải tiền/nhiên liệu.
- P = số lượt vượt năng lực + số cặp vi phạm + số cặp vi phạm mới. Mục tiêu = C + 1.000P; fitness = 1/(1+mục tiêu).
- Khả thi yêu cầu không có vi phạm năng lực và giãn cách, không chỉ mục tiêu thấp hơn.

| Ca | Phương pháp | Cặp đến–đến vi phạm | Chi phí C | Tổng điều tiết (phút) | Khả thi |
|---|---|---:|---:|---:|---:|
| nominal | NO_CONTROL | 15 | 0.00 | 0.00 | Chưa đạt |
| nominal | GREEDY_GROUND | 9 | 45.00 | 45.00 | Chưa đạt |
| nominal | GREEDY_MIXED | 4 | 57.31 | 48.65 | Chưa đạt |
| nominal | TEAM_GROUND | 5.50 ± 0.71 | 85.00 | 85.00 | 0/10 |
| nominal | TEAM_MIXED | 2.40 ± 0.97 | 78.80 | 64.90 | 0/10 |
| nominal | LEGACY_GROUND | 5.00 ± 0.67 | 98.00 | 98.00 | 0/10 |
| nominal | LEGACY_MIXED | 2.60 ± 0.84 | 72.98 | 60.24 | 0/10 |
| holiday_peak | NO_CONTROL | 61 | 0.00 | 0.00 | Chưa đạt |
| holiday_peak | GREEDY_GROUND | 35 | 150.00 | 150.00 | Chưa đạt |
| holiday_peak | GREEDY_MIXED | 23 | 191.98 | 178.49 | Chưa đạt |
| holiday_peak | TEAM_GROUND | 33.60 ± 0.84 | 148.00 | 148.00 | 0/10 |
| holiday_peak | TEAM_MIXED | 22.90 ± 1.20 | 185.57 | 169.79 | 0/10 |
| holiday_peak | LEGACY_GROUND | 33.50 ± 0.53 | 152.50 | 152.50 | 0/10 |
| holiday_peak | LEGACY_MIXED | 22.40 ± 1.26 | 195.35 | 174.42 | 0/10 |

TEAM = GA cộng tác đã tích hợp. LEGACY = GA trước đây chạy lại theo cùng giao thức so sánh mới.

## Kiểm tra dày 5 giây

Chỉ kiểm tra các phương án chọn trong bảng dưới, không phải trung bình toàn bộ 10 seed. Phương án TEAM được chọn theo mục tiêu trên lưới 20 giây.

| Ca | Phương án | Cặp đến–đến (20 s) | Cặp đến–đến (5 s) | Cặp đến–đi (5 s) | Vượt năng lực (5 s) |
|---|---|---:|---:|---:|---:|
| nominal | NO_CONTROL | 15 | 15 | 0 | 0 |
| nominal | GREEDY_MIXED | 4 | 6 | 0 | 0 |
| nominal | TEAM_GROUND | 5 | 7 | 0 | 0 |
| nominal | TEAM_MIXED | 1 | 2 | 0 | 0 |
| holiday_peak | NO_CONTROL | 61 | 63 | 0 | 0 |
| holiday_peak | GREEDY_MIXED | 23 | 26 | 0 | 0 |
| holiday_peak | TEAM_GROUND | 34 | 34 | 0 | 0 |
| holiday_peak | TEAM_MIXED | 21 | 26 | 0 | 0 |

## Nhận xét

- GA cộng tác đã chạy và nạp được vào radar với đúng danh sách chuyến bay. Phương án phối hợp giảm vi phạm so với không điều tiết trên các đường bay giả định.
- Cặp đến–đến ca thường: greedy 4, TEAM_MIXED trung bình 2.40. Ca Tết: greedy 23, TEAM_MIXED trung bình 22.90.
- So sánh TEAM_MIXED / LEGACY_MIXED: ca thường 2.40 / 2.60 cặp; ca Tết 22.90 / 22.40 cặp. Chưa có bằng chứng bản mới vượt trội toàn diện hoặc khác biệt có ý nghĩa thống kê.
- Lưới 5 giây tìm thêm vi phạm. Ca Tết: TEAM_MIXED được chọn còn 26 cặp; greedy mixed còn 26 cặp. Phải xét phép kiểm tra dày trước khi kết luận lợi thế.
- Có 1 cặp bắt buộc vi phạm ở ca thường và 5 cặp ở ca Tết trong mọi tổ hợp hành động phối hợp hiện tại; các phương án không thể đạt hết ràng buộc trong miền này.
- Năng lực không bị vượt ở các phương án đã chạy. Mã gốc chỉ xét số chuyến đến với giới hạn 42/giờ sẽ không thấy vấn đề ở hai ca chỉ có tổng 23/37 chuyến đến; ràng buộc giãn cách là phần cần bổ sung.
- Tăng số thế hệ không thể loại bỏ các cặp bắt buộc vi phạm trong miền hiện tại. Muốn nghiên cứu phương án khả thi cần thay đổi hợp lý thời điểm quyết định hoặc miền biện pháp, rồi đánh giá lại; chưa tự thay những giả định này.

## Phạm vi và giả định

- Ca thường 08/10: 23 đến giả định + 32 đi. Ca Tết 22/02: 37 đến + 43 đi. Nhãn video được đối chiếu; đường bay, tọa độ, mục tiêu runway và giờ xuất phát là dữ liệu tái dựng.
- GDP 5/10/15/20 phút chỉ cho chuyến chưa cất cánh tại thời điểm lập phương án (trước khung 60 phút, giả định xuất phát trước mục tiêu đến 95 phút). Giảm tốc 5/10/15% trên đoạn upstream giả định 20 phút.
- Giãn cách đến–đến: 10 NM, cùng hướng (chênh hướng ≤25°) 20 NM, không xét giãn cách đứng cho cặp đến. Chẩn đoán đến–đi: 5 NM và 1.000 ft. Miền kiểm tra: 40 NM, 3.000–16.570 ft.
- Năng lực 42 tổng lượt đến/đi trong từng khung 60 phút cố định kể từ đầu ca, gồm phần đuôi trễ; không phải giờ trượt hoặc năng lực công bố đã xác thực.
- Chuyến đi giữ nguyên thời gian/quỹ đạo. Biện pháp upstream được thể hiện bằng dịch giờ terminal. Phần Centre/FIR bổ sung không nằm trong đánh giá GA.
- Đây là nghiên cứu mô phỏng, không phải xác nhận an toàn khai thác hoặc tối ưu nhiên liệu.

## Mở trên hệ thống

Mở `/case-scenarios` → **Chạy GA trên hai ca nghiên cứu** → chọn ca → **Xem kết quả đã lưu**. 
Bấm **Nạp phương án phối hợp mới lên radar** để xem phương án đúng run ID đang hiển thị.

```powershell
.venv\Scripts\python.exe -B -X utf8 scripts/run_teammate_ga.py
```

## Dữ liệu tái lập

- nominal: `20261020T061932Z-fdeec57c`; seed `[11, 22, 33, 44, 55, 66, 77, 88, 99, 110]`.
  Dữ liệu snapshot: `scenarios/reconstructed/vvts_video_cases/nominal/variants/team_ga/20261020T061932Z-fdeec57c/`.
- holiday_peak: `20261020T062110Z-9e46eeaa`; seed `[11, 22, 33, 44, 55, 66, 77, 88, 99, 110]`.
  Dữ liệu snapshot: `scenarios/reconstructed/vvts_video_cases/holiday_peak/variants/team_ga/20261020T062110Z-9e46eeaa/`.

Mỗi snapshot chứa results.json, summary.csv, metrics.csv, convergence.csv, 
TEAM_*_flights.csv, quỹ đạo nạp radar và hash nguồn/thuật toán. Mã gốc và các kết quả cũ được giữ lại.
