# GA trên hai ca video VVTS — 13/10/2026

## Chạy và xem kết quả

Từ thư mục MOSAIC:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/run_video_case_ga.py
.\.venv\Scripts\python.exe -X utf8 scripts/verify_video_case_ga.py
```

Mặc định chạy 10 seed cho mỗi ca, quần thể 80, tối đa 160 thế hệ và
6.000 đánh giá mỗi phương pháp, gồm chuẩn bị nghiệm chung.
Kết quả ở `output/video_case_ga/2026-10-13`: báo cáo tiếng Việt,
`results.json`, bảng CSV, lịch sử hội tụ và gene từng chuyến.

## Xem phương án trên radar

```powershell
.\.venv\Scripts\python.exe main.py --mock --profile tsn_tma
```

Mở `/case-scenarios`, chọn phương án rồi bấm **Nạp vào radar TMA**:

- **Bản dựng giãn cách FCFS**: bộ ca tái dựng ban đầu.
- **Đối chứng không điều tiết**: đường bay neo vào thời điểm mục tiêu.
- **GA chỉ Ground Delay**: tối ưu các mức GDP 5/10/15/20 phút.
- **GA phối hợp**: mỗi chuyến chọn GDP hoặc giảm tốc upstream 5/10/15%.

Các phương án GA tốt nhất được xuất vào `variants` của từng ca. Nhấn Phát,
chọn thời điểm hoặc mở radar để xem đường bay và biện pháp trong bảng tàu bay.
Chuyến đi giữ lịch cố định; GA chỉ quyết định biện pháp cho chuyến đến.
Giảm tốc upstream được biểu diễn bằng dịch thời điểm đoạn bay terminal,
không mô phỏng thêm đường bay upstream. Không cần kết nối BlueSky.

## Diễn giải đúng kết quả

- Ca 08/10 có 23 chuyến đến tổng hợp và 32 chuyến đi đọc nhãn video.
- Ca 22/02 có 37 chuyến đến và 43 chuyến đi đọc nhãn video. Quỹ đạo,
  thời điểm runway và phần FPL vẫn là giả định mô phỏng ở cả hai ca.
- Năng lực 42 tổng lượt đến và đi mỗi giờ, thời điểm quyết định trước
  khung 60 phút, thời gian từ nơi đi đến mục tiêu 95 phút và 20 phút
  upstream là giả định thực nghiệm, chưa xác nhận với giảng viên.
- Số cặp vi phạm là số cặp tàu bay có ít nhất một mẫu vi phạm; không phải
  số phút hoặc số sự kiện. Kết quả chính dùng bước 20 giây.
- Hậu kiểm bước 5 giây áp dụng cùng gene của phương án tốt nhất;
  không phải trung bình 10 seed và chưa thay kiểm tra liên tục.
- Cả hai ca có 0/10 phương án khả thi ở cả hai phương pháp GA.
  Kết quả chỉ chứng minh giảm vi phạm trong mô hình. Chi phí quy đổi
  tăng ở cả hai ca; tổng phút điều tiết tăng ở ca 22/02.

Không tự giãn cách lại quỹ đạo sau GA để làm biến mất vi phạm.
Miền biện pháp hiện tại có các cặp vi phạm với mọi tổ hợp gene hợp lệ;
cần xem lại giả định quyết định và miền biện pháp trước khi kết luận hiệu quả.
