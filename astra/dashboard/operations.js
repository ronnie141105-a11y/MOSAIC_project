(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const dialog = $('operations-dialog');
  if (!dialog) return;
  let state = null, reviewed = null, busy = false, weatherDirty = false, rateDirty = false;
  const labels = {departure_slots:'Departure slots', minit:'Departure spacing', ground_stop:'Ground stop', arrival_metering:'TMA arrival metering'};
  const help = {
    departure_slots:'Hold flights at their stands until their departure slot. Takeoff clearance is still required.',
    minit:'Release departures at least the selected number of minutes apart.',
    ground_stop:'Keep departures on the ground. Flights already on the runway continue.',
    arrival_metering:'Absorb arrival delay with upstream speed changes. Any delay that cannot be absorbed stays visible.'
  };
  const clock = t => t == null ? 'On hold' : [Math.floor(t/3600),Math.floor(t%3600/60),Math.floor(t%60)].map(n=>String(n).padStart(2,'0')).join(':');
  const minutes = t => t == null ? 'Pending' : (t/60).toFixed(1)+' min';
  const strip = $('wx-strip');
  const header = document.querySelector('#hmi-header, .topbar');
  if (header) header.after(strip);
  function values(form) {
    const data = Object.fromEntries(new FormData(form));
    for (const key of ['duration_min','rate_per_hour','minit_min','nominal_departures_per_hour','nominal_arrivals_per_hour']) if (key in data) data[key]=Number(data[key]);
    return data;
  }
  async function api(path, body) {
    const response = await fetch('/api/operations/'+path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if (response.status === 404) throw new Error('UNAVAILABLE');
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || 'Could not complete the action.');
    return data;
  }
  function forgetReview() { reviewed=null; $('ops-apply').disabled=true; }
  function measureFields() {
    const kind=$('ops-measure').value;
    $('ops-measure-help').textContent=help[kind];
    $('ops-minit-field').hidden=kind!=='minit';
    $('ops-rate-field').hidden=kind==='ground_stop';
    if (state && !rateDirty) $('ops-rate').value=Math.max(1,Math.floor(kind==='arrival_metering' ? state.capacity.arrivals_per_hour : state.capacity.departures_per_hour));
  }
  function schedule(rows) {
    const tbody=$('ops-slots'); tbody.replaceChildren();
    $('ops-flight-summary').textContent='Flight schedule · '+rows.length+' flights';
    if (!rows.length) { const cell=tbody.insertRow().insertCell(); cell.colSpan=5; cell.textContent='No flights affected yet.'; return; }
    for (const flight of rows) {
      const action=flight.status==='CAPACITY_REVIEW_REQUIRED' ? 'Needs coordination' : flight.speed_factor!==undefined ? 'Up to '+Math.round((1-flight.speed_factor)*100)+'% slower · remaining '+minutes(flight.residual_delay_s) : flight.status==='STAND_HOLD' ? 'Stand hold until '+clock(flight.off_block_time_s) : flight.status==='GROUND_STOP' ? 'Remain on ground' : 'Departure slot';
      const row=tbody.insertRow();
      for (const value of [flight.callsign,clock(flight.estimated_time_s),clock(flight.target_time_s),minutes(flight.delay_s),action]) row.insertCell().textContent=value;
    }
  }
  function publish(data) {
    const caseReplay=data.case_replay;
    $('operations-open').hidden=!!caseReplay?.active;
    strip.querySelector('[data-open-operations]').hidden=!!caseReplay?.active;
    if(caseReplay?.active){
      if(dialog.open)dialog.close();
      strip.hidden=true;
      window.MOSAIC_OPERATIONS={...data,tma_weather:null};
      window.dispatchEvent(new CustomEvent('mosaic:operations',{detail:window.MOSAIC_OPERATIONS}));
      return;
    }
    const weather=data.weather, c=data.capacity;
    strip.hidden=false;
    $('wx-condition').textContent='VVTS · '+weather.label;
    $('wx-source').textContent=weather.source==='SIMULATED' ? 'SIM METAR' : 'USER METAR';
    $('wx-metar').textContent=weather.raw;
    $('wx-summary').textContent=(weather.wind_direction_deg==null?'VRB':String(weather.wind_direction_deg).padStart(3,'0')+'°')+' / '+weather.wind_speed_kt+' kt · VIS '+weather.visibility_m+' m · QNH '+weather.qnh_hpa+' · TMA ARR '+c.arrivals_per_hour.toFixed(0)+'/h'+(data.program?' · '+labels[data.program.type]:'');
    $('operations-badge').textContent=data.program?labels[data.program.type]:weather.label;
    window.MOSAIC_OPERATIONS=data;
    window.dispatchEvent(new CustomEvent('mosaic:operations',{detail:data}));
  }
  function render(data) {
    const changed=state && state.weather.raw!==data.weather.raw;
    state=data; publish(data);
    if (changed) forgetReview();
    if (data.available===false) {
      $('ops-unavailable').hidden=false; $('ops-unavailable').textContent=data.blocked_reason; $('ops-controls').hidden=true; forgetReview(); return;
    }
    $('ops-unavailable').hidden=true; $('ops-controls').hidden=false;
    if (!dialog.open) return;
    const weather=data.weather, c=data.capacity, demand=data.demand;
    if (!$('ops-preset').options.length) for (const item of data.presets) $('ops-preset').add(new Option(item.label,item.key));
    if (!weatherDirty) { $('ops-preset').value=weather.preset; $('ops-nominal-dep').value=c.nominal_departures_per_hour; $('ops-nominal-arr').value=c.nominal_arrivals_per_hour; }
    $('ops-source').textContent=weather.source==='SIMULATED'?'Simulated':'User METAR';
    $('ops-weather-effect').textContent=weather.preset==='clear' ? 'Normal TMA and airport conditions.' : 'TMA speeds, arrival times and airport capacity change with this weather.'+(data.recovery_at_s!=null?' Clears at '+clock(data.recovery_at_s)+'.':'');
    $('ops-trigger').textContent=demand.trigger==='BALANCED'?'Within capacity':demand.trigger==='DEPARTURE_CAPACITY_ZERO'?'Departures suspended':'Over capacity';
    const tiles=$('ops-capacity'); tiles.replaceChildren();
    for (const [label,rate,count] of [['Departures',c.departures_per_hour,demand.departures],['TMA arrivals',c.arrivals_per_hour,demand.arrivals]]) {
      const tile=document.createElement('div'), title=document.createElement('span'), strong=document.createElement('strong'), sub=document.createElement('small');
      title.textContent=label; strong.textContent=rate.toFixed(0)+' / hour'; sub.textContent=count+' expected in the next 15 min'; tile.append(title,strong,sub); tiles.append(tile);
    }
    $('ops-recommendation').textContent=data.recommendation ? 'Suggested: '+labels[data.recommendation]+'.' : 'No additional ATFM measure suggested.';
    $('ops-use-recommendation').hidden=!data.recommendation;
    $('ops-program-status').textContent=data.program ? data.program.status==='ACTIVE'?'Active':'Needs coordination' : 'Off';
    $('ops-cancel').hidden=!data.program;
    measureFields();
    if (!reviewed) {
      schedule(data.slots);
      $('ops-program-description').textContent=data.program ? labels[data.program.type]+' is active until '+clock(data.program.ends_at_s)+'. Simulation time '+clock(data.sim_time_s)+'.' : 'Preview the flights affected, then start the measure.';
    }
    const m=data.metrics;
    $('ops-results').textContent=m.completed_departures+' departures completed · stand holds '+minutes(m.stand_hold_s)+' · taxi/runway holds '+minutes(m.runway_and_taxi_hold_s)+' · unabsorbed arrival delay '+minutes(m.residual_arrival_delay_s);
    $('ops-note').textContent=data.note;
    $('ops-log').replaceChildren();
    for (const event of data.history.slice(-8).reverse()) { const line=document.createElement('div'); line.textContent=clock(event.time_s)+' · '+event.event.replaceAll('_',' ')+' · '+event.reason; $('ops-log').append(line); }
  }
  async function refresh() {
    if (busy) return;
    try { render(await api('state')); }
    catch (error) {
      if (error.message==='UNAVAILABLE') { strip.hidden=true; $('ops-unavailable').hidden=false; $('ops-controls').hidden=true; }
      else { $('wx-source').textContent='WX UNAVAILABLE'; if (dialog.open) $('ops-error').textContent=error.message; }
    }
  }
  async function mutate(action) {
    if (busy) return;
    busy=true; $('ops-error').textContent='';
    try { await action(); } catch (error) { $('ops-error').textContent=error.message; }
    finally { busy=false; }
  }
  function open() { if (!dialog.open) dialog.showModal(); if (state) render(state); refresh(); }
  $('operations-open').addEventListener('click',open);
  document.querySelectorAll('[data-open-operations]').forEach(button=>button.addEventListener('click',open));
  $('operations-close').addEventListener('click',()=>dialog.close());
  $('ops-weather-form').addEventListener('input',()=>{weatherDirty=true;});
  $('ops-weather-form').addEventListener('submit',event=>{event.preventDefault();mutate(async()=>{const result=await api('weather',values(event.target));weatherDirty=false;forgetReview();render(result);});});
  $('ops-metar-form').addEventListener('submit',event=>{event.preventDefault();mutate(async()=>{const result=await api('weather',{metar:$('ops-metar-input').value});weatherDirty=false;forgetReview();render(result);});});
  $('ops-program-form').addEventListener('input',()=>{forgetReview();measureFields();});
  $('ops-rate').addEventListener('input',()=>{rateDirty=true;});
  $('ops-measure').addEventListener('change',()=>{rateDirty=false;measureFields();});
  $('ops-use-recommendation').addEventListener('click',()=>{if(!state?.recommendation)return;$('ops-measure').value=state.recommendation;rateDirty=false;forgetReview();measureFields();$('ops-measure').focus();});
  $('ops-program-form').addEventListener('submit',event=>{
    event.preventDefault();mutate(async()=>{
      const body=values(event.target); body.reason=body.reason.trim() || (state.weather.label+': '+(state.recommendation?'traffic/capacity coordination':'flow management'));
      reviewed=await api('review',body);schedule(reviewed.slots);$('ops-flight-details').open=true;$('ops-apply').disabled=false;
      $('ops-program-description').textContent='Ready: '+labels[reviewed.config.type]+' for '+reviewed.config.duration_min+' minutes. Start to apply these changes.';
    });
  });
  $('ops-apply').addEventListener('click',()=>mutate(async()=>{if(!reviewed)return;const token=reviewed.token;forgetReview();render(await api('apply',{token}));}));
  $('ops-cancel').addEventListener('click',()=>mutate(async()=>{forgetReview();render(await api('cancel',{}));}));
  setInterval(refresh,2000); refresh();
})();
