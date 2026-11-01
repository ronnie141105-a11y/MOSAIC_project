# Điều tiết phối hợp tại AC – BAOMY và các sân bay nguồn

Phiên bản mô hình: `ac-baomy-flow-1`; bộ đánh giá `fixed-order-regional-gate-ga-10`.

## Cách sử dụng

1. Chạy mô phỏng với cấu hình `tsn_tma`.
2. Trong Scenario Builder hoặc Supervisor, chọn **Nominal · 20 aircraft** hoặc **Sector overload · 60 aircraft**, sau đó chọn GA, FCFS hoặc Reference.
3. Mở Centre. Bấm sân bay trên bản đồ hoặc nút **GDP / TOBT / CTOT** để xem các chuyến tại Phú Quốc, Liên Khương, Buôn Ma Thuột, Pleiku, Cam Ranh, Côn Sơn (VVCS) và Tân Sơn Nhất. Số cạnh tên sân bay là số chuyến còn tại đỗ/đang lăn ở sân bay đó.
4. Bấm vòng tròn AC/BAOMY để xem lịch qua cụm dùng chung; PTH hiển thị nhánh cấp vào BAOMY. Các bảng dùng giờ UTC. Scenario Builder cũng liệt kê sân bay khởi hành bằng tên và mã ICAO.

## Dữ liệu và phạm vi

| Kịch bản | Đến đang bay khi bắt đầu | Đến còn tại sân bay nguồn | Khởi hành tại TSN | Tổng |
|---|---:|---:|---:|---:|
| Nominal | 8 | 6 | 6 | 20 |
| Overload | 24 | 18 | 18 | 60 |

Mỗi sân bay nguồn có 1 hoặc 3 chuyến mới. CTOT gốc bắt đầu từ phút 10–50; TOBT gốc sớm hơn theo thời gian lăn. Các chuyến này có TOBT, CTOT yêu cầu, CTOT điều tiết, quỹ đạo từ vị trí sân bay và thời điểm qua điểm chuyển giao. Trước CTOT chúng không xuất hiện như tàu bay đang bay trên radar. Sau hạ cánh tại TSN, chúng tiếp tục lăn vào đỗ.

Mặt đất tại sáu sân bay nguồn được biểu diễn bằng mốc thời gian tại đỗ/lăn giả định (8–10 phút). Tọa độ là vị trí điều phối gần đúng; không phải dữ liệu ARP/SID hoặc sơ đồ sân đỗ đã xác minh để khai thác. Mặt đất TSN tiếp tục sử dụng mô phỏng đường lăn hiện có. Đây là dữ liệu tổng hợp cho nghiên cứu.

## Quyết định điều tiết

| Biện pháp | Thực hiện trong mô hình | Giới hạn |
|---|---|---|
| GDP / CTOT | Trì hoãn khởi hành tại TSN hoặc sân bay nguồn | 0–60 phút bổ sung, bước 5 phút; bộ điều phối an toàn có thể tăng thêm |
| MIT / MINIT | AC và BAOMY dùng chung một luồng cấp vào APP | Nominal: 10 NM và 120 s; overload: 15 NM và 180 s |
| CTO / RTA | Tìm phương án tốc độ/quỹ đạo đạt giờ qua điểm | Chỉ đưa vào miền tìm kiếm khi có thể thực hiện; sai số mục tiêu 15 s |
| Tốc độ | Tăng hoặc giảm tốc trên phần Centre, giữ trạng thái ban đầu | −15% đến +10%; tốc độ thay đổi có giới hạn và trần phụ thuộc độ cao |
| Vector ngắn | Thêm một điểm vòng rồi trở về đúng điểm kế tiếp của tuyến | Lệch ngang ≤8 NM, quãng đường bổ sung ≤12 NM; không đổi STAR/đích đến |
| Level capping | Giới hạn mực bay của chuyến khu vực chưa khởi hành | FL180/220/260, thấp hơn mực bay yêu cầu; giữ phần sau điểm chuyển giao |

MIT/MINIT ở bảng là **tham số kịch bản**, không phải tiêu chuẩn phân cách được công bố cho AC/BAOMY. PTH–BAOMY được quản lý như nhánh cấp vào cùng cụm BAOMY; không gán thêm một năng lực độc lập không có dữ liệu chứng minh.

Ground Stop, đổi tuyến và slot swapping không nằm trong miền quyết định. Tên hàm `sequence_move` còn để tương thích, nhưng không đổi thứ tự. Các phương pháp đều giữ thứ tự hàng chờ TSN, thứ tự khởi hành tại từng sân bay nguồn và thứ tự qua điểm của cùng dòng đến. GDP của các sân bay nguồn có khoảng cách cất cánh giả định tối thiểu 240 s.

## GA và FCFS được so sánh như thế nào

FCFS ghép đầu các hàng chờ cố định, cấp thời gian khả thi sớm nhất và kiểm tra giãn cách, đường băng, chuyển giao, cụm cửa vào, năng lực từng sector. Chạy cả lưới CTOT 5 và 10 phút; kết quả thực thi tốt hơn là đối chứng. GA phối hợp GDP/CTOT, RTA, tốc độ, vector ngắn và level cap trong cùng một thuật toán. Giao diện và báo cáo chỉ trình bày GA → FCFS → Reference; các lượt ablation cũ được giữ trong dữ liệu lịch sử.

Một gene chọn **một gói điều khiển** cho mỗi chuyến. Gói RTA có thể phối hợp tốc độ với vector; với chuyến chưa rời sân bay, RTA muộn được thực hiện bằng GDP. Phiên bản này chưa tìm mọi tổ hợp GDP × tốc độ × mực bay độc lập trên cùng một chuyến.

Điểm số dùng chặn vi phạm an toàn trước, sau đó tối thiểu hóa:

`J = D_ground + 2 D_air + lambda × E_sector`

Trong đó D là tổng phút chậm tàu bay; GDP tại sân bay nguồn và chậm của khởi hành TSN được tính vào D_ground. E_sector là tích phân số tàu vượt năng lực riêng từng sector theo thời gian, đơn vị tàu bay-phút. Hệ số 1/2 và lambda là giả định nghiên cứu; chưa phải nhiên liệu hoặc tiền. Giảm E có thể đổi lấy tăng chậm. GA không được đảm bảo luôn tốt hơn FCFS.

Reference đã có điều phối an toàn và chương trình cửa vào. Chuyến đã bay có cùng vị trí, độ cao ban đầu giữa các phương pháp; không được trì hoãn bằng cách đứng yên trên không. Việc xếp giờ GDP trong Reference được tính vào chi phí mặt đất của sân bay nguồn.

## Kiểm tra và minh bạch kết quả

Quỹ đạo đến và cặp đến được dự báo ở bước 1 s; năng lực và cặp có chuyến khởi hành dùng lưới 20 s khi tìm kiếm. Phương án thực thi được kiểm tra toàn bộ ở bước 1 s, gồm cả luồng AC/BAOMY và mặt đất. Vi phạm không được xuất bản làm bản replay hợp lệ. GA có ngân sách kiểm tra mô phỏng thực thi riêng; phương án bị rút và biện pháp đã thực hiện được lưu trong từng run.

CTOT/RTA đề xuất có thể được điều chỉnh để giữ an toàn. Bảng Centre hiển thị CTO cuối cùng và RTA đề xuất riêng; trạng thái `REVISED_BY_SAFETY_METERING` tránh hiểu nhầm rằng mọi mục tiêu RTA đều được đạt. RTA/vector không khả thi bị loại, không thay bằng dừng trên không.

Các kết quả trước 01/11/2026 dùng bộ tối ưu có đổi thứ tự tàu bay còn đỗ. Chúng là kết quả lịch sử và không được dùng làm bằng chứng cho mô hình giữ thứ tự hiện tại. Các đường tải báo cáo cũ được chặn nếu mã run/phiên bản không khớp. Lượt chạy 1 seed chỉ kiểm chứng tích hợp; cần nhiều seed và phân tích độ nhạy để viết kết luận hiệu quả cho luận văn.

## Tài liệu phương pháp

- [ICAO Doc 9971, bản được FAA cung cấp](https://tfmlearning.faa.gov/tfm-training/atfm-basics/files/pdf/Doc.9971-EN%20Manual%20on%20Collaborative%20Air%20Traffic%20Flow%20Management.pdf): MIT/MINIT, điều tiết tại nguồn và phối hợp giờ đến.
- [EUROCONTROL ATFCM Operations Manual 2026](https://www.eurocontrol.int/sites/default/files/2026-03/eurocontrol-atfcm-operations-manual-wave-2-3-external.pdf): biện pháp điều tiết và level capping.

Các tài liệu hỗ trợ lựa chọn loại biện pháp; không chứng nhận tham số hoặc quỹ đạo tổng hợp của mô hình này.

## Compact case revision

Regional and initially airborne arrivals are interleaved by requested gate times; neither entire cohort is appended after the other. Original and regulated TOBT/CTOT are separate. A synthetic touchdown metering window leaves the last five minutes of each 15-minute period available for departure opportunities; runway clearance and separation checks still decide whether a departure can use a gap. Airborne aircraft absorb sequencing through longer initial upstream routes and bounded speed/RTA vectors, without pausing in the air. Dynamic terminal holding/point-merge route selection is not a GA decision in this version.

Arrivals vacate only via P5, cross 25L through the connected S8 crossing, and wait 20 seconds after wheel-off before entering the crossing.

## Mixed-start continuous-flow revision

The overload cohort is 60 aircraft: 24 initially airborne arrivals (two already on full point-merge arcs), 18 origin-pending arrivals, and 18 TSN departures. Four TSN departures are already airborne at startup: two in APP climb, one in Centre and one close to onward transfer. Nominal uses 20 aircraft, with three TSN departures already airborne and two arrivals on arcs. Historical TOBT/CTOT remain visible with a negative-minute indication; airborne departures cannot receive GDP or revised pre-start history.

Phú Quốc flights use PQU → RG → TRN → BITIS and BITIS2H. NIXIV–VICAL is a separate feeder, not a Phú Quốc route. Saved waypoint coordinates and assumed airport joins remain synthetic scenario geometry.

Startup states result from a one-hour native warmup, not teleports to runway or arbitrary snapshots. Remaining TSN departure readiness is spaced every four minutes; regional origin demand repeats every 15 minutes per source. Initially airborne gate demand is regular; safety and ATFM metering adjust the executed stream.

The display declares **ATFM complete** when all TSN departures have left the modeled sector and the current sector counts do not exceed capacity. Remaining arrivals are preserved; **Continue arrivals** runs the tail. This operational pause never rewrites aircraft completion counts. Comparative statistics and final safety audits still cover the complete flight cohort, including the arrival tail; they are not silently shortened to the display pause. Historical takeoffs are excluded from runway-event counts inside the planning window.

The earlier 19.8% excess and 7.8% delay reductions were the GDP-only GA in an 80-aircraft case. This is a different cohort, route set and initialization, and the single current GA is the coordinated method. Percentages from those experiments cannot be combined.
