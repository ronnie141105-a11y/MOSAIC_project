# Supervisor · Centre / Approach / Tower

Ba màn hình dùng cùng StateReader, danh sách tàu bay và đồng hồ. Chuyển giao
chỉ đổi đơn vị hiển thị chính, không xóa hoặc tạo lại tàu bay ở ranh giới.

## Mở các màn hình

```powershell
.\.venv\Scripts\python.exe main.py --mock --profile tsn_tma
```

- `/centre`: bản đồ FIR Hồ Chí Minh, đường hàng không và lưu lượng đường dài.
- `/`: màn hình Approach hiện có, STAR/SID và point merge.
- `/airport`: Tower và chuyển động mặt đất hiện có.
- `/supervisor`: cả ba màn hình với một đồng hồ và bộ điều khiển chung.
  Nút ⛶ mở rộng một màn hình, **All views** trở lại cả ba, **Open** mở riêng.
  Đường dẫn `/control-room` vẫn mở Supervisor.

Supervisor gửi cùng một frame có dấu thời gian tới cả ba màn hình; Tower và
hai radar dùng cùng UTC trong ca phát lại. Nút Play/Pause, tốc độ, Restart
và thanh thời gian tác động tới cùng mô phỏng. Chế độ Day/Night dùng chung.
Mỗi radar có vùng nhìn và mức zoom riêng, lưu độc lập.

### Co giãn màn hình Tower

Tower trong Supervisor mặc định dùng **Runway chart**: một sơ đồ liền gồm hai
đường băng và các taxiway chính. Nền sáng, mặt đường xám và đường băng đen;
không vẽ sân đỗ, các nhánh dẫn vào stand hoặc tàu bay đang đỗ trong chế độ này.
Các liên kết S1, đường V và graph mô phỏng gốc được giữ nguyên. Các trục S, V,
Y và hai đường băng được căn thẳng; nhánh nối được làm tròn và các cạnh trùng
được gộp trước khi vẽ. Nhãn P1–P6, S1/S3–S10, V/V1 và Y/Y1–Y4/Y6–Y8 được
bố trí theo ảnh tham chiếu; tên điểm đầu 07L/25R và 07R/25L luôn hiện rõ.
Tọa độ hiển thị riêng được ánh xạ theo từng cạnh của graph, dùng cho cả tàu
bay, tuyến được chọn và thao tác kéo node; không sửa tọa độ mô phỏng.
Hai trục hiển
thị co giãn khác nhau để sơ đồ vừa ô Tower; chữ và ký hiệu tàu bay giữ kích
thước dễ đọc. Phần final 25R được nén theo chiều dài riêng để không làm nhỏ
toàn bộ sân bay. Không dùng khoảng cách pixel để đo cự ly thực.

Dùng **Fit map**, **− / +**, con lăn zoom và kéo chuột phải để dịch. Bấm tàu bay
xem chi tiết và tuyến màu xanh, kéo tới node để đổi tuyến, Shift-kéo để nối
waypoint. Chế độ **Full airport** vẫn có bản đồ đầy đủ và các stand.

Chuyển động Tower được nội suy giữa các frame chung; tàu bay taxi đi theo các
đỉnh đường taxi, không cắt góc bằng đường thẳng. Pause và seek hiển thị đúng vị
trí của frame ngay lập tức. Co giãn chỉ đổi khoảng cách theo pixel, không đổi
vận tốc kt, thời gian bay, giãn cách hoặc tốc độ mô phỏng. Đoạn final 8 NM vẫn
là phần kéo dài dạng sơ đồ, theo mô hình Tower hiện có.

## Ranh giới hiển thị 40 NM

- Chuyến đến ngoài 40 NM thuộc Centre. Khi vào 40 NM, Approach hiển thị
  chính, còn Centre giữ tàu bay màu xám khi độ cao còn từ 7.000 ft trở lên.
  Tàu bay chỉ ẩn khỏi Centre khi xuống dưới 7.000 ft trong vòng tròn TMA.
- Chuyến đi trong 40 NM thuộc Approach. Sau khi ra 40 NM, Centre hiển thị
  chính, còn Approach mờ dần bóng trong khoảng 40–44 NM.
- Số tàu bay của từng đơn vị chỉ đếm tàu bay thuộc đơn vị đó, không đếm bóng.
- Tuyến trên Centre là nét đứt màu xám nhạt, chìm vào nền. STAR chỉ hiển thị
  từ đường dài tới điểm bàn giao: BITIS, VICAL, GOMIN; nhánh DALAP cắt đúng
  vòng tròn 40 NM. Fan point merge và STAR phía trong dành cho Approach.
- Các điểm bàn giao Centre/Approach của SID và STAR dùng tam giác xám, gồm BACHU,
  MISAN, ANTRI, LANHI, XOBAV, VICAL, BITIS và GOMIN. Giữ tọa độ gốc;
  nhiều điểm nằm ngoài vòng tròn danh nghĩa một phần NM.
- SID vẫn hiển thị đầy đủ khi bật trong Options. NIXIV → VICAL là nhánh đến;
  XOBAV → NIXIV là nhánh đi. Bộ sinh feeder không dẫn chuyến đến qua XOBAV.
- Vệt bay giới hạn theo 10 NM đường đã bay, độc lập với mức zoom. Centre giữ
  cả phần vệt trong TMA khi tàu bay còn hiển thị. Approach cắt tại vùng của mình.
- Tàu bay overflight được khai báo rõ không tự bàn giao cho VVTS chỉ vì đi qua vòng tròn.
- Ranh giới 40 NM là quy ước nghiên cứu theo yêu cầu, chưa mô hình hóa quy trình
  phối hợp ACC/APP thực tế hoặc giới hạn theo độ cao.

## Kịch bản kiểm thử tổng hợp

Trong `/supervisor`, chọn **T1**, **T2** hoặc **T3**, bấm **Load**, rồi **Play**.
Ba bộ dữ liệu này được sinh từ bộ truyền chuyển động procedure hiện có, kiểm tra
giãn cách mỗi giây và khoảng bàn giao đến tối thiểu 120 giây trước khi lưu.
Đây là test chức năng, không phải các ca nghiên cứu hoặc FPL thực tế.
Chi tiết và cách tái tạo trong [System_test_scenarios.md](System_test_scenarios.md).

Demo live cũ vẫn có qua `POST /api/centre/demo` khi không phát lại ca.
Mốc `sid_exit` ghi khi hoàn tất SID, `centre_handoff` khi vượt 40 NM và
`fir_route_exit` khi hoàn tất đoạn đường dài đang mô phỏng.

Các chuyến đến thêm bằng bảng Tower tại đầu STAR sẽ được nối thêm đường dài.
Chuyến đã đặt giữa STAR giữ vị trí xuất phát đã chọn. Các chuyến đi từ Tower
tiếp tục trên đường dài sau SID. Callsign và bản ghi tàu bay giữ nguyên khi
chuyển Centre/Approach. Chuyển mặt đất/không trung giữ cơ chế Tower trước đây.

## Hai ca từ video

Trang `/case-scenarios` có tùy chọn **Mở rộng Centre / FIR bằng quỹ đạo giả định**.
Khi bật, hệ thống thêm đoạn đường dài trong bộ nhớ và bắt đầu sớm tới 60 phút,
từ lúc có tàu bay đầu tiên. Phần terminal gốc không bị sửa. Bỏ chọn tùy chọn
này để phát bộ ca terminal ban đầu. Có thể nạp các phương án GA đã lưu.

Nguồn video chỉ cung cấp nhãn và thời gian nhìn thấy. Đoạn FIR, vận tốc đường
dài, độ cao, thời điểm và liên kết tuyến là giả định mô phỏng. Các tuyến dùng
đường hàng không lịch sử đã đóng gói. Liên kết không có trong mạng được ghi
`SYNTHETIC CONNECTOR`, không coi là tuyến công bố. Không xác nhận chiều bay
hoặc mức bay cho khai thác thực tế.

Tower trong case replay hiển thị tiếp cận 8 NM và đoạn đầu cất cánh theo cùng
quỹ đạo. Đây là hiển thị sơ đồ, chỉ đọc. Video không có dữ liệu taxi nên không
tạo giả chuyển động taxi cho các ca phát lại. Các demo mặt đất vẫn hoạt động.

Các giá trị GA ngày 13/10 vẫn tính từ bộ terminal cũ. Đoạn FIR bổ sung chưa
được tối ưu hoặc dùng để tính lại hiệu quả GA. Bước tiếp theo là đưa thời điểm
mục tiêu vào TMA, dữ liệu đường dài và điều kiện áp dụng biện pháp vào bộ tối ưu.

## Kiểm tra

Hai ca tổng hợp mới tại `/case-scenarios` gồm 20 lượt/giờ thông thường và 50
lượt/giờ vượt năng lực giả định 42 lượt/giờ. Các ca này có lịch khởi hành/FPL
tổng hợp và bộ đánh giá GA đường dài riêng, gồm Centre, TMA, runway và phần
đuôi. Không dùng lại điểm GA terminal của hai ca video. Xem
[hướng dẫn nghiên cứu](VVTS_Workbook_Case_Study.md) để nạp đối chứng hoặc phương
án GA đã lưu và đọc kết quả kiểm tra một giây.

`tests/pytest/test_centre_connection.py` kiểm tra quỹ đạo liên tục, một chủ sở hữu,
không đổi bản ghi khi qua 40 NM, bảo toàn đường terminal và dữ liệu case gốc.
`tests/control_areas.test.cjs` kiểm tra bóng chuyển giao theo độ cao và đường đầy đủ trên Centre.
`tests/trails_nm.test.cjs` kiểm tra vệt 10 NM độc lập mức zoom.
`tests/tower_view.test.cjs` kiểm tra co giãn, nội suy theo đường taxi, pause và seek.
`tests/tower_chart_geometry.test.cjs` kiểm tra topology, tọa độ hiển thị và nhãn tham chiếu.
`tests/pytest/test_system_scenarios.py` tính lại giãn cách, khoảng bàn giao và phát hết ba test.
