(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const labels = {RECONSTRUCTED:'Reference',NO_CONTROL:'Reference',FCFS:'FCFS',TEAM_MIXED:'GA'};
  const fmt = value => Number(value).toLocaleString('en-GB',{minimumFractionDigits:2,maximumFractionDigits:2});
  const short = value => Number(value).toLocaleString('en-GB',{maximumFractionDigits:1});
  let state={},cases=[],busy=false,revision=0,optResult=null,optimizerRevision=0,optimizerRunning=false,seenRun=null,notesCase='';

  async function api(path,body) {
    const response=await fetch('/api/case-scenarios'+path,body?{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)
    }:{});
    const data=await response.json();
    if(!response.ok)throw Error(data.error||'Request failed.');
    return data;
  }
  function message(id,error) {
    $(id).hidden=!error;
    $(id).textContent=error?.message||'';
  }
  function renderCase() {
    for(const option of $('opt-case').options){const c=cases.find(c=>c.case_id===option.value);if(c?.counts)option.textContent=(c.study_role==='nominal'?'Nominal':'Overload')+' · '+c.counts.total+' aircraft';}
    const selected=cases.find(c=>c.case_id===$('opt-case').value);
    const counts=selected?.counts||(optResult?.case_id===$('opt-case').value?optResult.case_counts:null);
    $('case-description').textContent=counts?counts.arrivals+' arrivals · '+counts.departures+' departures':'';
    if(notesCase!==(selected?.case_id||'')) {
      notesCase=selected?.case_id||'';$('notes').replaceChildren();
      for(const note of selected?.limitations||[]) {
        const li=document.createElement('li');li.textContent=note;$('notes').append(li);
      }
    }
  }
  function render() {
    $('load-replay').disabled=busy||(!optResult&&$('method').value!=='RECONSTRUCTED');
    $('playback-controls').hidden=!state.active;
    for(const id of ['play','speed','restart','timeline','stop'])$(id).disabled=!state.active||busy;
    const active=cases.find(c=>c.case_id===state.case_id);
    const caseName=active?(active.study_role==='nominal'?'Nominal':'Overload'):state.case_id;
    $('status').textContent=state.active
      ? caseName+' · '+(labels[state.method]||state.method)+' · '+state.visible+' airborne · '+state.completed+'/'+state.total+' completed'
      : 'No scenario loaded.';
    if(state.atfm_complete)$('status').textContent+=' · ATFM complete · '+state.remaining_arrivals+' arrivals remain';
    $('play').textContent=state.running?'Pause':state.atfm_complete?(state.remaining_arrivals?'Continue arrivals':'Completed'):'Play';
    if(state.atfm_complete&&!state.remaining_arrivals&&!state.running)$('play').disabled=true;
    $('speed').value=String(state.multiplier||30);
    if(!$('timeline').matches(':active')) {
      $('timeline').max=state.duration_s||10800;
      $('timeline').value=state.time_s||0;
    }
    $('clock').textContent=state.playback_utc
      ? new Date(state.playback_utc).toLocaleTimeString('en-GB',{timeZone:'UTC',hour12:false})+' UTC':'';
    renderCase();
  }
  async function submit(path,body) {
    if(busy)return;
    busy=true;revision++;render();
    try {state=(await api(path,body)).replay;message('error',null);}
    catch(error){message('error',error);}
    finally{busy=false;render();}
  }
  const control=body=>submit('/control',body);
  $('method').onchange=render;
  $('load-replay').onclick=()=>submit('/load',{
    case_id:$('opt-case').value,method:$('method').value,enroute:true,
    run_id:optResult?.case_id===$('opt-case').value?optResult.run_id:undefined
  });
  $('play').onclick=()=>control({action:state.running?'pause':'play'});
  $('speed').onchange=()=>control({action:'speed',multiplier:Number($('speed').value)});
  $('restart').onclick=()=>control({action:'seek',time_s:0});
  $('stop').onclick=()=>control({action:'stop'});
  $('timeline').onchange=()=>control({action:'seek',time_s:Number($('timeline').value)});

  function addRow(target,values,team=false) {
    const tr=document.createElement('tr');if(team)tr.className='team';
    for(const value of values){const td=document.createElement('td');td.textContent=value;tr.append(td);}
    $(target).append(tr);
  }
  function showResult(result) {
    if(!result.native_summary)throw Error('This case has no saved executed comparison.');
    optResult=result;$('opt-results').hidden=false;$('native-rows').replaceChildren();$('detail-rows').replaceChildren();
    const rows=Object.fromEntries(result.native_summary.map(r=>[r.method,r]));
    const spread=(row,key)=>fmt(row['mean_'+key])+(row.runs>1?' ± '+fmt(row['std_'+key]):'');
    for(const method of ['TEAM_MIXED','FCFS','NO_CONTROL']) {
      const r=rows[method];
      addRow('native-rows',[labels[method],spread(r,'total_delay_min'),spread(r,'sector_excess_aircraft_minutes'),
        r.safe_runs===r.runs?'Passed':r.safe_runs+'/'+r.runs+' passed'],method==='TEAM_MIXED');
    }
    const f=rows.FCFS,g=rows.TEAM_MIXED;
    const excess=f.mean_sector_excess_aircraft_minutes-g.mean_sector_excess_aircraft_minutes;
    const delay=g.mean_total_delay_min-f.mean_total_delay_min;
    let takeaway;
    if(f.mean_sector_excess_aircraft_minutes===0&&g.mean_sector_excess_aircraft_minutes===0&&Math.abs(delay)<1e-9) {
      takeaway='Both methods stayed within sector capacity and produced the same event delay.';
    } else {
      takeaway=excess>0&&f.mean_sector_excess_aircraft_minutes>0
        ? 'GA reduced sector overload by '+short(excess/f.mean_sector_excess_aircraft_minutes*100)+'%. '
        : excess===0?'Both methods produced the same sector overload. ':'GA produced more sector overload. ';
      takeaway+=Math.abs(delay)<1e-9?'Event delay was unchanged.':'Event delay '+(delay>0?'increased':'decreased')+' by '+short(Math.abs(delay))+' aircraft-minutes.';
      if(g.mean_sector_excess_aircraft_minutes>0)takeaway+=' Overload remains.';
    }
    const fcfsTrial=(result.native_trials||[]).find(r=>r.method==='FCFS');
    if((fcfsTrial?.metrics.native_withdrawn_control_proposals||0)>0)takeaway+=' FCFS control proposals were withdrawn by execution checks; inspect its executed plan when interpreting the comparison.';
    $('study-takeaway').textContent=takeaway;
    $('study-sampling').textContent=g.runs>1?'GA values are mean ± sample SD across '+g.runs+' runs.':'One GA run; variation across runs was not estimated.';
    for(const method of ['TEAM_MIXED','FCFS','NO_CONTROL']) {
      const r=rows[method];
      addRow('detail-rows',[labels[r.method]||r.method,r.runs,spread(r,'total_delay_min'),
        spread(r,'sector_excess_aircraft_minutes'),spread(r,'converted_cost'),
        short(r.mean_completed_in_original_window)+' / '+result.case_counts.total,
        r.capacity_feasible_runs+' / '+r.runs],r.method==='TEAM_MIXED');
    }
    const searches=Object.entries(result.runs).filter(([name])=>name.startsWith('TEAM_MIXED_')).map(([,r])=>r.search);
    const mixed=(result.native_trials||[]).filter(r=>r.method==='TEAM_MIXED');
    const executed=mixed.reduce((n,r)=>n+r.metrics.speed_flights,0);
    const rta=mixed.reduce((n,r)=>n+(r.metrics.rta_flights||0),0);
    const vectors=mixed.reduce((n,r)=>n+(r.metrics.vector_flights||0),0);
    const caps=mixed.reduce((n,r)=>n+(r.metrics.level_cap_flights||0),0);
    const withdrawn=mixed.reduce((n,r)=>n+(r.metrics.native_withdrawn_control_proposals||0),0);
    $('opt-native-feedback').textContent='Executed checks: 1 second. GA arrival speed controls across all runs: '+
      executed+' direct speed controls; RTA '+rta+', short vectors '+vectors+', level caps '+caps+'. '+withdrawn+' control proposals withdrawn by safety checks. Simulator checkpoints: '+
      searches.reduce((n,s)=>n+(s.native_checks||0),0)+'.';
    $('opt-model').textContent='GDP/CTOT: 0–60 minutes, at TSN and six regional origins. Fixed departure queues. GA adds gate RTA, speed −15% to +10%, short rejoining vectors and regional level caps. AC + BAOMY share MIT/MINIT limits. Same sector capacities for both cases. Takeoff gap ≥120 seconds; full runway evacuation, next arrival outside 6 NM at roll start, wheel-off >30 seconds before touchdown.';
    $('opt-run-info').textContent=result.case_id+' · '+result.version+' · '+result.run_id+
      ' · '+result.settings.seeds.length+' GA runs · '+result.settings.max_evaluations.toLocaleString('en-GB')+
      ' fast evaluations/run, plus separately counted simulator checks.';
    $('opt-download').href='/api/case-scenarios/optimizer/results?case_id='+encodeURIComponent(result.case_id)+'&download=1';
    $('results-loading').hidden=true;render();
  }
  async function savedResult() {
    const caseId=$('opt-case').value,requested=++optimizerRevision;
    optResult=null;$('opt-results').hidden=true;$('results-loading').hidden=false;
    $('results-loading').textContent='Loading saved results…';message('opt-error',null);render();
    try {
      const result=await api('/optimizer/results?case_id='+encodeURIComponent(caseId));
      if(requested!==optimizerRevision)return;
      showResult(result);
    } catch(error) {
      if(requested!==optimizerRevision)return;
      $('results-loading').hidden=true;message('opt-error',error);
    }
  }
  $('opt-case').onchange=savedResult;
  $('opt-saved').onclick=savedResult;
  $('opt-run').onclick=async()=>{
    if(optimizerRunning)return;
    $('opt-run').disabled=true;message('opt-error',null);
    try {
      const count=Number($('opt-seeds').value);
      await api('/optimizer/run',{case_id:$('opt-case').value,seeds:Array.from({length:count},(_,i)=>(i+1)*11),
        population:Number($('opt-population').value),generations:Number($('opt-generations').value),
        max_evaluations:Number($('opt-budget').value),compare_legacy:false});
      optimizerRunning=true;seenRun=null;$('opt-status').textContent='Preparing the study…';
    } catch(error){message('opt-error',error);$('opt-run').disabled=false;}
  };
  async function pollOptimizer() {
    try {
      const status=await api('/optimizer/status');
      optimizerRunning=status.status==='running';$('opt-run').disabled=optimizerRunning;
      if(optimizerRunning) {
        const p=status.progress;
        $('opt-status').textContent=p.phase==='native_search_feedback'
          ? 'Testing '+p.method+' in the simulator; candidate '+p.native_candidates+'.'
          : p.phase==='full_route_tables'?'Preparing trajectories: '+p.pair+' / '+p.pairs+' aircraft pairs.'
          : 'Running '+status.case_id+': '+(p.completed_seeds||0)+' / '+(p.total_seeds||'?')+' GA runs.';
      } else if(status.status==='error') {
        $('opt-status').textContent='Study failed. Previous saved results are retained.';message('opt-error',Error(status.error));
      } else if(status.status==='done') {
        $('opt-status').textContent='Study saved. The comparison uses all GA runs; replay uses the best executed run.';
        if(seenRun!==status.case_id){seenRun=status.case_id;if($('opt-case').value===status.case_id)await savedResult();}
      } else $('opt-status').textContent='Ready. Saved results are shown above.';
    } catch(error){$('opt-status').textContent=error.message;}
    finally{setTimeout(pollOptimizer,2000);}
  }
  async function poll() {
    const requested=revision;
    try {
      if(busy)return;
      const data=await api('');
      if(busy||requested!==revision)return;
      state=data.replay;cases=data.cases;render();
    } catch(error){message('error',error);}
    finally{setTimeout(poll,1500);}
  }
  render();savedResult();pollOptimizer();poll();
})();
