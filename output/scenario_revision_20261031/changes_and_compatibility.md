# Thay đổi kịch bản và nội dung cần thống nhất với Chương 3

Đợt cập nhật ngày 31 tháng 10 năm 2026 giữ hai case trong Scenario Builder và Supervisor: danh định 20 tàu bay, quá tải 60 tàu bay gồm 36 đến và 24 đi. Mã `workbook_peak_50` được giữ để không làm hỏng liên kết; số lượng hiển thị và dữ liệu là 60.

Kịch bản quá tải giữ phân bố nhóm tuyến và năng lực sector, nhưng bố trí lại trạng thái thượng nguồn cùng đợt sẵn sàng khởi hành. Tất cả tàu bay đến chuyển động từ đầu; luồng đến riêng không vượt năng lực. Khi kết hợp tàu bay đi, tham chiếu có 83,05 tàu bay-phút vượt năng lực. Điều kiện chấp nhận case được ghi trong `protocol.json`, không dựa vào kết quả thắng hoặc thua của GA.

Một lần kiểm tra FCFS phát hiện kẹt giữa tàu bay đi và tàu bay đến ở nút giao đường lăn. Quy tắc nhường trước nút giao được sửa chung; cả hai tham chiếu được kiểm chứng lại trước bộ thử cuối. Nhu cầu, mốc sẵn sàng và vị trí ban đầu trên không của case danh định được giữ. Các kết quả và bản Word trước đợt sửa nằm trong thư mục này hoặc các thư mục chạy cũ.

Các định nghĩa sau cần dùng nhất quán trong Chương 3 và Chương 4:

- **Năng lực:** số tàu bay đang bay đồng thời trong đúng sector, không phải tổng biểu tượng trên radar hoặc số chuyến mỗi giờ. E là tổng phần vượt năng lực theo sector và thời gian, đơn vị tàu bay-phút.
- **Mốc chậm trễ:** với tàu bay đi, dùng thời điểm sẵn sàng cất cánh cố định đã gán trước xếp lịch; với tàu bay đến, dùng thời điểm chạm bánh không điều tiết từ cùng trạng thái ban đầu. Gọi các mốc này là r_i. D = tổng max(0, t_i − r_i)/60 khi thời gian tính bằng giây. Không cộng quãng bay thượng nguồn do khởi tạo vào chậm trễ của GA.
- **Chỉ tiêu phụ:** phần tăng dương và thay đổi có dấu so với lịch tham chiếu được lưu riêng. Không trộn chúng với D chính, cũng không ghép trung bình kết quả cũ và mới.
- **Hàm mục tiêu thực thi:** sau khi đạt kiểm tra an toàn, J = D_đi + 2 D_đến + 10.000 E. Đây là trọng số giả định, không phải chi phí tiền hoặc nhiên liệu.
- **Biến điều khiển:** với tàu bay đi còn đỗ, CTOT mục tiêu bằng r_i cộng 0–60 phút. Lựa chọn không điều tiết giữ lịch tham chiếu. Tàu bay đã lăn giữ thứ tự cam kết và không được đưa sớm hơn. GA có thể đổi thứ tự nhóm còn đỗ. Giảm tốc trên đoạn Centre đủ điều kiện có các mức 1/2/3/5/10/15%; không tối ưu độ cao, đường bay hoặc năng lực tùy ý.
- **Đối chứng:** thực thi FCFS bước một phút và năm phút, chọn J thấp hơn làm đối chứng chính. Cả hai nghiệm được cho GA ở bước khởi tạo. So sánh GA mặt đất với FCFS là so sánh cùng nhóm biện pháp; GA kết hợp có thêm điều chỉnh tốc độ.
- **Thực nghiệm:** 10 seed cố định 11, 22, …, 110; quần thể 60; tối đa 120 thế hệ; 6.000 đánh giá nhanh mỗi phương pháp và seed, gồm kiểm tra FCFS khởi tạo. Tối đa bốn checkpoint thực thi được đếm riêng. Báo cáo trung bình và độ lệch chuẩn mẫu của toàn bộ seed.
- **Đóng góp tìm kiếm:** phần cải thiện từ chọn nghiệm khởi tạo phải tách khỏi cải thiện sau khởi tạo. Phần sau vẫn gồm GA, tìm kiếm cục bộ và phản hồi mô phỏng; chưa chứng minh đóng góp riêng của từng toán tử.
- **Kết quả:** bảng chính sử dụng thực thi một giây, gồm chậm trễ do bộ điều khiển bổ sung. Sự kiện cất/hạ cánh và hoàn tất hành trình đến vị trí đỗ hoặc hết đoạn Centre được đếm riêng.

Các giới hạn, tốc độ, quỹ đạo và quy tắc bảo vệ là giả định mô phỏng. Kết quả chỉ mô tả hai bộ nhu cầu tổng hợp, chưa phải hiệu quả đã xác minh trong khai thác thực tế. Mã băm đầu vào chung cho mọi phương pháp được lưu ở `final_frozen_inputs_sha256.json`.

Để chạy lại bộ thử cuối:

```powershell
.\.venv\Scripts\python.exe scripts/run_full_route_studies.py --seeds 11 22 33 44 55 66 77 88 99 110 --population 60 --generations 120 --max-evaluations 6000
.\.venv\Scripts\python.exe scripts/report_fcfs_ga_comparison.py
.\.venv\Scripts\python.exe scripts/prepare_thesis_summary.py
```

Không chạy lại script dựng kịch bản nếu chỉ muốn tái lập so sánh trên đầu vào đã đóng băng.
