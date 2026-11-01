**CHƯƠNG 3\. XÂY DỰNG MÔ HÌNH VÀ THUẬT TOÁN TỐI ƯU ATFM**  
   
**3.1. Mô hình luồng không lưu tại TMA Tân Sơn Nhất**  
3.1.1. Phạm vi không gian, luồng đến và các điểm kiểm soát  
3.1.2. Dữ liệu chuyến bay và giả định năng lực tiếp nhận  
   
**3.2. Bài toán tối ưu**   
**3.2. Bài toán tối ưu**  
***3.2.1. Biến quyết định và miền giá trị***  
Biến quyết định cho mỗi chuyến bay $i$ gồm hai thành phần:  
Loại biện pháp ${m}_{i}∈\{0,1,2\}$ (0 \= Không áp dụng; 1=Ground Delay; 2=Speed adjustment  
Mức độ biện pháp ${l}_{i}$ (ví dụ: GDP=5, 10, 15, 20 phút; Speed-5%, 10%, 15%).  
Miền giá trị của mức độ được giới hạn theo khả năng kỹ thuật của tàu bay và quy trình điều hành.  
Ví dụ mã hóa: với 5 chuyến bay, một cá thể (phương án phân bổ) có thể được mã hóa như sau:  
\[1 – 15, 2 – 10, 0 – 0, 1 – 5, 2 – 15\]  
Diễn giải:

- Chuyến 1: Ground delay 15 phút  
- Chuyến 2: Speed giảm 10%  
- Chuyến 3: Không áp dụng  
- Chuyến 4: Ground Delay 5 phút  
- Chuyến 5: Speed giảm 15%

***3.2.2. Hàm mục tiêu và cách tính chậm trễ***  
Hàm mục tiêu là tối thiểu hóa tổng chi phí quy đổi của các biện pháp, đồng thời phạt nặng các phương án vi phạm ràng buộc an toàn \[6\], \[7\], \[10\]:  
$$f=\sum\limits_{i=1}^{N}c\left({{m}_{i},\ {l}_{i}}\right)+\ λ.P\ \ \ \left({3}\right){\ }$$  
Trong đó:  
$c\left({{m}_{i},\ {l}_{i}}\right)$: là chi phí quy đổi của biện pháp áp dụng cho chuyến bay $i$ (dựa trên bảng hệ số quy đổi);  
$\lambda :$ là trọng số ưu tiên giữa chi phí và an toàn;  
$P:$ là mức phạt do vi phạm năng lực hoặc tạo điểm nóng mới.  
***3.2.3. Ràng buộc năng lực, giãn cách và khả năng điều chỉnh***  
Ràng buộc năng lực: số tàu bay trong mỗi khoảng thời gian $\leq$ 42 slot.  
Ràng buộc giãn cách an toàn: Khoảng cách giữa các tàu bay không được nhỏ hơn ngưỡng quy định.  
Ràng buộc khả năng điều chỉnh: Mức độ GDP và Speed Adjustment nằm trong khoảng cho phép.  
**3.3. Thiết kế thuật toán di truyền**  
***3.3.1. Mã hóa nhiễm sắc thể và khởi tạo quần thể***  
Mỗi cá thể đại diện cho một phương án phân bổ biện pháp. Nhiễm sắc thể được mã hóa dưới dạng danh sách gene, mỗi gene tương ứng một chuyến bay \[6\], \[7\]:  
\[${m}_{1}-{l}_{1},\ {m}_{2}-{l}_{2},…,\ {m}_{N}-{l}_{N}]$  
Quần thể ban đầu được tạo ngẫu nhiên trong miền giá trị cho phép. Để hạn chế số cá thể không khả thi, có thể kết hợp khởi tạo ngẫu nhiên với một số cá thể được tạo bằng heuristic, ví dụ ưu tiên điều chỉnh các chuyến bay có thời điểm đến gần tâm điểm nóng. Cách làm này chỉ là chiến lược khởi tạo của mô hình, không phải quy tắc điều hành bay thực tế.   
***3.3.2. Đánh giá cá thể và xử lý phương án không khả thi***  
Sau khi tạo cá thể, mô hình giải mã từng gene để tính thời điểm đến sau điều tiết. Từ các thời điểm mới, hệ thống tính nhu cầu theo từng khung thời gian, kiểm tra năng lực và các ràng buộc khác, sau đó tính tổng chi phí và fitness.  
Hàm thích nghi (Fitness) được xây dựng theo dạng \[8\], \[9\]:  
$$Fitness=\frac{1}{1+Tổng\ chi\ phí\ quy\ đổi+λ.P}\ \ \left({4}\right){\ }$$  
Cách tính này tạo penalty bằng 0 khi không có vi phạm năng lực. Khi mức vượt năng lực tăng, penalty tăng tương ứng. Nếu cần phạt mạnh hơn đối với vi phạm lớn, có thể sử dụng bình phương mức vượt, nhưng khi đó cần thực hiện phân tích độ nhạy để tránh làm mất cân bằng giữa các thành phần của hàm mục tiêu.

***3.3.3. Chọn lọc, lai ghép, đột biến và bảo toàn cá thể tốt***  
GA được xây dựng từ chu trình chọn lọc – lai ghép – đột biến – đánh giá – thay thế. Đây là các toán tử cơ bản của giải thuật di truyền; crossover tái tổ hợp thông tin từ các cá thể cha mẹ, trong khi mutation tạo biến đổi nhằm duy trì đa dạng quần thể.

| Toán tử | Cài đặt đề xuất | Lý do |
| ----- | ----- | ----- |
| Chọn lọc | Tournament Selection (k=3 hoặc 5\) | Duy trì đa dạng |
| Lai ghép | One-point/Two-point crossover, ${P}_{c}=0.8$ | Giữ cấu trúc theo nhóm chuyến bay |
| Đột biến | Uniform/Gaussian, ${P}_{m}=0.1$ | Thay đổi loại hoặc mức độ biện pháp |
| Elitism | Giữ 5-10% cá thể tốt nhất | Bảo toàn lời giải tốt |

Đột biến có hai kiểu chính:

- Đột biến loại biện pháp (thay đổi ${m}_{i})$;  
- Đột biến mức độ (thay đổi ${l}_{i}$ trong cùng loại).

***3.3.4. Tham số thuật toán và điều kiện dừng***  
Kích thước quần thể: 50-150 (tùy số chuyến bay);  
Số thế hệ tối đa: 100-300;  
Xác suất lai ghép ${P}_{c}=0.8$;  
Xác suất đột biến ${P}_{m}=0.1$ (trong khoảng 0.05-0.15 để cân bằng giữa khám phá và hội tụ);  
Điều kiện dừng: Không cải thiện fitness trong 30-50 thế hệ liên tiếp, hoặc đạt ngưỡng fitness mong muốn.  
Việc chọn ${P}_{m}=0.1$ (10%) là hợp lý vì nếu quá thấp dễ kẹt cục bộ, nếu quá cao thì thuật toán trở thành tìm kiếm ngẫu nhiên \[9\].

**3.4. Tích hợp thuật toán với mô phỏng**  
***3.4.1. Quy trình dữ liệu đầu vào – tối ưu – mô phỏng – ghi kết quả***  
Bước 1: Thu thập dữ liệu vị trí, tốc độ, hướng bay từ MOSAIC.   
Bước 2: Phát hiện điểm nóng bằng DBSCAN \+ PCA (Module 1).   
Bước 3: Chạy thuật toán GA để tìm phương án phân bổ biện pháp tối ưu (Module 3).   
Bước 4: Đưa phương án trở lại mô phỏng MOSAIC để kiểm chứng.   
Bước 5: Ghi nhận kết quả theo 5 chỉ tiêu đánh giá.  
***3.4.2. Kiểm chứng mô hình và kiểm tra tính khả thi của phương án***  
Mỗi phương án sau GA được đưa vào mô phỏng để kiểm tra:

- Có còn vượt năng lực 42 slot không;  
- Có xuất hiện điểm nóng mới không;  
- Các biện pháp có nằm trong giới hạn kỹ thuật không.

**3.5. Thiết kế thực nghiệm**  
***3.5.1. Phương pháp đối chứng và điều kiện so sánh***  
So sánh giữa:

- Baseline: Chỉ dùng một biện pháp đơn lẻ (ví dụ chỉ Ground Delay);  
- Giải pháp GA đa biện pháp;  
- (Tham khảo) ASTRA gốc sử dụng RL/PPO về tính minh bạch và chi phí tính toán \[6\], \[7\], \[10\].

***3.5.2. Kịch bản, chỉ số đánh giá và quy tắc tái lập***  
Kịch bản được xây dựng từ dữ liệu mô phỏng MOSAIC (ARR/DEP tại VVTS). Chỉ số đánh giá gồm 5 tiêu chí đã nêu ở mục 2.4. Quy tắc tái lập: chạy GA nhiều lần (ít nhất 10–20 lần) với cùng tham số để lấy giá trị trung bình và độ lệch chuẩn, đảm bảo tính ổn định của kết quả.

   
