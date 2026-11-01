"""Check the selected plans on a denser grid and save a readable result note."""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from astra.optimization.video_cases import VideoCaseEvaluator

folder=ROOT/'output/video_case_ga/2026-10-13'
lines=['# Kết quả GA trên hai ca VVTS, 13/10/2026','',
       '10 seed mỗi phương pháp. 80 cá thể, tối đa 160 thế hệ và 6.000 đánh giá, gồm chuẩn bị nghiệm.',
       'GA chỉ xét chuyến đến. Chuyến đi giữ lịch mô phỏng. Đầu vào gồm nhãn video và đường bay giả định.',
       'Năng lực 42 tổng lượt đến/đi mỗi giờ là tham số nghiên cứu của mô hình Chương 3.', '',
       '| Ca | Phương pháp | Cặp vi phạm TB ± SD | Chi phí biện pháp | Tổng điều tiết (phút) | Khả thi |',
       '|---|---|---:|---:|---:|---:|']
for case in ('nominal','holiday_peak'):
    file=folder/case/'results.json'
    result=json.loads(file.read_text(encoding='utf-8'))
    fine=VideoCaseEvaluator(case,sample_s=5)
    checks={}
    for method,name in [('NO_CONTROL','NO_CONTROL'),*result['best_methods'].items()]:
        metrics,_,audit=fine.evaluate(result['runs'][name]['plan'])
        checks[method]=dict(selected_run=name,metrics=metrics,audit=audit)
    result['post_validation']=dict(sample_s=5,scope='Selected best plan from each method, not all ten seeds',checks=checks)
    result['algorithm_sha256']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        for name in ('astra/optimization/video_cases.py','astra/optimization/formulation.py')}
    file.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    for row in result['summary']:
        lines.append(f"| {case} | {row['method']} | {row['mean_arrival_conflict_pairs']:.2f} ± {row['std_arrival_conflict_pairs']:.2f} | {row['mean_converted_cost']:.2f} | {row['mean_total_delay_min']:.2f} | {row['feasible_runs']}/10 |")
    print(case,'5s', {method:(check['metrics']['arrival_conflict_pairs'],check['metrics']['feasible_sampled']) for method,check in checks.items()},flush=True)
lines += ['', '## Cách đọc kết quả', '',
    '- Đối chứng không điều tiết có 15 cặp ở 08/10 và 61 cặp ở 22/02. Đây là đường bay neo vào yêu cầu chưa điều tiết, khác bản FCFS đã giãn cách trên radar.',
    '- GA phối hợp giảm số cặp vi phạm so với GA chỉ GDP khoảng 59,2% ở 08/10 và 29,1% ở 22/02.',
    '- Cả hai ca vẫn 0/10 phương án khả thi. Miền phối hợp có 1 cặp bắt buộc vi phạm ở 08/10 và 5 cặp ở 22/02 với mọi tổ hợp biện pháp hiện tại.',
    '- Chi phí biện pháp tăng ở cả hai ca. Tổng phút điều tiết ca Tết tăng từ 145,5 lên 161,2. Không coi giảm điểm mục tiêu là giảm nhiên liệu hoặc giảm toàn bộ chậm trễ.',
    '- Ground Delay áp dụng ở sân bay xuất phát của chuyến đến VVTS. Chuyến đã cất cánh trước lúc lập phương án không đủ điều kiện GDP.',
    '- Nguồn thời điểm xuất phát là giả định 95 phút trước mục tiêu runway. Quyết định lập trước đầu khung 60 phút.',
    '- Các bảng chỉ kiểm tra giãn cách theo mẫu. Kiểm tra 5 giây áp dụng phương án tốt nhất của từng phương pháp, vẫn không chứng nhận an toàn liên tục.',
    '- Ca 08/10 còn thiếu video đến nên 23 chuyến đến mang mã MOSN vẫn là giả định.', '',
    '## Tái lập', '', '`python scripts/run_video_case_ga.py`', '',
    'Chọn phương án ở /case-scenarios rồi nạp lên radar. Bản dựng FCFS giữ riêng và không bị ghi đè.',
    'Các file results.json, summary.csv, metrics.csv, convergence.csv và GA_*_flights.csv giữ số liệu chi tiết.']
(folder/'Ket_qua_GA_VVTS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
