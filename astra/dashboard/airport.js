/* AEON-style airport monitor. The server remains authoritative for routing. */
(() => {
  'use strict';
  if(window.self!==window.top)document.body.classList.add('embedded-control-view');
  const SVG = 'http://www.w3.org/2000/svg';
  const INITIAL_VIEW = {x: 0, y: 0, width: 1820, height: 965};
  const map = document.getElementById('airport-map');
  const viewport = document.getElementById('map-viewport');
  const world = document.getElementById('world');
  const towerView = window.MosaicTowerView;
  const motion = new towerView.Motion();
  const markers = new Map();
  const layer = {
    taxi: document.getElementById('taxiway-lines'),
    key: document.getElementById('key-points'),
    routes: document.getElementById('route-lines'),
    aircraft: document.getElementById('aircraft-layer'),
    drag: document.getElementById('drag-layer')
  };
  let view = {...INITIAL_VIEW};
  let rotation = 0;
  let autoFit = true;
  let layout = null;
  let nodes = new Map();
  let state = null;
  let selected = '';
  let gesture = null;
  let fetching = false;
  let presets = [];
  let split = null;

  function splitMode() { return ['split','full'].includes(document.getElementById('tower-layout').value); }
  function splitOptions() {
    return {taxiways:document.getElementById('show-taxiways').checked,
      routes:document.getElementById('show-routes').checked,
      labels:document.getElementById('show-labels').checked,readOnly:!!state?.replay_read_only};
  }
  function setLayout() {
    viewport.classList.toggle('split-mode',splitMode());
    document.querySelector('.map-toolbar').classList.toggle('split-toolbar',splitMode());
    document.getElementById('fit-view').textContent = 'Fit maps';
    if(splitMode())split?.setLayout(document.getElementById('tower-layout').value);else fitView();
    if(state&&layout)render();
  }

  function svg(tag, attrs = {}) {
    const e = document.createElementNS(SVG, tag);
    for (const [key, value] of Object.entries(attrs)) e.setAttribute(key, String(value));
    return e;
  }
  function addText(parent, tag, attrs, content) {
    const e = svg(tag, attrs);
    e.textContent = content;
    parent.append(e);
    return e;
  }
  function message(value, error = false) {
    document.getElementById('map-message').textContent = value;
    document.getElementById('error').textContent = error ? value : '';
  }
  async function api(url, data) {
    const response = await fetch(url, data === undefined ? undefined : {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || 'Request failed.');
    return result;
  }
  function setView(next) {
    view = next;
    map.setAttribute('viewBox', `${view.x} ${view.y} ${view.width} ${view.height}`);
    updateGlyphs();
  }
  function pointerPoint(event, target) {
    const point = map.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    return point.matrixTransform(target.getScreenCTM().inverse());
  }
  function mapPoint(event) { return pointerPoint(event, world); }
  function viewPoint(event) { return pointerPoint(event, map); }
  function desiredRotation() {
    return towerView.orientation(document.getElementById('map-orientation').value,
      viewport.clientWidth, viewport.clientHeight);
  }
  function fitView() {
    autoFit = true;
    rotation = desiredRotation();
    world.setAttribute('transform', `rotate(${rotation} 910 482.5)`);
    viewport.dataset.orientation = rotation ? 'vertical' : 'horizontal';
    setView(towerView.fitBounds(rotation));
  }
  function zoom(factor, point = {x:view.x+view.width/2, y:view.y+view.height/2}) {
    autoFit = false;
    const width = Math.max(180, Math.min(4500, view.width / factor));
    const height = width * view.height / view.width;
    const fx = (point.x-view.x)/view.width, fy = (point.y-view.y)/view.height;
    setView({x:point.x-fx*width, y:point.y-fy*height, width, height});
  }
  function updateGlyphs() {
    const matrix = world.getScreenCTM();
    if (!matrix) return;
    const scale = Math.hypot(matrix.a, matrix.b);
    if (!scale) return;
    const bounds = viewport.getBoundingClientRect();
    for (const {group, marker, tag, width} of markers.values()) {
      marker.setAttribute('transform', `scale(${.6/scale})`);
      if (!tag) continue;
      const point = map.createSVGPoint();
      const position = group.transform.baseVal.getItem(0).matrix;
      point.x = position.e; point.y = position.f;
      const screen = point.matrixTransform(matrix);
      const x = screen.x+width+12>bounds.right-6 ? -width-12 : 12;
      const y = Math.max(bounds.top+6-screen.y, Math.min(-24, bounds.bottom-54-screen.y));
      tag.setAttribute('transform', `rotate(${-rotation}) scale(${1/scale}) translate(${x} ${y})`);
    }
    layer.key.querySelectorAll('.key-label').forEach(label=>{
      label.setAttribute('transform', `rotate(${-rotation} ${label.getAttribute('x')} ${label.getAttribute('y')})`);
      label.style.fontSize = `${11/scale}px`;
    });
  }
  function drawLayout() {
    layer.taxi.replaceChildren();
    layer.key.replaceChildren();
    for (const path of layout.paths) {
      const points = path.ids.map(id => nodes.get(id)).filter(Boolean);
      if (points.length < 2) continue;
      const line = svg('polyline', {
        points: points.map(p => `${p.x},${p.y}`).join(' '),
        class: path.type === 'runway' ? 'runway-line' : 'taxiway-line'
      });
      layer.taxi.append(line);
    }
    for (const [id, label] of [['n107', 'HLD-S1'], ['n113', 'HLD-P5'],
                                ['n123', '25L ENTRY'], ['n125', '25R']]) {
      const n = nodes.get(id);
      if (!n) continue;
      layer.key.append(svg('polygon', {
        points: `${n.x},${n.y-8} ${n.x+8},${n.y} ${n.x},${n.y+8} ${n.x-8},${n.y}`,
        class: 'key-marker', fill: label.startsWith('HLD') ? '#9e4d8e' : '#3a83b4'
      }));
      addText(layer.key, 'text', {x: n.x + 12, y: n.y + 5, class: 'key-label'}, label);
    }
    document.getElementById('show-taxiways').onchange = toggleLayers;
    document.getElementById('show-routes').onchange = toggleLayers;
    document.getElementById('show-labels').onchange = render;
    toggleLayers();
  }
  function toggleLayers() {
    layer.taxi.style.display = document.getElementById('show-taxiways').checked ? '' : 'none';
    layer.routes.style.display = document.getElementById('show-routes').checked ? '' : 'none';
    if(splitMode()&&split)split.render(motion.sample(performance.now()),selected,splitOptions());
  }
  function allAircraft(snapshot = state) {
    if (!snapshot) return [];
    const result = snapshot.aircraft.slice();
    for (const [callsign, a] of Object.entries(snapshot.tower_arrivals || snapshot.approaches || {})) {
      const reference=layout?.display_reference||window.MosaicTowerRadarGeometry.DEFAULT_REFERENCE;
      const position=Number.isFinite(a.lat)&&Number.isFinite(a.lon)
        ? window.MosaicTowerRadarGeometry.geoToWorld(a.lat,a.lon,reference)
        : {x:reference.anchor.x+a.distance_nm*1852/reference.metres_per_unit,y:reference.anchor.y};
      result.push({callsign,...position,heading_deg:a.heading_deg??reference.runway_bearing_deg,
        state: 'ILS APPROACH', operation: 'approach', route: [], seg_idx: 0,
        altitude_ft: a.altitude_ft, distance_nm: a.distance_nm,
        speed_kt: a.speed_kt, vertical_speed_fpm: a.vertical_speed_fpm,
        fpl: snapshot.fpl[callsign], metrics: {}});
    }
    return result;
  }
  function phaseClass(a) {
    if (a.state === 'HOLDING') return 'holding';
    if (a.state === 'ARRIVED' || a.state === 'DEPARTED') return 'done';
    return a.operation;
  }
  function altitudeLabel(feet) {
    if (feet == null) return 'GROUND';
    return feet < 10000 ? `${Math.round(feet).toLocaleString()} ft` :
      `FL${String(Math.round(feet / 100)).padStart(3, '0')}`;
  }
  function speedLabel(knots) { return `${Math.round(knots || 0)} kt`; }
  function remainingPoints(a) {
    const points = [{x: a.x, y: a.y}];
    for (const id of (a.route || []).slice((a.seg_idx || 0) + 1)) {
      const n = nodes.get(id);
      if (n) points.push(n);
    }
    return points;
  }
  function renderRoutes(aircraft) {
    layer.routes.replaceChildren();
    for (const a of aircraft) {
      const points = remainingPoints(a);
      if (points.length < 2) continue;
      const highlighted = a.callsign === selected;
      layer.routes.append(svg('polyline', {
        points: points.map(p => `${p.x},${p.y}`).join(' '),
        class: highlighted ? 'route-selected' : 'route-muted'
      }));
      if (highlighted) {
        const end = points[points.length - 1];
        layer.routes.append(svg('circle', {cx: end.x, cy: end.y, r: 6, class: 'route-end'}));
      }
    }
  }
  function renderAircraft(aircraft) {
    layer.aircraft.replaceChildren();
    markers.clear();
    for (const a of aircraft) {
      const group = svg('g', {'class': 'aircraft-symbol', 'data-callsign': a.callsign,
        transform: `translate(${a.x} ${a.y})`, 'aria-label': `${a.callsign} · ${a.state} · ${a.fpl?.stand || ''}`});
      addText(group, 'title', {}, `${a.callsign} · ${a.state} · ${a.fpl?.stand || ''}`);
      const marker = svg('g');
      marker.append(svg('circle', {r: 21, fill: 'transparent'}));
      if (a.callsign === selected) marker.append(svg('circle', {r: 18, class: 'aircraft-halo'}));
      marker.append(svg('circle', {r: 13, class: `aircraft-circle ${phaseClass(a)}`}));
      const plane = svg('path', {
        d: 'M0,-10 L2,-3 L10,2 L10,5 L2,3 L2,8 L5,10 L5,12 L0,10 L-5,12 L-5,10 L-2,8 L-2,3 L-10,5 L-10,2 L-2,-3 Z',
        class: 'aircraft-plane'
      });
      marker.append(plane); group.append(marker);
      let tag = null, width = 0;
      const atStand = a.state === 'PARKED' || a.state === 'ARRIVED';
      const queuedBehind=a.state==='HOLDING'&&nodes.get(a.route?.[a.seg_idx])?.name!=='HLD-S1';
      if (document.getElementById('show-labels').checked && !atStand && !queuedBehind) {
        tag = svg('g', {class: 'aircraft-tag'});
        width = Math.max(90, a.callsign.length * 8 + 14);
        tag.append(svg('rect', {x: 0, y: 0, width, height: 48, rx: 4,
          class: `tag-plate ${phaseClass(a)}`}));
        addText(tag, 'text', {x: 7, y: 14, class: 'tag-name'}, a.callsign);
        addText(tag, 'text', {x: 7, y: 28, class: 'tag-data'}, altitudeLabel(a.altitude_ft));
        addText(tag, 'text', {x: 7, y: 42, class: 'tag-data'}, speedLabel(a.speed_kt));
        group.append(tag);
      }
      layer.aircraft.append(group);
      markers.set(a.callsign, {group, marker, plane, tag, width});
    }
    positionAircraft(aircraft);
  }
  function positionAircraft(aircraft) {
    for (const a of aircraft) {
      const record = markers.get(a.callsign); if (!record) continue;
      record.group.setAttribute('transform', `translate(${a.x} ${a.y})`);
      const route = remainingPoints(a);
      let angle = a.operation === 'approach' || a.state === 'CLIMBING' ? 270 : 0;
      if (route.length > 1) {
        const dx = route[1].x-a.x, dy = route[1].y-a.y;
        if (Math.hypot(dx,dy)>.5) angle = Math.atan2(dy,dx)*180/Math.PI+90;
      }
      record.plane.setAttribute('transform', `rotate(${angle})`);
    }
    updateGlyphs();
  }
  function renderSidebar(aircraft) {
    document.getElementById('traffic-count').textContent = String(aircraft.length);
    const list = document.getElementById('traffic-list');
    list.replaceChildren();
    if (!aircraft.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-traffic'; empty.textContent = 'No aircraft on the airport yet.';
      list.append(empty);
    }
    for (const a of aircraft) {
      const row = document.createElement('button');
      row.type = 'button'; row.className = `traffic-row${selected === a.callsign ? ' selected' : ''}`;
      const dot = document.createElement('span'); dot.className = `traffic-dot ${a.operation}`;
      const info = document.createElement('span');
      const name = document.createElement('strong'); name.textContent = a.callsign;
      const sub = document.createElement('small'); sub.textContent = `${a.fpl?.aircraft_type || ''} · ${a.fpl?.origin || '—'} → ${a.fpl?.destination || '—'}`;
      info.append(name, sub);
      const phase = document.createElement('span'); phase.className = 'traffic-state'; phase.textContent = a.state.replace('_', ' ');
      row.append(dot, info, phase);
      row.onclick = () => select(a.callsign);
      list.append(row);
    }
    const a = aircraft.find(item => item.callsign === selected);
    const f = a?.fpl;
    const flightPanel = document.getElementById('airport-flight-panel');
    flightPanel.hidden = !a;
    const panelContent = document.getElementById('flight-panel-content');
    panelContent.replaceChildren();
    if (a) {
      const title = document.createElement('div'); title.className = 'flight-panel-title'; title.textContent = a.callsign;
      const route = document.createElement('div'); route.className = 'flight-panel-route';
      route.textContent = `${f?.origin || '—'}  →  ${f?.destination || '—'} · ${f?.aircraft_type || 'Aircraft'}`;
      const grid = document.createElement('div'); grid.className = 'flight-panel-grid';
      const items = [
        ['Phase', a.state.replace('_', ' ')], ['Ground speed', speedLabel(a.speed_kt)],
        ['Altitude', altitudeLabel(a.altitude_ft)],
        ['Vertical speed', `${Math.round(a.vertical_speed_fpm || 0)} fpm`],
        ['Procedure', f?.sid || f?.star || '—'], ['Runway', f?.runway || '—'],
        ['Requested level', f?.requested_fl == null ? '—' : `FL${f.requested_fl}`],
        ['Stand', f?.stand || '—'],
        ['Filed route', f?.departure_route || f?.arrival_route || '—'],
        ['To threshold', a.distance_nm == null ? '—' : `${a.distance_nm.toFixed(1)} NM`]
      ];
      for (const [label, value] of items) {
        const cell = document.createElement('div');
        const small = document.createElement('small'); small.textContent = label;
        const strong = document.createElement('strong'); strong.textContent = value;
        cell.append(small, strong); grid.append(cell);
      }
      panelContent.append(title, route, grid);
    }
    document.getElementById('selected-name').textContent = a ? a.callsign : 'No aircraft selected';
    document.getElementById('selected-phase').textContent = a ? a.state.replace('_', ' ') : 'NONE';
    document.getElementById('selected-detail').textContent = a ?
      `${f?.aircraft_type || 'Aircraft'} · ${a.operation === 'dep' ? 'Departure' : 'Arrival'} · ${a.state === 'HOLDING' && !(a.route || []).length ? 'Route ended; restore planned route' : a.state.replace('_', ' ').toLowerCase()}` :
      'Choose a flight on the map or in the traffic list.';
    const facts = document.getElementById('selected-facts');
    facts.replaceChildren();
    if (a && f) {
      const items = [
        ['Flight', `${f.origin || '—'} → ${f.destination || '—'}`, true],
        ['Filed route', f.departure_route || f.arrival_route || '—', true],
        ['Procedure', f.sid || f.star || '—'],
        ['Runway', f.runway || '—'],
        ['Requested level', f.requested_fl == null ? '—' : `FL${String(f.requested_fl).padStart(3, '0')}`],
        ['Stand', f.stand || '—'],
      ];
      if (a.altitude_ft != null) items.push(['Current altitude', `${Math.round(a.altitude_ft).toLocaleString()} ft`]);
      if (a.distance_nm != null) items.push(['To threshold', `${a.distance_nm.toFixed(1)} NM`]);
      const planClock=t=>new Date((state.case_replay?.active?new Date(state.case_replay.playback_utc).getTime()-state.sim_time_s*1000:0)+t*1000).toISOString().slice(11,19)+' UTC';
      if (f.ctot_s != null) items.push(['CTOT', planClock(f.ctot_s)]);
      if (f.tobt_s != null) items.push(['TOBT', planClock(f.tobt_s)]);
      if (f.estimated_taxi_out_s != null) items.push(['Estimated taxi out', `${Math.round(f.estimated_taxi_out_s)} s`]);
      for (const [key, value, wide] of items) {
        const cell = document.createElement('div'); cell.className = `fact${wide ? ' wide' : ''}`;
        const caption = document.createElement('small'); caption.textContent = key;
        const content = document.createElement('strong'); content.textContent = value;
        cell.append(caption, content); facts.append(cell);
      }
    }
    document.getElementById('takeoff-clearance').disabled = !(a && a.operation === 'dep' && a.state === 'HOLDING' && (a.route || []).length);
    document.getElementById('crossing-clearance').disabled = !(a && a.operation === 'arr' && a.state === 'HOLDING' && (a.route || []).length);
    document.getElementById('restore-route').disabled = !!state.replay_read_only || !(a && a.operation !== 'approach' && a.state !== 'ARRIVED');
    const timeline = document.getElementById('selected-timeline');
    timeline.replaceChildren();
    const eventNames = {takeoff_clearance:'Takeoff cleared', crossing_clearance:'Crossing cleared',
      off_block:'Off-block', runway_entry:'Runway entry', takeoff:'Takeoff',
      tma_handoff:'TMA', sid_exit:'SID exit', approach_visible:'Approach', touchdown:'Touchdown',
      landing_two_thirds:'Passed 2/3 runway', takeoff_roll:'Takeoff roll', runway_exit:'Runway exit', crossing_entry:'25L crossing', crossing_exit:'Crossed 25L',
      stand_arrival:'At stand'};
    for (const [key, time] of Object.entries(state.milestones?.[selected] || {})) {
      const chip = document.createElement('span'); chip.className = 'event-chip';
      const name = document.createElement('b'); name.textContent = eventNames[key] || key;
      chip.append(name, ` · ${Math.round(time)} s`); timeline.append(chip);
    }
    renderMeasures();
  }
  function renderMeasures() {
    const box = document.getElementById('run-measures');
    box.replaceChildren();
    const flights = Object.entries(state?.fpl || {});
    if (!state?.study_key || !flights.length) {
      box.textContent = 'Load a scenario to see movement times.'; return;
    }
    const values = [
      ['Flights', flights.length],
      ['Takeoffs', Object.values(state.milestones || {}).filter(m => m.takeoff != null).length],
      ['Landings', Object.values(state.milestones || {}).filter(m => m.touchdown != null).length],
    ];
    const taxi = flights.map(([cs]) => {
      const m = state.milestones?.[cs] || {};
      return m.off_block != null && m.takeoff != null ? m.takeoff - m.off_block : null;
    }).filter(v => v != null);
    if (taxi.length) values.push(['Mean taxi-out', `${Math.round(taxi.reduce((a,b) => a+b, 0)/taxi.length)} s`]);
    const slot = flights.map(([cs, f]) => {
      const takeoff = state.milestones?.[cs]?.takeoff;
      return takeoff != null && f.ctot_s > 0 ? takeoff - f.ctot_s : null;
    }).filter(v => v != null);
    if (slot.length) values.push(['Mean CTOT delta', `${Math.round(slot.reduce((a,b) => a+b, 0)/slot.length)} s`]);
    const holds = state.aircraft.filter(a => a.operation === 'dep').map(a => a.metrics?.hold_s || 0);
    if (holds.length) values.push(['Departure hold', `${Math.round(holds.reduce((a,b) => a+b, 0))} s`]);
    for (const [name, value] of values) {
      const row = document.createElement('div'); row.className = 'measure-row';
      const label = document.createElement('span'); label.textContent = name;
      const number = document.createElement('strong'); number.textContent = value;
      row.append(label, number); box.append(row);
    }
  }
  function render() {
    if (!state || !layout) return;
    const aircraft = motion.sample(performance.now());
    if(splitMode()&&split)split.render(aircraft,selected,splitOptions());
    else {renderRoutes(aircraft);renderAircraft(aircraft);}
    renderSidebar(aircraft);
    const clock=state.case_replay?.active ? new Date(state.case_replay.playback_utc) : new Date(state.sim_time_s * 1000);
    document.getElementById('clock').textContent = clock.toISOString().slice(11, 19);
    document.getElementById('run-indicator').classList.toggle('running', state.running);
    document.getElementById('run-label').textContent = state.running ? 'Running' : 'Paused';
    document.getElementById('run-toggle').textContent = state.running ? 'Ⅱ Pause' : '▶ Resume';
    if(state.replay_read_only)message(state.case_replay?.ground_tracks ?
      'Full-cycle scenario · stands, taxi, holds, runway and airborne movements.' :
      'Case playback · terminal tracks only. Taxi movements are not recorded.');
    document.querySelectorAll('#departure-form input, #departure-form select, #departure-form button, #arrival-form input, #arrival-form select, #arrival-form button').forEach(e=>e.disabled=!!state.replay_read_only);
  }
  function select(callsign) {
    selected = callsign;
    render();
    if (callsign) message(state?.replay_read_only ? `${callsign} · ${state.case_replay?.ground_tracks ? 'Full-cycle playback.' : 'Case playback. Taxi data is unavailable.'}` : `${callsign} selected. Drag its symbol to reroute; Shift-drag to queue a waypoint.`);
  }
  document.getElementById('flight-panel-close').onclick = () => select('');
  function showTooltip(event) {
    const tooltip = document.getElementById('aircraft-tooltip');
    const symbol = event.target.closest?.('.aircraft-symbol');
    const a = symbol && allAircraft().find(item => item.callsign === symbol.dataset.callsign);
    if (!a || gesture) {tooltip.hidden = true; return;}
    const f = a.fpl || {};
    tooltip.replaceChildren();
    const title = document.createElement('strong'); title.textContent = a.callsign;
    const phase = document.createElement('small'); phase.textContent = `${f.aircraft_type || 'Aircraft'} · ${a.state.replace('_', ' ')}`;
    const detail = document.createElement('span'); detail.textContent = a.operation === 'approach' ?
      `${a.distance_nm.toFixed(1)} NM to 25R · ${Math.round(a.altitude_ft)} ft` :
      `${f.origin || '—'} → ${f.destination || '—'} · ${f.sid || f.star || 'Ground'}`;
    tooltip.append(title, phase, detail);
    const bounds = viewport.getBoundingClientRect();
    tooltip.style.left = `${Math.min(event.clientX - bounds.left + 16, bounds.width - 240)}px`;
    tooltip.style.top = `${Math.max(8, Math.min(event.clientY - bounds.top + 14, bounds.height - 100))}px`;
    tooltip.hidden = false;
  }
  async function refresh() {
    if(window.MosaicSupervisorSync?.active)return;
    if (fetching) return;
    fetching = true;
    try { receiveState(await api('/airport/state')); }
    catch (error) { message(error.message, true); }
    finally { fetching = false; }
  }
  function receiveState(next) {
    if(state && (state.sim_time_s!==next.sim_time_s || state.case_replay?.trail_generation!==next.case_replay?.trail_generation))
      document.getElementById('aircraft-tooltip').hidden = true;
    state = next;
    window.__mosaicTowerState = state;
    const replay = state.case_replay;
    motion.update(allAircraft(), state.sim_time_s, state.running,
      `${replay?.case_id||''}:${replay?.trail_generation||0}`, performance.now(), nodes);
    if (!gesture) render();
  }
  function animate(now) {
    if (state?.running && !gesture && now<=motion.started+motion.duration+32) {
      const aircraft=motion.sample(now);
      if(splitMode()&&split)split.position(aircraft);else positionAircraft(aircraft);
    }
    requestAnimationFrame(animate);
  }
  function nearestNode(point) {
    let result = null, best = 40;
    for (const n of nodes.values()) {
      const distance = Math.hypot(n.x - point.x, n.y - point.y);
      if (distance < best) {result = n; best = distance;}
    }
    return result;
  }
  function drawDrag() {
    layer.drag.replaceChildren();
    if (!gesture || gesture.type !== 'aircraft' || !gesture.moved) return;
    const a = allAircraft().find(item => item.callsign === gesture.callsign);
    if (!a) return;
    const p = gesture.node || gesture.point;
    layer.drag.append(svg('line', {x1: a.x, y1: a.y, x2: p.x, y2: p.y, class: 'drag-line'}));
    if (gesture.node) {
      layer.drag.append(svg('circle', {cx: p.x, cy: p.y, r: 16, class: 'drag-target'}));
      addText(layer.drag, 'text', {x: p.x + 20, y: p.y - 6, class: 'drag-target-label'},
        gesture.node.name || gesture.node.id);
    }
  }
  map.addEventListener('contextmenu', event => event.preventDefault());
  map.addEventListener('wheel', event => {
    event.preventDefault();
    zoom(event.deltaY<0?1.15:1/1.15, viewPoint(event));
  }, {passive: false});
  map.addEventListener('pointerdown', event => {
    event.preventDefault();
    if (event.button === 2) {
      autoFit = false;
      gesture = {type: 'pan', point: viewPoint(event)};
      viewport.classList.add('panning'); map.setPointerCapture(event.pointerId);
      return;
    }
    if (event.button !== 0) return;
    const symbol = event.target.closest('.aircraft-symbol');
    if (symbol) {
      if(state?.replay_read_only){select(symbol.dataset.callsign);return;}
      gesture = {type: 'aircraft', callsign: symbol.dataset.callsign,
        startX: event.clientX, startY: event.clientY, point: mapPoint(event), node: null, moved: false};
      map.setPointerCapture(event.pointerId);
    } else select('');
  });
  map.addEventListener('pointermove', event => {
    if (!gesture) showTooltip(event);
    if (!gesture) return;
    if (gesture.type === 'pan') {
      const p = viewPoint(event);
      setView({...view, x: view.x + gesture.point.x - p.x, y: view.y + gesture.point.y - p.y});
      return;
    }
    if (Math.hypot(event.clientX - gesture.startX, event.clientY - gesture.startY) > 6)
      gesture.moved = true;
    if (gesture.moved) {
      gesture.point = mapPoint(event);
      gesture.node = nearestNode(gesture.point);
      viewport.classList.add('dragging');
      drawDrag();
      message(gesture.node ? `Release on ${gesture.node.name || gesture.node.id}${event.shiftKey ? ' (queued)' : ''}` :
        'Move closer to a taxiway node.');
    }
  });
  map.addEventListener('pointerleave', () => {document.getElementById('aircraft-tooltip').hidden = true;});
  map.addEventListener('pointerup', async event => {
    if (!gesture) return;
    const drag = gesture;
    gesture = null;
    viewport.classList.remove('panning', 'dragging');
    layer.drag.replaceChildren();
    if (drag.type !== 'aircraft') return;
    if (!drag.moved) {select(drag.callsign); return;}
    if (!drag.node) {message('No taxiway node selected.'); return;}
    try {
      await api('/airport/reroute', {callsign: drag.callsign,
        target_id: drag.node.id, queue: event.shiftKey});
      selected = drag.callsign;
      message(`${drag.callsign} ${event.shiftKey ? 'queued via' : 'rerouted to'} ${drag.node.name || drag.node.id}.`);
      await refresh();
    } catch (error) {message(error.message, true);}
  });
  map.addEventListener('pointercancel', () => {
    gesture = null; viewport.classList.remove('panning', 'dragging'); layer.drag.replaceChildren();
  });

  async function submitForm(id, url) {
    const form = document.getElementById(id);
    form.onsubmit = async event => {
      event.preventDefault();
      const body = Object.fromEntries(new FormData(form));
      body.requested_fl = Number(body.requested_fl);
      if (body.transition === '') delete body.transition;
      try {
        const result = await api(url, body);
        selected = result.fpl.callsign;
        message(`${selected} added to the shared scenario.`);
        await refresh();
      } catch (error) {message(error.message, true);}
    };
  }
  function fillSelect(id, values) {
    const select = document.getElementById(id);
    for (const item of values) {
      const option = document.createElement('option');
      option.value = typeof item === 'string' ? item : item.id;
      option.textContent = typeof item === 'string' ? item : item.name;
      select.append(option);
    }
  }
  async function init() {
    try {
      layout = await api('/airport/layout');
      nodes = new Map(layout.nodes.map(n => [n.id, n]));
      split = new window.MosaicSplitTower(document.getElementById('tower-split'),layout,{
        select,
        hover:showTooltip,
        hideTooltip:()=>{document.getElementById('aircraft-tooltip').hidden=true;},
        reroute:async(callsign,node,queue)=>{
          try {
            await api('/airport/reroute',{callsign,target_id:node.id,queue});
            selected=callsign;message(`${callsign} ${queue?'queued via':'rerouted to'} ${node.name||node.id}.`);await refresh();
          } catch(error) {message(error.message,true);}
        }
      });
      drawLayout();
      state = await api('/airport/state');
      fillSelect('stand', state.stands);
      fillSelect('sid', state.sids);
      fillSelect('star', state.stars);
      const result = await api('/scenario/presets');
      presets = result.presets || [];
      const scenarioSelect = document.getElementById('scenario-select');
      for (const preset of presets) {
        const option = document.createElement('option'); option.value = preset.key;
        option.textContent = preset.label; scenarioSelect.append(option);
      }
      scenarioSelect.onchange = () => {
        document.getElementById('scenario-description').textContent =
          presets.find(p => p.key === scenarioSelect.value)?.description || '';
      };
      scenarioSelect.onchange();
      receiveState(state);
      setLayout();
      if(window.MosaicSupervisorSync?.active)window.MosaicSupervisorSync.subscribe(frame=>receiveState(frame.airport));
      else setInterval(refresh, 1000);
    } catch (error) {message(error.message, true);}
  }
  submitForm('departure-form', '/airport/departures');
  submitForm('arrival-form', '/airport/arrivals');
  document.getElementById('tower-layout').value = window.self!==window.top ? 'split' : 'full';
  document.getElementById('tower-layout').onchange = setLayout;
  document.getElementById('fit-view').onclick = () => splitMode() ? split?.fitAll() : fitView();
  document.getElementById('zoom-in').onclick = () => splitMode() ? split && split.zoom(split.activePane,1.25) : zoom(1.25);
  document.getElementById('zoom-out').onclick = () => splitMode() ? split && split.zoom(split.activePane,1/1.25) : zoom(1/1.25);
  document.getElementById('map-orientation').onchange = fitView;
  new ResizeObserver(()=>{
    if (!viewport.clientWidth || !viewport.clientHeight) return;
    if(splitMode()){split?.resize();return;}
    if (autoFit || rotation!==desiredRotation()) fitView();
    else updateGlyphs();
  }).observe(viewport);
  requestAnimationFrame(animate);
  document.getElementById('run-toggle').onclick = async () => {
    try {await api('/scenario/control', {action: state?.running ? 'pause' : 'resume'}); await refresh();}
    catch (error) {message(error.message, true);}
  };
  document.getElementById('step').onclick = async () => {
    try {await api('/scenario/control', {action: 'step', ticks: 1}); await refresh();}
    catch (error) {message(error.message, true);}
  };
  for (const [id, type] of [['takeoff-clearance', 'takeoff'], ['crossing-clearance', 'crossing']]) {
    document.getElementById(id).onclick = async () => {
      try {await api('/airport/clearance', {callsign: selected, type}); message(`${selected}: ${type} clearance issued.`); await refresh();}
      catch (error) {message(error.message, true);}
    };
  }
  document.getElementById('restore-route').onclick = async () => {
    try {await api('/airport/restore-route', {callsign: selected}); message(`${selected}: planned route restored.`); await refresh();}
    catch (error) {message(error.message, true);}
  };
  document.getElementById('load-scenario').onclick = async () => {
    const key = document.getElementById('scenario-select').value;
    try {await api(`/scenario/presets/${encodeURIComponent(key)}/load`, {}); selected = ''; message('Scenario loaded. Resume to start.'); await refresh();}
    catch (error) {message(error.message, true);}
  };
  init();
})();
