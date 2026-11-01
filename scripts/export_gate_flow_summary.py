"""Export current pilot evidence without recycling previous thesis results."""
from pathlib import Path
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from astra.optimization.full_route_cases import saved_result

def export():
    target=Path(__file__).resolve().parents[1]/'output/gate_flow_revision_20261101'
    target.mkdir(parents=True,exist_ok=True)
    sources={};lines=['# Kết quả kiểm chứng tích hợp ATFM mới','',
        'Mô hình giữ thứ tự hàng chờ; không Ground Stop, đổi tuyến hoặc slot swapping. Đây là lượt chạy thử 1 seed cho mỗi case, không phải kết luận thống kê cho luận văn.','']
    for case in ('workbook_low_20','workbook_peak_50'):
        r=saved_result(case);sources[case]=dict(run_id=r['run_id'],version=r['version'],input_sha256=r['input_sha256'])
        lines.extend(['| Case | Phương pháp | Tổng chậm (tàu bay-phút) | Vượt năng lực (tàu bay-phút) | Vi phạm phân cách / cửa vào |','|---|---|---:|---:|---:|'])
        rows={row['method']:row for row in r['native_summary']}
        for method in ('TEAM_MIXED','FCFS','NO_CONTROL'):
            row=rows[method]
            name={'NO_CONTROL':'Reference','FCFS':'FCFS','TEAM_GROUND':'GA GDP/CTOT','TEAM_MIXED':'GA'}[row['method']]
            lines.append(f'| {r["case_counts"]["total"]} tàu bay | {name} | {row["mean_total_delay_min"]:.2f} | {row["mean_sector_excess_aircraft_minutes"]:.2f} | {row["mean_separation_conflict_pairs"]:.0f} / {row["mean_gate_flow_violations"]:.0f} |')
        lines.extend(['',f'Case `{case}`: run `{r["run_id"]}`; {len(r["settings"]["seeds"])} seed, tối đa {r["settings"]["max_evaluations"]} đánh giá nhanh, {r["settings"]["population"]} cá thể, {r["settings"]["generations"]} thế hệ.',''])
    lines.extend(['## Cách đọc','',
        'GA trong bảng là bộ tối ưu phối hợp đầy đủ. Các đề xuất bị rút sau kiểm tra thực thi được ghi trong từng run; không mặc định FCFS hoặc GA luôn khác Reference. Cần nhiều seed trước khi kết luận tổng quát.',
        'Case nominal không vượt năng lực. Nếu GA giữ phương án Reference hoặc FCFS, không coi đó là một phương án mới do tiến hóa tìm được.',
        'Chỉ sử dụng các chỉ tiêu trong bảng của đúng phiên bản hiện tại. Không mang tỷ lệ cải thiện từ case 80 tàu bay sang case 60 tàu bay. GA có thể giữ Reference hoặc FCFS nếu đó là phương án thực thi tốt nhất; không mặc định mọi biện pháp bổ sung cải thiện đồng thời mọi chỉ tiêu.',
        'Biện pháp được chọn thực tế nằm trong manifest của từng bản replay. Miền tìm kiếm có GDP, RTA, tốc độ, vector ngắn và level cap; không bắt buộc phương án tốt nhất phải sử dụng mọi biện pháp.',
        'Sáu sân bay nguồn dùng tọa độ điều phối gần đúng và thời gian lăn giả định; TSN sử dụng mạng đường lăn của mô phỏng. MIT/MINIT là tham số nghiên cứu.',
        'Các kết quả cũ cho mô hình có đổi thứ tự chuyến còn đỗ không được ghép vào bảng này. Chương 4/5 hiện có cần cập nhật sau khi chốt bộ thí nghiệm nhiều seed và phân tích độ nhạy.','',
        'Chi tiết: `docs/Gate_flow_ATFM.md`. Kiểm chứng thực thi ở bước 1 giây; kiểm tra năng lực theo từng sector.'])
    (target/'implementation_results.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (target/'current_source_runs.json').write_text(json.dumps(sources,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return target/'implementation_results.md'

if __name__=='__main__':print(export())
