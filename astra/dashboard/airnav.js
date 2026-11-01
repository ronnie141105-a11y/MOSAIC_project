'use strict';
(() => {
  const $ = id => document.getElementById(id);
  let report, selected = 0, time = 0, playing = false, previousTick;
  const colors = ['#50d6cd', '#ffd17a', '#95acff', '#ed91bd'];
  const fmt = (value, digits = 1) => value == null ? 'Unavailable' : Number(value).toFixed(digits);
  const currentCase = () => report.cases[selected];
  async function api(url, options) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
    return data;
  }
  function error(message) { $('error').textContent = message; $('error').hidden = !message; }
  function cell(row, text) { const td = document.createElement('td'); td.textContent = text; row.append(td); }
  function rowInto(id, values) { const tr = document.createElement('tr'); values.forEach(v => cell(tr, v)); $(id).append(tr); }
  function sizedCanvas(id) {
    const canvas = $(id), ratio = window.devicePixelRatio || 1, box = canvas.getBoundingClientRect();
    canvas.width = box.width * ratio; canvas.height = box.height * ratio;
    const ctx = canvas.getContext('2d'); ctx.scale(ratio, ratio);
    return {ctx, width: box.width, height: box.height};
  }
  function frame() {
    const frames = currentCase().frames;
    let low = 0, high = frames.length;
    while (low < high) { const middle = (low + high) >> 1; if (frames[middle].time_s <= time) low = middle + 1; else high = middle; }
    return frames[Math.max(0, low - 1)];
  }
  function drawMap(active) {
    const {ctx, width, height} = sizedCanvas('track-map');
    const s = report.study, cos = Math.cos(s.center_lat * Math.PI / 180), radius = 65;
    const scale = Math.min(width - 80, height - 64) / (2 * radius);
    const xy = p => [width / 2 + (p.lon - s.center_lon) * 60 * cos * scale, height / 2 - (p.lat - s.center_lat) * 60 * scale];
    ctx.strokeStyle = '#203649'; ctx.lineWidth = 1;
    for (let n = -60; n <= 60; n += 20) { ctx.beginPath(); ctx.moveTo(width / 2 + n * scale, 26); ctx.lineTo(width / 2 + n * scale, height - 25); ctx.stroke(); ctx.beginPath(); ctx.moveTo(28, height / 2 + n * scale); ctx.lineTo(width - 28, height / 2 + n * scale); ctx.stroke(); }
    ctx.setLineDash([5, 5]); ctx.strokeStyle = '#587086'; ctx.beginPath(); ctx.arc(width / 2, height / 2, 40 * scale, 0, 2 * Math.PI); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = '#b3c5d5'; ctx.font = '12px Arial'; ctx.fillText('VVTS · RWY ' + (report.flight.landingRunway || 'unknown'), width / 2 + 10, height / 2 + 14);
    ctx.fillRect(width / 2 - 4, height / 2 - 3, 8, 6);
    report.observed_points.forEach((point, index, points) => {
      if (!index) return;
      const previous = points[index - 1], gap = point.time_s - previous.time_s > report.source.policy.max_position_age_s || !point.usable || !previous.usable;
      ctx.strokeStyle = gap ? '#72879b' : '#50d6cd'; ctx.setLineDash(gap ? [3, 5] : []); ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(...xy(previous)); ctx.lineTo(...xy(point)); ctx.stroke();
    });
    ctx.setLineDash([]);
    const labels = [];
    active.aircraft.forEach((ac, index) => {
      const [x, y] = xy(ac), color = colors[index % colors.length];
      ctx.save(); ctx.translate(x, y); ctx.rotate(ac.heading_deg * Math.PI / 180); ctx.fillStyle = color;
      ctx.beginPath(); ctx.moveTo(0, -9); ctx.lineTo(6, 6); ctx.lineTo(0, 3); ctx.lineTo(-6, 6); ctx.closePath(); ctx.fill(); ctx.restore();
      ctx.fillStyle = color; ctx.font = '11px Arial';
      const labelWidth = ctx.measureText(ac.callsign).width, labelX = Math.min(x + 10, width - labelWidth - 8);
      let labelY = y - 7;
      while (labels.some(p => labelX < p.x + p.width + 4 && labelX + labelWidth + 4 > p.x && Math.abs(labelY - p.y) < 15)) labelY += 16;
      if (labelY !== y - 7) { ctx.strokeStyle = color; ctx.lineWidth = .6; ctx.beginPath(); ctx.moveTo(x + 6, y); ctx.lineTo(labelX - 2, labelY - 4); ctx.stroke(); }
      ctx.fillText(ac.callsign, labelX, labelY); labels.push({x: labelX, y: labelY, width: labelWidth});
    });
    ctx.fillStyle = '#a3b5c7'; ctx.font = '11px Arial'; ctx.fillText('N ↑ · local distance view (NM)', 15, 20);
  }
  function drawChart() {
    const {ctx, width, height} = sizedCanvas('complexity-chart'), frames = currentCase().frames;
    const end = frames.at(-1).time_s || 1, x = t => 40 + t / end * (width - 55), y = v => height - 25 - v / 100 * (height - 45);
    ctx.font = '10px Arial'; ctx.fillStyle = '#a3b5c7';
    [0, 50, 100].forEach(v => { ctx.fillText(String(v), 7, y(v) + 3); ctx.strokeStyle = '#293c4e'; ctx.beginPath(); ctx.moveTo(35, y(v)); ctx.lineTo(width - 10, y(v)); ctx.stroke(); });
    ['observed_complexity', 'predicted_complexity'].forEach((key, index) => {
      ctx.strokeStyle = index ? '#ffd17a' : '#50d6cd'; ctx.setLineDash(index ? [5, 4] : []); ctx.lineWidth = 1.5; ctx.beginPath();
      frames.forEach((f, i) => i ? ctx.lineTo(x(f.time_s), y(f[key])) : ctx.moveTo(x(f.time_s), y(f[key]))); ctx.stroke();
    });
    ctx.setLineDash([]); ctx.strokeStyle = '#edf3fa'; ctx.beginPath(); ctx.moveTo(x(time), 12); ctx.lineTo(x(time), height - 25); ctx.stroke();
    ctx.fillText('0 min', 40, height - 7); ctx.fillText(fmt(end / 60) + ' min', width - 65, height - 7);
  }
  function renderFrame() {
    if (!report) return;
    const active = frame(); $('timeline').value = time;
    const date = new Date(Date.parse(report.study.start_utc) + time * 1000);
    $('clock').textContent = date.toLocaleTimeString('en-GB', {timeZone: 'Asia/Ho_Chi_Minh', hour12: false}) + ' ICT';
    $('case-kind').textContent = currentCase().kind === 'observed' ? 'Recorded flight; gaps and recovered fields remain visible.' : 'Hypothetical copies of VN243; no other observed flights.';
    const frameTime = new Date(Date.parse(report.study.start_utc) + active.time_s * 1000).toLocaleTimeString('en-GB', {timeZone: 'Asia/Ho_Chi_Minh', hour12: false});
    $('frame-info').textContent = `Frame ${frameTime} ICT · ${active.assessed_aircraft} aircraft inside the assessment volume · complexity ${fmt(active.observed_complexity)} · ${active.conflict_pairs} pairs below study thresholds`;
    $('aircraft-list').replaceChildren();
    if (!active.aircraft.length) $('aircraft-list').textContent = 'No usable observation at this time. Recording gaps are retained.';
    active.aircraft.forEach(ac => {
      const provenance = active.provenance[ac.callsign], p = document.createElement('p');
      const recovered = Object.entries(provenance.field_sources).filter(([, kind]) => kind !== 'reported').map(([field, kind]) => `${field}: ${kind}`);
      p.textContent = `${ac.callsign} · ${fmt(ac.altitude_ft, 0)} ft · ${fmt(ac.ground_speed_kt, 0)} kt · ${provenance.position_kind}, source age ${fmt(provenance.source_age_s)} s${recovered.length ? ' · ' + recovered.join(', ') : ''}`;
      $('aircraft-list').append(p);
    });
    drawMap(active); drawChart();
  }
  function display(data) {
    report = data; selected = 0; time = 0; playing = false; $('play').textContent = 'Play';
    $('results').hidden = false; $('flight-label').textContent = `${data.flight.flightNumberIata || data.study.source_callsign} · ${data.flight.aircraftRegistration}`;
    const localDate = new Date(data.study.start_utc).toLocaleDateString('en-GB', {timeZone: 'Asia/Ho_Chi_Minh', day: 'numeric', month: 'short', year: 'numeric'});
    $('recording-label').textContent = `${data.flight.depAirportIcao} → VVTS · ${localDate}`; $('raw-count').textContent = data.source.raw_positions;
    $('source-hash').textContent = data.source.source_sha256;
    $('case-select').replaceChildren(); data.cases.forEach((c, i) => { const option = document.createElement('option'); option.value = i; option.textContent = c.label; $('case-select').append(option); });
    $('quality').replaceChildren(); const quality = data.source.quality;
    Object.entries({'Usable airborne records': quality.usable_airborne || 0, 'Incomplete records excluded': quality.excluded_incomplete || 0, 'Ground records excluded': quality.excluded_ground || 0, 'Carried fields': quality.carried_fields || 0, 'Derived fields': quality.derived_fields || 0, 'Position expiry': data.source.policy.max_position_age_s + ' s'}).forEach(([name, value]) => { const dt = document.createElement('dt'), dd = document.createElement('dd'); dt.textContent = name; dd.textContent = value; $('quality').append(dt, dd); });
    $('quality-note').textContent = `${data.observed_points.length} source observations in the 60 NM arrival window. Null fields are recovered from the past within ${data.source.policy.max_field_age_s} seconds or excluded.`;
    const context = data.airport_context, runwayUse = values => Object.entries(values || {}).map(([runway, percent]) => `${runway} ${percent}%`).join(', ');
    $('context').textContent = context ? `Airport View landing use: ${runwayUse(context.observed_landing_runway_percentages)}. Takeoff use: ${runwayUse(context.observed_takeoff_runway_percentages)}. Snapshot captured separately on ${context.observed_local_date}.` : 'No separately captured airport context is available.';
    $('case-rows').replaceChildren(); data.cases.forEach(c => { const s = c.summary; rowInto('case-rows', [c.label, c.kind === 'observed' ? 'Recorded' : 'Hypothetical', s.peak_aircraft, fmt(s.peak_complexity), `${fmt(s.conflict_pair_exposure_s)} / ${fmt(s.evaluated_pair_time_s)}`, s.min_horizontal_nm == null ? 'No eligible pair' : fmt(s.min_horizontal_nm, 2) + ' NM', s.frames_with_manual_intervention, s.frames_with_candidates]); });
    $('threshold-note').textContent = `Assessment: ${data.study.assessment_radius_nm} NM, ${fmt(data.study.assessment_lower_ft, 0)}–${fmt(data.study.assessment_upper_ft, 0)} ft. Pair thresholds: ${data.study.horizontal_threshold_nm} NM / ${data.study.vertical_threshold_ft} ft, research assumptions. *Minimum distance considers only pairs below the vertical threshold. Exposure is pair-seconds; coverage is seconds with at least two eligible aircraft.`;
    $('forecast-rows').replaceChildren(); data.forecast_summary.forEach(r => rowInto('forecast-rows', [r.horizon_s + ' s', r.count, fmt(r.mean_horizontal_nm, 3) + (r.count ? ' NM' : ''), fmt(r.p95_horizontal_nm, 3) + (r.count ? ' NM' : ''), fmt(r.mean_altitude_ft, 0) + (r.count ? ' ft' : '')]));
    $('limitations').replaceChildren(); data.limitations.forEach(text => { const li = document.createElement('li'); li.textContent = text; $('limitations').append(li); });
    $('timeline').max = currentCase().frames.at(-1).time_s; renderFrame();
  }
  async function refreshStatus() {
    try {
      const status = await api('/api/airnav/status'); $('run-study').disabled = status.status === 'running' || !status.data_available;
      $('job-status').textContent = status.status === 'running' ? 'Running the three cases…' : status.status === 'done' ? 'Results ready · offline recording' : status.status === 'failed' ? 'Study failed' : status.data_available ? 'Saved recording ready · no API credits required' : 'Saved recording unavailable';
      if (status.error) error(status.error);
      if (status.status === 'done' && !report) display(await api('/api/airnav/results'));
      if (status.status === 'running') setTimeout(refreshStatus, 1000);
    } catch (exc) { error(exc.message); $('job-status').textContent = 'Unable to load study status'; $('run-study').disabled = false; }
  }
  $('run-study').addEventListener('click', async () => { error(''); $('run-study').disabled = true; playing = false; report = undefined; $('results').hidden = true; try { await api('/api/airnav/run', {method: 'POST'}); refreshStatus(); } catch (exc) { error(exc.message); $('run-study').disabled = false; } });
  $('case-select').addEventListener('change', () => { selected = Number($('case-select').value); time = 0; playing = false; $('play').textContent = 'Play'; $('timeline').max = currentCase().frames.at(-1).time_s; renderFrame(); });
  $('play').addEventListener('click', () => { playing = !playing; if (playing && time >= Number($('timeline').max)) time = 0; $('play').textContent = playing ? 'Pause' : 'Play'; });
  $('timeline').addEventListener('input', () => { time = Number($('timeline').value); renderFrame(); });
  window.addEventListener('resize', renderFrame);
  function tick(now) { if (previousTick && playing && report) { time = Math.min(Number($('timeline').max), time + (now - previousTick) / 1000 * Number($('play-speed').value)); if (time >= Number($('timeline').max)) { playing = false; $('play').textContent = 'Play'; } renderFrame(); } previousTick = now; requestAnimationFrame(tick); }
  refreshStatus(); requestAnimationFrame(tick);
})();
