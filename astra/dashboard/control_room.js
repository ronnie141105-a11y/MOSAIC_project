(()=>{
 'use strict';const $=id=>document.getElementById(id);let latest=null,sequence=0,busy=false,shownCase=null;
 async function api(url,body){const r=await fetch(url,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d;}
 function send(target){if(latest)target.postMessage({type:'mosaic-supervisor-frame',frame:latest},location.origin);}
 window.addEventListener('message',e=>{if(e.origin===location.origin&&e.data?.type==='mosaic-supervisor-ready'&&[...document.querySelectorAll('iframe')].some(f=>f.contentWindow===e.source))send(e.source);});
 async function poll(){
  try{
   const [radar,airport]=await Promise.all([api('/state'),api('/airport/state')]);
   const identitiesMatch=!airport.case_replay?.active||radar.cycle?.snapshot.aircraft.every(a=>a.callsign in airport.fpl);
   if(radar.has_data&&identitiesMatch&&Math.abs(radar.cycle.snapshot.timestamp_s-airport.sim_time_s)<.001){
    latest={sequence:++sequence,radar,airport};window.__mosaicSupervisorFrame=latest;
    document.querySelectorAll('iframe').forEach(f=>send(f.contentWindow));
    const replay=airport.case_replay;
    const replayKey=replay?.case_id+':'+replay?.method;
    if(replay?.active&&replayKey!==shownCase&&[...$('test-scenario').options].some(o=>o.value===replay.case_id)){$('test-scenario').value=replay.case_id;$('traffic-plan').value=replay.method==='NO_CONTROL'?'RECONSTRUCTED':replay.method;shownCase=replayKey;}
    $('clock').textContent=(replay?.active?new Date(replay.playback_utc):new Date(airport.sim_time_s*1000)).toISOString().slice(11,19);
    $('run-status').textContent=replay?.atfm_complete?(airport.running?'Arrival tail':'ATFM complete'):(airport.running?'Running':'Paused');$('play').textContent=airport.running?'Pause':replay?.atfm_complete?(replay.remaining_arrivals?'Continue arrivals':'Completed'):'Play';
    $('play').disabled=!!replay?.atfm_complete&&!replay.remaining_arrivals&&!airport.running;
    $('timeline').disabled=!replay?.active;if(replay?.active&&!$('timeline').matches(':active')){$('timeline').max=replay.duration_s;$('timeline').value=replay.time_s;}
    if(replay?.active)$('speed').value=String(replay.multiplier);
    $('sector-capacity').textContent=(replay?.sector_occupancy||[]).map(s=>`${s.label}: ${s.count}/${s.capacity}${s.excess?' EXCEEDED':''}`).join(' · ');
    $('traffic-count').textContent=`${radar.cycle.snapshot.aircraft.filter(a=>a.altitude_ft>0&&!a.on_ground).length} airborne · ${(airport.aircraft||[]).filter(a=>a.state!=='CLIMBING').length} surface${replay?.active?' · '+replay.total+' planned':''}`;
   }
  }catch(e){$('message').textContent=e.message;}
  finally{setTimeout(poll,500);}
 }
 async function action(fn){if(busy)return;busy=true;try{await fn();$('message').textContent='';}catch(e){$('message').textContent=e.message;}finally{busy=false;}}
 $('play').onclick=()=>action(()=>api('/scenario/control',{action:latest?.airport.running?'pause':'resume'}));
 $('speed').onchange=()=>action(()=>api('/scenario/control',{action:'speed',multiplier:Number($('speed').value)}));
 $('restart').onclick=()=>action(()=>latest?.airport.case_replay?.active?api('/api/case-scenarios/control',{action:'seek',time_s:0}):api('/scenario/control',{action:'reset'}));
 $('timeline').onchange=()=>action(()=>api('/api/case-scenarios/control',{action:'seek',time_s:Number($('timeline').value)}));
 $('load-test').onclick=()=>action(async()=>{const caseId=$('test-scenario').value;if(!caseId)throw Error('Choose a scenario');await api('/api/system-tests/load',{case_id:caseId,method:caseId.startsWith('workbook_')?$('traffic-plan').value:'RECONSTRUCTED'});});
 $('test-scenario').onchange=()=>{$('traffic-plan').disabled=!$('test-scenario').value.startsWith('workbook_');};
 document.querySelectorAll('[data-focus]').forEach(button=>button.onclick=()=>{$('views').classList.add('focused');document.querySelectorAll('[data-view]').forEach(s=>s.classList.toggle('expanded',s.dataset.view===button.dataset.focus));});
 $('all-views').onclick=()=>{$('views').classList.remove('focused');};
 api('/api/system-tests').then(data=>{for(const s of data.scenarios)$('test-scenario').add(new Option(s.label,s.case_id));}).catch(e=>$('message').textContent=e.message);
 poll();
})();
