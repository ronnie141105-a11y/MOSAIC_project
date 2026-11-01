"""Write a concise, annotated note from the latest published teammate benchmarks."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from astra.optimization.teammate_cases import saved_result


def main():
    cases=[saved_result(case) for case in ('nominal','holiday_peak')]
    for result in cases:
        settings=result['settings']
        if (len(settings['seeds'])!=10 or settings['population']!=80 or settings['generations']!=150
                or settings['max_evaluations']!=6000 or not settings['compare_legacy']):
            raise ValueError('This dated benchmark report requires the full default ten-seed comparison; run run_teammate_ga.py first.')
    lines=['# Kết quả tích hợp GA cộng tác — 20/10/2026','',
        'Mã gốc do thành viên nhóm đóng góp. Bản tích hợp giữ mã hóa (biện pháp, mức độ), ',
        'tournament, lai ghép một điểm, đột biến phân loại và elitism; sửa lỗi và dùng bộ kiểm tra MOSAIC.', '',
        '## Cách chạy và đọc bảng','',
        '- Mỗi ca: 10 seed, 80 cá thể, tối đa 150 thế hệ, 6.000 đánh giá duy nhất/phương pháp/seed, gồm chuẩn bị nghiệm.',
        '- Hai GA dùng cùng dữ liệu, chi phí, miền hành động, nghiệm GDP khởi đầu và ngân sách. GA cộng tác dừng sau 30 thế hệ không cải thiện; GA trước đây sau 40.',
        '- Greedy: hai lượt tối ưu lần lượt từng chuyến, không chọn lọc/lai ghép/đột biến.',
        '- Bảng chính dùng lưới thời gian 20 giây. Cặp vi phạm được đếm một lần nếu có ít nhất một thời điểm vi phạm; không phải số lần cảnh báo hoặc số tai nạn.',
        '- TB ± SD: trung bình và độ lệch chuẩn mẫu qua các seed; greedy/không điều tiết là một phương án xác định.',
        '- Chi phí C: GDP 1 đơn vị/phút; giảm tốc 2 đơn vị/phút chậm phát sinh. Đây là đơn vị giả định, không phải tiền/nhiên liệu.',
        '- P = số lượt vượt năng lực + số cặp vi phạm + số cặp vi phạm mới. Mục tiêu = C + 1.000P; fitness = 1/(1+mục tiêu).',
        '- Khả thi yêu cầu không có vi phạm năng lực và giãn cách, không chỉ mục tiêu thấp hơn.', '',
        '| Ca | Phương pháp | Cặp đến–đến vi phạm | Chi phí C | Tổng điều tiết (phút) | Khả thi |',
        '|---|---|---:|---:|---:|---:|']
    for r in cases:
        for method in ('NO_CONTROL','GREEDY_GROUND','GREEDY_MIXED'):
            m=r['runs'][method]['metrics']
            lines.append(f"| {r['case_id']} | {method} | {m['arrival_conflict_pairs']} | {m['converted_cost']:.2f} | {m['total_delay_min']:.2f} | {'Đạt' if m['feasible_sampled'] else 'Chưa đạt'} |")
        for row in r['summary']:
            lines.append(f"| {r['case_id']} | {row['method']} | {row['mean_arrival_conflict_pairs']:.2f} ± {row['std_arrival_conflict_pairs']:.2f} | {row['mean_converted_cost']:.2f} | {row['mean_total_delay_min']:.2f} | {row['feasible_runs']}/{row['seeds']} |")
    lines += ['', 'TEAM = GA cộng tác đã tích hợp. LEGACY = GA trước đây chạy lại theo cùng giao thức so sánh mới.', '',
        '## Kiểm tra dày 5 giây','',
        'Chỉ kiểm tra các phương án chọn trong bảng dưới, không phải trung bình toàn bộ 10 seed. Phương án TEAM được chọn theo mục tiêu trên lưới 20 giây.', '',
        '| Ca | Phương án | Cặp đến–đến (20 s) | Cặp đến–đến (5 s) | Cặp đến–đi (5 s) | Vượt năng lực (5 s) |',
        '|---|---|---:|---:|---:|---:|']
    for r in cases:
        for method,check in r['post_validation']['checks'].items():
            coarse=r['runs'][check['selected_run']]['metrics'];fine=check['metrics']
            lines.append(f"| {r['case_id']} | {method} | {coarse['arrival_conflict_pairs']} | {fine['arrival_conflict_pairs']} | {fine['arrival_departure_conflict_pairs']} | {fine['capacity_excess_flights']} |")
    metrics={r['case_id']:{row['method']:row for row in r['summary']} for r in cases}
    nominal,holiday=cases
    ng=nominal['runs']['GREEDY_MIXED']['metrics']['arrival_conflict_pairs']
    hg=holiday['runs']['GREEDY_MIXED']['metrics']['arrival_conflict_pairs']
    nt=metrics['nominal']['TEAM_MIXED']['mean_arrival_conflict_pairs']
    ht=metrics['holiday_peak']['TEAM_MIXED']['mean_arrival_conflict_pairs']
    nl=metrics['nominal']['LEGACY_MIXED']['mean_arrival_conflict_pairs']
    hl=metrics['holiday_peak']['LEGACY_MIXED']['mean_arrival_conflict_pairs']
    nf=len(nominal['domain_diagnostics']['mixed']['unavoidable_arrival_pairs'])
    hf=len(holiday['domain_diagnostics']['mixed']['unavoidable_arrival_pairs'])
    checked=holiday['post_validation']['checks']
    lines += ['', '## Nhận xét','',
        '- GA cộng tác đã chạy và nạp được vào radar với đúng danh sách chuyến bay. Phương án phối hợp giảm vi phạm so với không điều tiết trên các đường bay giả định.',
        f'- Cặp đến–đến ca thường: greedy {ng}, TEAM_MIXED trung bình {nt:.2f}. Ca Tết: greedy {hg}, TEAM_MIXED trung bình {ht:.2f}.',
        f'- So sánh TEAM_MIXED / LEGACY_MIXED: ca thường {nt:.2f} / {nl:.2f} cặp; ca Tết {ht:.2f} / {hl:.2f} cặp. Chưa có bằng chứng bản mới vượt trội toàn diện hoặc khác biệt có ý nghĩa thống kê.',
        f"- Lưới 5 giây tìm thêm vi phạm. Ca Tết: TEAM_MIXED được chọn còn {checked['TEAM_MIXED']['metrics']['arrival_conflict_pairs']} cặp; greedy mixed còn {checked['GREEDY_MIXED']['metrics']['arrival_conflict_pairs']} cặp. Phải xét phép kiểm tra dày trước khi kết luận lợi thế.",
        f'- Có {nf} cặp bắt buộc vi phạm ở ca thường và {hf} cặp ở ca Tết trong mọi tổ hợp hành động phối hợp hiện tại; các phương án không thể đạt hết ràng buộc trong miền này.',
        '- Năng lực không bị vượt ở các phương án đã chạy. Mã gốc chỉ xét số chuyến đến với giới hạn 42/giờ sẽ không thấy vấn đề ở hai ca chỉ có tổng 23/37 chuyến đến; ràng buộc giãn cách là phần cần bổ sung.',
        '- Tăng số thế hệ không thể loại bỏ các cặp bắt buộc vi phạm trong miền hiện tại. Muốn nghiên cứu phương án khả thi cần thay đổi hợp lý thời điểm quyết định hoặc miền biện pháp, rồi đánh giá lại; chưa tự thay những giả định này.', '',
        '## Phạm vi và giả định','',
        '- Ca thường 08/10: 23 đến giả định + 32 đi. Ca Tết 22/02: 37 đến + 43 đi. Nhãn video được đối chiếu; đường bay, tọa độ, mục tiêu runway và giờ xuất phát là dữ liệu tái dựng.',
        '- GDP 5/10/15/20 phút chỉ cho chuyến chưa cất cánh tại thời điểm lập phương án (trước khung 60 phút, giả định xuất phát trước mục tiêu đến 95 phút). Giảm tốc 5/10/15% trên đoạn upstream giả định 20 phút.',
        '- Giãn cách đến–đến: 10 NM, cùng hướng (chênh hướng ≤25°) 20 NM, không xét giãn cách đứng cho cặp đến. Chẩn đoán đến–đi: 5 NM và 1.000 ft. Miền kiểm tra: 40 NM, 3.000–16.570 ft.',
        '- Năng lực 42 tổng lượt đến/đi trong từng khung 60 phút cố định kể từ đầu ca, gồm phần đuôi trễ; không phải giờ trượt hoặc năng lực công bố đã xác thực.',
        '- Chuyến đi giữ nguyên thời gian/quỹ đạo. Biện pháp upstream được thể hiện bằng dịch giờ terminal. Phần Centre/FIR bổ sung không nằm trong đánh giá GA.',
        '- Đây là nghiên cứu mô phỏng, không phải xác nhận an toàn khai thác hoặc tối ưu nhiên liệu.', '',
        '## Mở trên hệ thống','',
        'Mở `/case-scenarios` → **Chạy GA trên hai ca nghiên cứu** → chọn ca → **Xem kết quả đã lưu**. ',
        'Bấm **Nạp phương án phối hợp mới lên radar** để xem phương án đúng run ID đang hiển thị.', '',
        '```powershell', '.venv\\Scripts\\python.exe -B -X utf8 scripts/run_teammate_ga.py', '```', '',
        '## Dữ liệu tái lập','']
    for r in cases:
        lines += [f"- {r['case_id']}: `{r['run_id']}`; seed `{r['settings']['seeds']}`.",
                  f"  Dữ liệu snapshot: `scenarios/reconstructed/vvts_video_cases/{r['case_id']}/variants/team_ga/{r['run_id']}/`."]
    lines += ['', 'Mỗi snapshot chứa results.json, summary.csv, metrics.csv, convergence.csv, ',
              'TEAM_*_flights.csv, quỹ đạo nạp radar và hash nguồn/thuật toán. Mã gốc và các kết quả cũ được giữ lại.', '']
    target=ROOT/'output/teammate_ga/Ket_qua_GA_cong_tac_2026-10-20.md'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text('\n'.join(lines),encoding='utf-8')
    print(target)


if __name__=='__main__':
    main()
