/* Centre origin dispatch board and shared AC/BAOMY flow programme. */
(() => {
  if (window.MOSAIC_CONTROL_VIEW !== 'centre') return;
  let state=null,selected='VVTS',hits=[];
  const panel=document.createElement('section');panel.id='gate-flow-board';panel.setAttribute('aria-label','Origin dispatch and gate flow');
  panel.innerHTML='<header><strong>Điều tiết luồng · AC / BAOMY</strong><button type="button" aria-label="Đóng bảng">×</button></header><div class="flow-origins"></div><div class="flow-programme"></div><h3></h3><p class="flow-counts"></p><div class="flow-table-wrap"><table><thead><tr><th>Tàu bay</th><th>TOBT gốc</th><th>CTOT gốc</th><th>TOBT mới</th><th>CTOT mới</th><th>Trạng thái</th></tr></thead><tbody></tbody></table></div><p class="flow-note"></p>';
  document.body.append(panel);
  const toggle=document.createElement('button');toggle.id='gate-flow-toggle';toggle.textContent='GDP / TOBT / CTOT';toggle.type='button';document.body.append(toggle);
  toggle.onclick=()=>panel.classList.toggle('open');panel.querySelector('header button').onclick=()=>panel.classList.remove('open');
  const labels={STAND:'Tại đỗ',TAXI:'Đang lăn',AIRBORNE:'Đang bay',COMPLETE:'Hoàn tất'};
  function clock(s){if(s===null||s===undefined)return '—';if(!state.local_start)return Math.floor(s/3600).toString().padStart(2,'0')+':'+Math.floor(s%3600/60).toString().padStart(2,'0');return new Date(Date.parse(state.local_start)+s*1000).toISOString().slice(11,19)+(s<0?' (−'+Math.ceil(-s/60)+'m)':'');}
  function td(row,value){const cell=document.createElement('td');cell.textContent=value;row.append(cell);}
  function actions(a){const parts=[];if(a.speed_change_pct!=null)parts.push('Tốc độ '+(a.speed_change_pct>0?'+':'')+a.speed_change_pct.toFixed(1)+'%');if(a.path_extension_nm>0)parts.push('Vector +'+a.path_extension_nm.toFixed(1)+' NM');if(a.level_cap_ft)parts.push('Trần FL'+a.level_cap_ft/100);if(a.gdp_delay_s>0)parts.push('GDP thêm '+Math.round(a.gdp_delay_s/60)+' phút');if(a.rta_status==='REVISED_BY_SAFETY_METERING')parts.push('RTA đã điều chỉnh');return parts.join(' · ')||'Theo kế hoạch';}
  function show(){
    if(!state)return;
    const origin=state.airports.find(a=>a.icao===selected);
    const buttons=panel.querySelector('.flow-origins');buttons.replaceChildren();
    for(const a of state.airports){const b=document.createElement('button');b.type='button';b.textContent=a.short+' '+a.waiting;b.classList.toggle('selected',a.icao===selected);b.onclick=()=>{selected=a.icao;show();};buttons.append(b);}
    for(const id of ['AC / BAOMY','PTH']){const b=document.createElement('button');b.type='button';b.textContent=id;b.classList.toggle('selected',id==='PTH'?selected==='PTH':selected==='AC_BAOMY');b.onclick=()=>{selected=id==='PTH'?'PTH':'AC_BAOMY';show();};buttons.append(b);}
    const all=document.createElement('button');all.type='button';all.textContent='Luồng đến';all.classList.toggle('selected',selected==='ALL_GATES');all.onclick=()=>{selected='ALL_GATES';show();};buttons.append(all);
    const p=state.programme;
    panel.querySelector('.flow-programme').textContent=p?`AC + BAOMY: ${p.mit_nm} NM / ${p.minit_s/60} phút · PTH → BAOMY · Giữ thứ tự khởi hành`:'Nạp case để xem kế hoạch điều tiết. Giữ thứ tự khởi hành.';
    const titles=origin?['Tàu bay','TOBT gốc','CTOT gốc','TOBT mới','CTOT mới','Trạng thái']:['Tàu bay','Từ','Điểm','CTO','RTA','Trạng thái'];panel.querySelectorAll('th').forEach((th,i)=>th.textContent=titles[i]);
    if(!origin){
      const gates=selected==='PTH'?state.gates.filter(g=>g.id==='PTH'):state.gates.filter(g=>g.id==='AC'||g.id==='BAOMY');
      const events=(selected==='ALL_GATES'?[...(state.arrival_events||[])]:gates.flatMap(g=>g.events)).sort((a,b)=>a.time_s-b.time_s);
      panel.querySelector('h3').textContent=selected==='ALL_GATES'?'Luồng đến · CTO / RTA':selected==='PTH'?'Nhánh PTH → BAOMY':'Cụm AC + BAOMY · điều phối chung';
      panel.querySelector('.flow-counts').textContent=`Qua trong 15 phút tới: ${events.filter(e=>e.time_s>=state.time_s&&e.time_s<state.time_s+900).length} · Tổng ${events.length} chuyến`;
      const body=panel.querySelector('tbody');body.replaceChildren();
      for(const f of events){const row=document.createElement('tr');td(row,f.callsign);td(row,f.origin);td(row,f.gate);td(row,clock(f.time_s));td(row,clock(f.rta_s));td(row,f.time_s<=state.time_s?'Đã qua':'Dự kiến');body.append(row);}
      panel.querySelector('.flow-note').textContent='AC và BAOMY dùng chung giới hạn luồng; PTH được theo dõi như nhánh cấp vào BAOMY. Giờ UTC.';return;
    }
    panel.querySelector('h3').textContent=origin.name+' · '+origin.icao;
    panel.querySelector('.flow-counts').textContent=`Tại đỗ ${origin.counts.STAND} · Đang lăn ${origin.counts.TAXI} · Đang bay ${origin.counts.AIRBORNE} · Hoàn tất ${origin.counts.COMPLETE}`;
    const body=panel.querySelector('tbody');body.replaceChildren();
    for(const f of origin.departures){const row=document.createElement('tr');td(row,f.callsign);td(row,clock(f.requested_tobt_s));td(row,clock(f.requested_ctot_s));td(row,clock(f.tobt_s));td(row,clock(f.ctot_s));row.title=actions(f.actions);if(f.ctot_s>f.requested_ctot_s)row.classList.add('regulated');td(row,labels[f.state]||f.state);body.append(row);}
    if(!origin.departures.length){const row=document.createElement('tr');const cell=document.createElement('td');cell.colSpan=6;cell.textContent='Chưa có chuyến khởi hành trong kịch bản.';row.append(cell);body.append(row);}
    panel.querySelector('.flow-note').textContent=origin.icao==='VVTS'?`Luồng đến TSN: ${origin.arrivals.length} chuyến; đã vào đỗ ${origin.arrivals.filter(f=>f.state==='ARRIVED').length}. Giờ UTC; −m = trước lúc bắt đầu.`:'Giờ UTC. Thời gian âm là trước lúc bắt đầu. Sân bay nguồn dùng mô hình thời gian tại đỗ/lăn giả định; radar bắt đầu theo dõi sau CTOT.';
  }
  window.MosaicGateFlow={
    draw(ctx,project){
      hits=[];if(!state)return;
      for(const a of state.airports){const [x,y]=project(a.lat,a.lon);hits.push({x,y,id:a.icao});}
      for(const g of state.gates){const [x,y]=project(g.lat,g.lon);hits.push({x,y,id:g.id});}

    },
    hit(x,y){const h=hits.find(h=>Math.hypot(h.x-x,h.y-y)<16);if(!h)return false;selected=h.id;panel.classList.add('open');show();return true;}
  };
  async function poll(){try{const r=await fetch('/api/centre/flow');if(r.ok){state=await r.json();show();window.dispatchEvent(new CustomEvent('mosaic:gate-flow'));}}catch(e){console.debug('Flow board unavailable',e);}finally{setTimeout(poll,3000);}}
  poll();
})();
