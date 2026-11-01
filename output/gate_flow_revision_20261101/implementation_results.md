# Kết quả kiểm chứng tích hợp ATFM mới

Mô hình giữ thứ tự hàng chờ; không Ground Stop, đổi tuyến hoặc slot swapping. Đây là lượt chạy thử 1 seed cho mỗi case, không phải kết luận thống kê cho luận văn.

| Case | Phương pháp | Tổng chậm (tàu bay-phút) | Vượt năng lực (tàu bay-phút) | Vi phạm phân cách / cửa vào |
|---|---|---:|---:|---:|
| 20 tàu bay | GA | 140.00 | 0.00 | 0 / 0 |
| 20 tàu bay | FCFS | 140.00 | 0.00 | 0 / 0 |
| 20 tàu bay | Reference | 140.00 | 0.00 | 0 / 0 |

Case `workbook_low_20`: run `20261101T091158Z-01b86d13`; 1 seed, tối đa 2000 đánh giá nhanh, 20 cá thể, 30 thế hệ.

| Case | Phương pháp | Tổng chậm (tàu bay-phút) | Vượt năng lực (tàu bay-phút) | Vi phạm phân cách / cửa vào |
|---|---|---:|---:|---:|
| 60 tàu bay | GA | 2081.30 | 75.58 | 0 / 0 |
| 60 tàu bay | FCFS | 2077.30 | 79.58 | 0 / 0 |
| 60 tàu bay | Reference | 2077.30 | 79.58 | 0 / 0 |

Case `workbook_peak_50`: run `20261101T092015Z-2cd7a0ae`; 1 seed, tối đa 2000 đánh giá nhanh, 20 cá thể, 30 thế hệ.

## Cách đọc

GA trong bảng là bộ tối ưu phối hợp đầy đủ. Các đề xuất bị rút sau kiểm tra thực thi được ghi trong từng run; không mặc định FCFS hoặc GA luôn khác Reference. Cần nhiều seed trước khi kết luận tổng quát.
Case nominal không vượt năng lực. Nếu GA giữ phương án Reference hoặc FCFS, không coi đó là một phương án mới do tiến hóa tìm được.
Chỉ sử dụng các chỉ tiêu trong bảng của đúng phiên bản hiện tại. Không mang tỷ lệ cải thiện từ case 80 tàu bay sang case 60 tàu bay. GA có thể giữ Reference hoặc FCFS nếu đó là phương án thực thi tốt nhất; không mặc định mọi biện pháp bổ sung cải thiện đồng thời mọi chỉ tiêu.
Biện pháp được chọn thực tế nằm trong manifest của từng bản replay. Miền tìm kiếm có GDP, RTA, tốc độ, vector ngắn và level cap; không bắt buộc phương án tốt nhất phải sử dụng mọi biện pháp.
Sáu sân bay nguồn dùng tọa độ điều phối gần đúng và thời gian lăn giả định; TSN sử dụng mạng đường lăn của mô phỏng. MIT/MINIT là tham số nghiên cứu.
Các kết quả cũ cho mô hình có đổi thứ tự chuyến còn đỗ không được ghép vào bảng này. Chương 4/5 hiện có cần cập nhật sau khi chốt bộ thí nghiệm nhiều seed và phân tích độ nhạy.

Chi tiết: `docs/Gate_flow_ATFM.md`. Kiểm chứng thực thi ở bước 1 giây; kiểm tra năng lực theo từng sector.

## Thời điểm hoàn thành phần ATFM

Đo theo quỹ đạo đã lưu và số tàu từng sector: nominal 01:32:18 (không còn tàu đến chưa hoàn thành); overload 02:25:44 (17 tàu đến còn tiếp tục hành trình). Reference và GA có cùng mốc dừng phần ATFM trong lượt chạy này. Toàn bộ bảng chậm/vượt năng lực phía trên vẫn tính đầy đủ đuôi hành trình đến, không cắt theo mốc dừng hiển thị.
