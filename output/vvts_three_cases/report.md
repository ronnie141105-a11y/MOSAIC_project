# Ba kịch bản VVTS theo đơn xin dữ liệu

| Kịch bản | Giờ Việt Nam | Tình trạng | Flights có track | Samples trong khung |
|---|---|---|---:|---:|
| Thời tiết xấu | 2026-10-07T17:00:00+07:00 – 2026-10-07T19:00:00+07:00 | partial | 6 | 1158 |
| Điều kiện bình thường | 2026-10-08T09:00:00+07:00 – 2026-10-08T11:00:00+07:00 | missing | 0 | 0 |
| Cao điểm Tết | 2026-02-22T10:00:00+07:00 – 2026-02-22T12:00:00+07:00 | missing | 0 | 0 |

## Thời tiết xấu
Mẫu track cuối trong khung: 2026-10-07T11:32:36+00:00.

- Cần bổ sung: Danh sách arrival/departure đầy đủ, gồm delayed/cancelled/diverted
- Cần bổ sung: FPL đầy đủ trong khung giờ: EOBT, EET, Item 15 và phiên bản
- Cần bổ sung: METAR/SPECI và TAF đầy đủ, đặc biệt phần cuối khung giờ
- Cần bổ sung: Declared capacity theo thời gian; không suy từ throughput quan trắc
- Cần bổ sung: ATFM measures / CTOT có timezone và revision history để đối chiếu

## Điều kiện bình thường
Mẫu track cuối trong khung: Chưa có.

- Cần bổ sung: Danh sách arrival/departure đầy đủ, gồm delayed/cancelled/diverted
- Cần bổ sung: FPL đầy đủ trong khung giờ: EOBT, EET, Item 15 và phiên bản
- Cần bổ sung: METAR/SPECI và TAF đầy đủ, đặc biệt phần cuối khung giờ
- Cần bổ sung: Declared capacity theo thời gian; không suy từ throughput quan trắc
- Cần bổ sung: ATFM measures / CTOT có timezone và revision history để đối chiếu

## Cao điểm Tết
Mẫu track cuối trong khung: Chưa có.

- Cần bổ sung: Danh sách arrival/departure đầy đủ, gồm delayed/cancelled/diverted
- Cần bổ sung: FPL đầy đủ trong khung giờ: EOBT, EET, Item 15 và phiên bản
- Cần bổ sung: METAR/SPECI và TAF đầy đủ, đặc biệt phần cuối khung giờ
- Cần bổ sung: Declared capacity theo thời gian; không suy từ throughput quan trắc
- Cần bổ sung: ATFM measures / CTOT có timezone và revision history để đối chiếu

## Giới hạn

- Danh sách track mẫu không đại diện toàn bộ planned demand hay airport throughput.
- Chưa có FPL/declared capacity đầy đủ: chưa xác nhận Demand > Capacity hoặc định lượng lợi ích ATFM thực tế.
- TMA dùng profile nghiên cứu 40 NM hiện có; track trong vòng 120 NM được giữ làm bối cảnh upstream.
- Khung Tết 10:00–12:00 đã được người dùng xác nhận; nhãn cao điểm còn cần dữ liệu xác minh.
- Không áp dụng clearance. Không suy CTOT, holding clearance, runway closure hay ATFM delay từ ADS-B.
- Thời tiết quan trắc và TAF được tách riêng. Không ngoại suy thời tiết tới phần chưa có báo cáo.
