# Hai kịch bản VVTS từ video AirNav

Chỉ giữ **08/10/2026 09:00–11:00 ICT** và **22/02/2026 10:00–12:00 ICT**.
Ca ngày 07/10 đã được loại khỏi bộ ca đang chạy theo yêu cầu của người dùng.

## Chạy trong MOSAIC

Từ thư mục dự án, chạy:

```powershell
.\.venv\Scripts\python.exe main.py --mock --profile tsn_tma
```

Mở `http://127.0.0.1:8050/case-scenarios`, chọn **Nạp vào radar TMA**,
sau đó **Phát**. Mở radar TMA để xem trên màn hình tiếp cận hiện có.
Có tạm dừng, tốc độ 1–60 lần, về đầu và thanh chọn thời điểm. Tải ca khác
hoặc bấm Kết thúc sẽ xóa lưu lượng của ca trước. Không cần BlueSky/video/OCR
để chạy; các dữ liệu nhỏ trong thư mục này đủ cho mô phỏng.

## Nguồn và giới hạn

- Video tháng 2 cung cấp nhãn cho cả chuyến đến và đi.
- Video ngày 08/10 chỉ cung cấp chuyến đi. `VVTS_ARR_OCT82026.mp4` có cùng
  SHA256 với `VVTS_DEP_FEB22_2026.mp4`, và đồng hồ trong video là 22/02.
  23 chuyến đến tháng 10 dùng lại giả định tổng hợp của ca trước; có mã MOSN.
- `evidence/video_observations.json` giữ nhãn gốc, đồng hồ UTC, thời điểm
  trong video, vùng ảnh và các trường đọc được. Mỗi nhãn máy đọc được phải
  xuất hiện ít nhất hai lần. Các mũi tên bị đọc thành chữ số 1 đã được đối
  chiếu và gộp, không tạo chuyến bay trùng. Đây là tập chuyến **nhìn thấy**,
  chưa khẳng định đã thu thập đủ mọi chuyển động sân bay.
- Tọa độ trên radar là đường bay **mô phỏng** theo STAR/SID 25R/25L hiện có,
  không phải dữ liệu ADS-B trích xuất từ video. FPL, thời điểm runway và
  direct-to là giả định. Các cột actual trong flights.csv luôn để trống.
- Thời điểm mục tiêu ước lượng từ lần nhìn thấy và độ cao thấp nhất, sau đó
  xếp lại theo đường bay và giãn cách 10/20 NM. Độ cao/GS trong nhãn được
  giữ làm bằng chứng; không sao chép nhãn chồng lấn hay GS thấp bất thường
  thành quỹ đạo. Áp dụng tốc độ và giới hạn 2.000 ft/min của mô hình hiện có.
- Khung nghiên cứu dài hai giờ; các chuyến còn trong hàng đợi có phần đuôi
  chạy tiếp sau hai giờ. Đây không phải bản phát lại chính xác lịch sử.
- Các chuyến đi đã lên cao khi video bắt đầu có đoạn bay mô phỏng trước
  đầu khung, không được đưa trở lại đường cất cánh. Tổng chuyến nhìn thấy
  không đồng nghĩa tổng lượt cất/hạ cánh trong hai giờ.
- Không chạy GA, tính hiệu quả ATFM hay thêm METAR/thời tiết ở bước này.

`manifest.json` ghi nguồn và giả định cho từng chuyến. `tracks.csv` là dữ
liệu chạy radar; `flights.csv`, `fpl.csv`, `demand.csv` là đầu vào mô phỏng.
`summary.json` chỉ kiểm tra dữ liệu/giãn cách, không phải báo cáo nghiên cứu.
Các bộ dữ liệu cũ ở recorded/synthetic là lưu trữ của lần xây dựng trước.

## Tạo lại dữ liệu

```powershell
.\.venv\Scripts\python.exe scripts/build_video_vvts_cases.py
```

Bộ tạo mặc định đọc bằng chứng đã đóng gói. Dùng `--evidence-dir` để nhập
bản nhãn đã đối chiếu khác, `--output` để tạo bản thử và `--check` để kiểm
tra khả năng tạo lại đúng từng byte. Không cần thư viện xử lý video.
