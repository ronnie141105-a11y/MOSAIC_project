const $ = id => document.getElementById(id);
const n = value => Number.isFinite(value) ? value.toFixed(2) : '—';
let result = null, lastStatus = null;
async function api(path, body) {
  const response = await fetch('/api/atfm/formulation/' + path, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type':'application/json'}, body:JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}
function row(id, values) {
  const tr = document.createElement('tr');
  for (const value of values) { const td = document.createElement('td'); td.textContent = value; tr.append(td); }
  $(id).append(tr);
}
function plan() {
  $('flights').replaceChildren();
  const run = result?.runs[$('method').value];
  if (!run) return;
  const m = run.metrics;
  $('plan-status').textContent = `${m.feasible_in_synthetic_tma ? 'Khả thi trong TMA giả lập' : 'Chưa khả thi trong TMA giả lập'} · P=${n(m.penalty)} · ${m.ground_flights} ground / ${m.speed_flights} speed / ${m.no_action_flights} không điều tiết. Upstream chưa được kiểm tra.`;
  for (const f of run.flights) row('flights', [f.id, f.measure,
    ['Không điều tiết','Ground delay','Giảm tốc'][f.measure], `${f.level}${f.measure === 2 ? '%' : ' phút'}`,
    n(f.total_delay_min), n(f.converted_cost), n(f.entry_min)]);
}
function render() {
  for (const id of ['summary','metrics','method','validation','limitations']) $(id).replaceChildren();
  const s = result.scenario;
  $('case').value = s.case;
  $('scenario-description').textContent = `${s.flights.length} arrivals · ${s.capacity_per_interval.join('/')} chuyến mỗi ${s.capacity_interval_min} phút; capacity sau các khoảng này: ${s.tail_capacity}. Trần 42 chuyến mỗi giờ cố định [0,60), [60,120)…; occupancy limit: ${s.occupancy_limit ?? 'không áp dụng'}. λ=${s.penalty_lambda}; penalty power=${s.penalty_power}.`;
  for (const r of result.summary) row('summary', [r.method, `${r.feasible_runs}/${r.seeds}`,
    ...['mean_objective','std_objective','mean_converted_cost','mean_total_delay_min','mean_separation_conflict_pairs'].map(k => n(r[k]))]);
  const ground = result.summary.find(r => r.method === 'GA_GROUND');
  const mixed = result.summary.find(r => r.method === 'GA_MIXED');
  $('assessment').textContent = `10 seed: ground khả thi ${ground.feasible_runs}/${ground.seeds}; mixed ${mixed.feasible_runs}/${mixed.seeds}. Objective thấp hơn vẫn cần đọc penalty, delay và phạm vi kiểm tra. Kết quả là thử nghiệm trên dữ liệu giả lập.`;
  const diagnosis = result.domain_diagnostics?.mixed;
  $('domain-diagnostics').textContent = diagnosis ? (diagnosis.proven_infeasible
    ? `Miền biện pháp hiện tại không có nghiệm thỏa hết các ràng buộc: ít nhất ${diagnosis.capacity_bound.excess_lower_bound} chuyến vượt capacity; ít nhất ${diagnosis.unavoidable_conflict_pairs.length} cặp mất giãn cách không thể tránh bằng các mức đã cho.`
    : 'Kiểm tra miền biện pháp chưa chứng minh kịch bản bất khả thi. Nếu còn vi phạm, kết quả chỉ cho biết GA chưa tìm được nghiệm khả thi trong ngân sách này.') : '';
  for (const [name, r] of Object.entries(result.runs)) {
    const m = r.metrics;
    row('metrics', [name, m.feasible_in_synthetic_tma ? 'Khả thi' : 'Chưa khả thi',
      ...['converted_cost','penalty','objective','fitness','total_delay_min'].map(k => k === 'fitness' ? m[k].toPrecision(4) : n(m[k])),
      m.capacity_excess_flights + (s.capacity_interval_min === 60 ? 0 : m.hourly_excess_flights),
      m.separation_conflict_pairs, m.new_conflict_pairs, r.search.total_evaluations ?? '—', n(r.search.total_elapsed_s)]);
    const option = document.createElement('option'); option.value = name; option.textContent = name; $('method').append(option);
  }
  $('method').value = result.best_methods.GA_MIXED;
  for (const [name, r] of Object.entries(result.pipeline_validation || {})) row('validation',
    [name,n(r.peak_complexity),`${r.hotspot_frames}/${r.frames}`,r.new_hotspot_memberships.length]);
  const limits = ['Các chi phí quy đổi và ngưỡng giãn cách là giả định nghiên cứu.',
    'Chưa có FPL, năng lực khai thác được xác minh và giới hạn kỹ thuật theo loại tàu bay.',
    'Giảm ground speed chưa mô hình hóa gió, IAS/Mach, nhiên liệu hoặc xung đột upstream.',
    'P dùng cặp xung đột mới làm đại diện; chưa đưa DBSCAN/PCA trực tiếp vào fitness.',
    'Mục 2.4 chưa được gửi; cần đối chiếu bộ chỉ tiêu cuối cùng với nhóm nghiên cứu.'];
  for (const text of limits) { const li = document.createElement('li'); li.textContent = text; $('limitations').append(li); }
  const curves = Object.entries(result.runs).filter(([,r]) => r.history.length);
  const xmax = Math.max(1,...curves.flatMap(([,r]) => r.history.map(h => h.evaluations+r.search.preparation_evaluations)));
  const values = curves.flatMap(([,r]) => r.history.map(h => h.objective));
  const lo = Math.min(...values), hi = Math.max(...values), range = Math.max(1,hi-lo);
  let svg = '<svg viewBox="0 0 900 250" role="img" aria-label="Hội tụ f theo ngân sách đánh giá"><text x="25" y="22" fill="#dce7f3">Hội tụ f · Xanh: ground · Cam: mixed · 10 seed</text>';
  for (const [name,r] of curves) {
    const points = r.history.map(h => `${35+830*(h.evaluations+r.search.preparation_evaluations)/xmax},${210-160*(h.objective-lo)/range}`).join(' ');
    svg += `<polyline fill="none" opacity=".65" stroke="${name.includes('MIXED') ? '#e9ac64' : '#4ab8c5'}" stroke-width="2" points="${points}"/>`;
  }
  $('convergence').innerHTML = svg+`<text x="25" y="243" fill="#dce7f3">f ${n(lo)}–${n(hi)} · Lượt đánh giá gồm chuẩn bị: 0–${xmax}</text></svg>`;
  plan();
}
async function poll() {
  try {
    const state = await api('status'), running = state.status === 'running';
    for (const id of ['load','run','case','population','generations','budget','lambda','power']) $(id).disabled = running;
    $('status').textContent = running ? 'Đang chạy 10 seed và kiểm tra DBSCAN/complexity…' : state.error || `Trạng thái: ${state.status}`;
    if (state.has_result && (!result || lastStatus === 'running' && state.status === 'done')) {
      result = await api('results'); render();
    }
    const r = state.replay;
    $('replay-status').textContent = r.active ? `${r.method} · phút ${n(r.time_min)} · occupancy ${r.occupancy} · hoàn tất ${r.completed}/${r.total} · ${r.running ? 'đang chạy' : 'tạm dừng'}` : 'Chưa nạp replay. Nút replay thay traffic của phiên mock hiện tại.';
    lastStatus = state.status;
  } catch(e) { $('status').textContent = 'Lỗi: '+e.message; }
}
$('run').onclick = async () => {
  try { await api('run', {case:$('case').value, population:Number($('population').value),
    generations:Number($('generations').value), max_evaluations:Number($('budget').value),
    penalty_lambda:Number($('lambda').value), penalty_power:Number($('power').value)});
    lastStatus = 'running'; await poll();
  } catch(e) { $('status').textContent = 'Lỗi: '+e.message; }
};
$('method').onchange = plan;
$('load').onclick = async () => {
  try { await api('load',{case:$('case').value}); result = await api('results'); render(); await poll(); }
  catch(e) { $('status').textContent = 'Lỗi: '+e.message; }
};
$('replay').onclick = async () => { try { await api('replay',{method:$('method').value}); await poll(); } catch(e) { $('status').textContent = e.message; } };
$('pause').onclick = async () => { await fetch('/api/atfm/pause',{method:'POST'}); await poll(); };
poll(); setInterval(poll,2000);
