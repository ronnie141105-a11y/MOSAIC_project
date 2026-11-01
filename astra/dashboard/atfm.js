const $ = id => document.getElementById(id);
let result = null, lastStatus = null;
async function api(path, body) {
  const response = await fetch('/api/atfm/' + path, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}
function error(e) {
  $('status').textContent = 'Lỗi: ' + e.message;
  $('status').className = 'error';
}
const n = value => Number.isFinite(value) ? value.toFixed(2) : '—';
const mean = values => values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : NaN;
function row(table, values) {
  const tr = document.createElement('tr');
  for (const value of values) {
    const td = document.createElement('td');
    td.textContent = value;
    tr.append(td);
  }
  table.append(tr);
}
function modeControls() {
  const uncertain = $('mode').value === 'uncertainty';
  $('uncertainty-controls').hidden = !uncertain;
  $('mode-description').textContent = uncertain
    ? 'Chạy 5 seeds cho GA danh định và GA bất định. Hai nhánh kế thừa cùng phương án ground-only, cùng giới hạn số lần mô phỏng tính cả tìm phương án xuất phát. GA bất định tối ưu mean/worst trên training; so sánh cuối cùng dùng bộ test giữ riêng. Một đánh giá cá thể bất định cần mô phỏng mọi mẫu training.'
    : 'Chạy 5 seeds. GA ground tạo phương án xuất phát; ground tiếp tục và mixed cùng kế thừa phương án đó, với cùng giới hạn tổng lượt đánh giá gồm bước chuẩn bị. Kết quả hiển thị số lượt thực dùng và thời gian tìm kiếm.';
}
function tableFlight() {
  if (!result) return;
  const run = result.runs[$('method').value];
  $('flights').replaceChildren();
  if (!run) return;
  for (const flight of run.flights || []) {
    row($('flights'), [flight.id, ...[
      'ground_delay_min', 'speed_delay_min', 'upstream_ground_speed_kt',
      'entry_min', 'airborne_delay_min'
    ].map(key => n(flight[key]))]);
  }
}
function uncertaintySummary() {
  const uncertain = !!result.uncertainty;
  $('uncertainty-results').hidden = !uncertain;
  $('nominal-heading').textContent = (uncertain ? '3' : '2') + ' · Kết quả danh định';
  $('replay-heading').textContent = (uncertain ? '4' : '3') + ' · Phát lại trên simulator MOSAIC';
  for (const split of ['test', 'training']) $('uncertainty-' + split).replaceChildren();
  if (!uncertain) return;
  const config = result.uncertainty;
  $('uncertainty-settings').textContent =
    `ETA ±${n(config.eta_jitter_min)} phút; capacity giảm tối đa ${config.capacity_drop} flights / 15 phút; risk weight ${n(config.risk_weight)}. Training: ${config.training_count} mẫu, gồm danh định. Test: ${config.test_count} mẫu giữ riêng. Ngân sách: ${result.settings?.max_evaluations ?? '—'} lần mô phỏng / nhánh / seed, gồm bước chuẩn bị.`;
  const summaries = result.uncertainty_summary || [];
  for (const summary of summaries) {
    if (!['training', 'test'].includes(summary.split)) continue;
    row($('uncertainty-' + summary.split), [
      summary.method, summary.count, ...[
        'mean_objective', 'worst_objective', 'risk_objective', 'mean_total_delay_min',
        'mean_airborne_holding_min', 'mean_airborne_extra_min'
      ].map(key => n(summary[key]))
    ]);
  }
  const test = summaries.filter(summary => summary.split === 'test');
  const describe = prefix => {
    const rows = test.filter(summary => summary.method.startsWith(prefix));
    return `mean objective ${n(mean(rows.map(s => s.mean_objective)))}, worst objective trung bình theo seed ${n(mean(rows.map(s => s.worst_objective)))}, tổng delay ${n(mean(rows.map(s => s.mean_total_delay_min)))} phút`;
  };
  $('uncertainty-assessment').textContent =
    'Trung bình trên các seed GA với cùng bộ test: GA danh định — ' + describe('GA_DETERMINISTIC_') +
    '; GA bất định — ' + describe('GA_UNCERTAINTY_') +
    '. Đây là so sánh có ghép cặp trên cùng mẫu bất định; đọc thêm holding và airborne extra để xác định đánh đổi.';
}
function demandChart() {
  const s = result.scenario || {};
  const counts = s.demand_counts_15min || [], caps = s.entry_capacity_15min || [];
  if (!counts.length) { $('chart').replaceChildren(); return; }
  const ymax = Math.max(1, ...counts, ...caps);
  const width = 830 / counts.length;
  let svg = '<svg viewBox="0 0 900 250" role="img" aria-label="Demand và entry capacity danh định"><text x="25" y="22" fill="#dce7f3">Danh định · Xanh: demand · Cam: capacity · flights / 15 phút</text>';
  counts.forEach((d, i) => {
    const x = 40 + i * width, c = caps[i] || 0, unit = 165 / ymax;
    svg += `<rect x="${x}" y="${210-d*unit}" width="${width*.3}" height="${d*unit}" fill="#4ab8c5"/><rect x="${x+width*.32}" y="${210-c*unit}" width="${width*.23}" height="${c*unit}" fill="#e9ac64"/><text x="${x}" y="${200-d*unit}" fill="#dce7f3">${d}</text><text x="${x}" y="237" fill="#dce7f3">${i*15}–${i*15+15}</text>`;
  });
  $('chart').innerHTML = svg + '</svg>';
}
function convergenceChart(curves, title, uncertaintyGroup) {
  if (!curves.length) return '';
  const costAxis = curves.every(([, r]) => r.search && r.history.every(h => Number.isFinite(h.evaluations)));
  const xValue = (r, h) => costAxis ? h.evaluations + (r.search.preparation_evaluations || 0) : h.generation;
  const xmax = Math.max(1, ...curves.flatMap(([, r]) => r.history.map(h => xValue(r, h))));
  const values = curves.flatMap(([, r]) => r.history.map(h => h.objective));
  const lo = Math.min(...values), hi = Math.max(...values), range = Math.max(1, hi-lo);
  let chart = `<svg viewBox="0 0 900 250" role="img" aria-label="${title}"><text x="25" y="22" fill="#dce7f3">${title}</text>`;
  for (const [name, r] of curves) {
    const points = r.history.map(h => `${35+830*xValue(r,h)/xmax},${210-160*(h.objective-lo)/range}`).join(' ');
    const color = uncertaintyGroup || name.includes('MIXED') ? '#e9ac64' : '#4ab8c5';
    chart += `<polyline fill="none" opacity=".7" stroke="${color}" stroke-width="2" points="${points}"/>`;
  }
  const axis = costAxis ? (result.uncertainty ? 'Lần mô phỏng, gồm chuẩn bị' : 'Lượt đánh giá, gồm chuẩn bị') : 'Generation';
  return chart + `<text x="25" y="243" fill="#dce7f3">Objective ${n(lo)}–${n(hi)} · ${axis} 0–${xmax}</text></svg>`;
}
function supplemental(runs) {
  const stress = result.stress || [], sensitivity = result.sensitivity || [];
  const uncertain = !!result.uncertainty;
  $('stress-details').hidden = !stress.length && !sensitivity.length;
  $('stress-summary').textContent = uncertain ? 'Chi tiết test · ETA và capacity thay đổi đồng thời' : 'ETA stress test và weight sensitivity';
  $('stress-description').textContent = uncertain
    ? 'Các plans được giữ nguyên, đánh giá trên cùng các mẫu test. Bộ test không tham gia fitness hoặc chọn cá thể.'
    : 'Giữ nguyên các plans, thay ETA ±2 phút trên 3 seeds; không re-optimize. Re-score speed weight 1/2/4 chỉ kiểm tra cách đánh giá thay đổi.';
  let text = (uncertain ? 'Test ETA/capacity' : 'ETA stress') + ': objective trung bình theo method\n';
  for (const [name] of runs) {
    const rows = stress.filter(s => s.method === name);
    if (rows.length) text += name + ': ' + n(mean(rows.map(s => s.objective))) + '\n';
  }
  if (sensitivity.length) {
    text += '\nSpeed weight re-score: trung bình theo nhóm\n';
    const prefixes = ['GA_GROUND', 'GA_CONTINUED_GROUND', 'GA_MIXED'].filter(prefix => runs.some(([name]) => name.startsWith(prefix)));
    text += 'Weight / ' + prefixes.join(' / ') + '\n';
    for (const w of [1, 2, 4]) {
      text += [w, ...prefixes.map(prefix => n(mean(sensitivity.filter(s => s.speed_weight === w && s.method.startsWith(prefix)).map(s => s.rescored_objective))))].join(' / ') + '\n';
    }
  }
  $('stress').textContent = text;
}
function render() {
  const runs = Object.entries(result.runs || {});
  const previousMethod = $('method').value;
  $('metrics').replaceChildren(); $('method').replaceChildren();
  for (const [name, run] of runs) {
    row($('metrics'), [name, ...[
      'ground_delay_min', 'speed_delay_min', 'airborne_holding_min',
      'total_delay_min', 'max_delay_min', 'objective'
    ].map(key => n(run.metrics[key])), run.search?.total_evaluations ?? '—', n(run.search?.total_elapsed_s)]);
    const option = document.createElement('option');
    option.value = name; option.textContent = name; $('method').append(option);
  }
  // Preserve an explicit user choice. Never choose a replay by held-out scores.
  if (result.runs[previousMethod]) $('method').value = previousMethod;
  const uncertain = !!result.uncertainty;
  $('nominal-description').textContent = uncertain
    ? 'Bảng dưới đây mô phỏng mọi plan trên cùng kịch bản danh định để đọc chi tiết và phát lại. Đánh giá bất định nằm ở bảng training/test phía trên; không suy ra độ ổn định từ objective danh định. Ngân sách tìm kiếm đếm cả mô phỏng training và chuẩn bị; chi phí báo cáo sau tìm kiếm được lưu riêng trong cấu hình xuất.'
    : 'KPI trên kịch bản danh định. So sánh ground tiếp tục và mixed theo cùng giới hạn lượt đánh giá tính cả tìm phương án ground xuất phát.';
  const objectives = prefix => mean(runs.filter(([name]) => name.startsWith(prefix)).map(([, run]) => run.metrics.objective));
  $('assessment').textContent = uncertain
    ? `Objective danh định trung bình: GA danh định ${n(objectives('GA_DETERMINISTIC_'))}; GA bất định ${n(objectives('GA_UNCERTAINTY_'))}. Giá trị này riêng với mean/worst trên test.`
    : `Objective trung bình: GA ground ban đầu ${n(objectives('GA_GROUND'))}; ${runs.some(([name]) => name.startsWith('GA_CONTINUED_GROUND')) ? 'ground tiếp tục ' + n(objectives('GA_CONTINUED_GROUND')) + '; ' : ''}GA mixed ${n(objectives('GA_MIXED'))}. So sánh cả tổng delay, maximum delay và ETA stress; chưa kết luận hiệu quả khai thác thực tế.`;
  uncertaintySummary(); demandChart();
  const curves = runs.filter(([, r]) => (r.history || []).length);
  $('convergence').innerHTML = uncertain
    ? convergenceChart(curves.filter(([name]) => name.startsWith('GA_DETERMINISTIC_')), 'GA danh định · objective danh định · 5 seeds', false) +
      convergenceChart(curves.filter(([name]) => name.startsWith('GA_UNCERTAINTY_')), 'GA bất định · training risk objective · 5 seeds', true)
    : convergenceChart(curves, 'Convergence · Xanh: ground · Cam: mixed · 5 seeds / measure set', false);
  supplemental(runs); tableFlight();
}
async function poll() {
  try {
    const state = await api('status');
    const running = state.status === 'running';
    for (const id of ['run', 'mode', 'population', 'generations', 'max-evaluations', 'risk-weight', 'eta-jitter', 'capacity-drop']) $(id).disabled = running;
    $('status').className = state.error ? 'error' : '';
    $('status').textContent = running
      ? (state.mode === 'uncertainty' ? 'GA đang tối ưu trên training và đánh giá riêng trên test · 5 seeds…' : 'GA đang chạy 5 seeds cho mỗi measure set…')
      : state.error || `Trạng thái: ${state.status}`;
    const replay = state.replay;
    $('replaystatus').textContent = replay.active
      ? `Replay danh định · ${replay.method} · phút ${n(replay.time_min)} · trong vùng ${replay.occupancy} · chờ upstream ${replay.upstream_holding} · hoàn tất ${replay.completed}/${replay.total} · ${replay.running ? 'đang chạy' : 'tạm dừng'}`
      : 'Chưa nạp replay.';
    if (state.has_result && (!result || (lastStatus === 'running' && state.status === 'done'))) {
      result = await api('results'); render();
      if (replay.method && result.runs[replay.method]) { $('method').value = replay.method; tableFlight(); }
    }
    lastStatus = state.status;
  } catch (e) { error(e); }
}
$('run').onclick = async () => {
  try {
    const body = {
      mode: $('mode').value, population: Number($('population').value),
      generations: Number($('generations').value), max_evaluations: Number($('max-evaluations').value)
    };
    if (body.mode === 'uncertainty') Object.assign(body, {
      risk_weight: Number($('risk-weight').value), eta_jitter_min: Number($('eta-jitter').value),
      capacity_drop: Number($('capacity-drop').value)
    });
    await api('run', body); lastStatus = 'running'; await poll();
  } catch (e) { error(e); }
};
$('replay').onclick = async () => { try { await api('replay', {method: $('method').value}); await poll(); } catch (e) { error(e); } };
$('pause').onclick = async () => { try { await api('pause', {}); await poll(); } catch (e) { error(e); } };
$('method').onchange = tableFlight;
$('mode').onchange = modeControls;
modeControls(); poll(); setInterval(poll, 2000);
