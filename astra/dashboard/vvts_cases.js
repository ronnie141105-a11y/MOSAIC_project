(() => {
  const $ = id => document.getElementById(id);
  let report, index=0, cursor=0, playing=false, tickTime;
  const number=(n,d=1)=>n==null?'Chưa có':Number(n).toFixed(d);
  const local=t=>new Date(t).toLocaleString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh',hour12:false});
  const clock=t=>new Date(t).toLocaleTimeString('en-GB',{timeZone:'Asia/Ho_Chi_Minh',hour12:false});
  const selected=()=>report.cases[index];
  const tr=(body,values)=>{const row=document.createElement('tr');values.forEach(value=>{const cell=document.createElement('td');cell.textContent=value;row.append(cell);});$(body).append(row);};
  function map(frame) {
    const canvas=$('case-map'), box=canvas.getBoundingClientRect(), ratio=window.devicePixelRatio||1;
    canvas.width=box.width*ratio;canvas.height=box.height*ratio;
    const ctx=canvas.getContext('2d');ctx.scale(ratio,ratio);
    const c=selected(), s=c.assessment, scale=Math.min(box.width-80,box.height-80)/260;
    const xy=p=>[box.width/2+(p.lon-s.center_lon)*60*Math.cos(s.center_lat*Math.PI/180)*scale,box.height/2-(p.lat-s.center_lat)*60*scale];
    ctx.strokeStyle='#496476';ctx.lineWidth=1;ctx.setLineDash([5,5]);
    [40,120].forEach(r=>{ctx.beginPath();ctx.arc(box.width/2,box.height/2,r*scale,0,2*Math.PI);ctx.stroke();});ctx.setLineDash([]);
    ctx.fillStyle='#c7d5e2';ctx.font='12px Arial';ctx.fillText('VVTS',box.width/2+8,box.height/2+16);ctx.fillRect(box.width/2-3,box.height/2-3,6,6);
    ctx.fillStyle='#a3b5c7';ctx.fillText('N ↑ · vị trí quan trắc / extrapolation tối đa 30 s',12,22);
    if(!frame || !frame.aircraft.length){ctx.fillText('Chưa có trạng thái sử dụng được tại thời điểm này',24,box.height-22);return;}
    const labels=[];
    frame.aircraft.forEach((ac,i)=>{const [x,y]=xy(ac);if(x<0||y<0||x>box.width||y>box.height)return;
      const color=['#50d6cd','#ffd17a','#95acff','#ed91bd','#b8de85','#f29b86'][i%6];
      ctx.save();ctx.translate(x,y);ctx.rotate(ac.heading_deg*Math.PI/180);ctx.fillStyle=color;ctx.beginPath();ctx.moveTo(0,-8);ctx.lineTo(5,5);ctx.lineTo(-5,5);ctx.closePath();ctx.fill();ctx.restore();
      let textY=y-9;while(labels.some(p=>Math.abs(p.x-x)<75&&Math.abs(p.y-textY)<15))textY+=16;labels.push({x,y:textY});
      ctx.fillStyle=color;ctx.font='11px Arial';ctx.fillText(ac.callsign,x+8,textY);
    });
  }
  function renderFrame(){if(!report)return;const c=selected();let frame=c.frames[Math.min(c.frames.length-1,Math.floor(cursor/report.sample_interval_s))];
    $('timeline').value=cursor;$('clock').textContent=clock(new Date(Date.parse(c.start_utc)+cursor*1000))+' ICT';map(frame);
    $('frame-note').textContent=frame?`Frame ${clock(frame.utc)} ICT · ${frame.usable_aircraft} track có trạng thái · ${frame.tma_aircraft} trong TMA · ${frame.upstream_aircraft} trong 120 NM · complexity ${number(frame.current_complexity)}`:'Chưa có track trong khung giờ này.';
  }
  function choose(){cursor=0;playing=false;$('play').textContent='Phát';const c=selected();$('play').disabled=!c.frames.length;
    $('timeline').disabled=!c.frames.length;$('timeline').max=(Date.parse(c.end_utc)-Date.parse(c.start_utc))/1000-report.sample_interval_s;
    $('case-note').textContent=c.recorded_flights?`${c.recorded_flights} chuyến bay trong tập track mẫu; không phải toàn bộ traffic. Mẫu cuối: ${local(c.last_sample_utc)}.`:'Chưa thu thập đủ dữ liệu để phát lại case thực tế này.';
    $('missing').replaceChildren();c.missing_inputs.forEach(text=>{const li=document.createElement('li');li.textContent=text;$('missing').append(li);});
    $('ctot-note').textContent=c.unverified_ctot?`Có ${c.unverified_ctot.rows} dòng CTOT công khai, timezone chưa xác minh. Chưa dùng để chấm compliance hay tính hiệu quả ATFM.`:'Chưa có bộ CTOT/restriction history đã xác minh cho khung này.';
    $('coverage-rows').replaceChildren();c.bins_15min.forEach(b=>tr('coverage-rows',[clock(b.start_utc),`${b.sampled_frames_with_data}/${b.sampled_frames}`,number(b.peak_tracked_subset,0),number(b.planned_demand,0),number(b.observed_airport_throughput,0),number(b.declared_capacity,0)]));
    $('error-rows').replaceChildren();c.forecast_summary.forEach(r=>tr('error-rows',[r.horizon_s+' s',r.matched_pairs,number(r.mean_horizontal_nm,3)+(r.matched_pairs?' NM':''),number(r.mean_altitude_ft,0)+(r.matched_pairs?' ft':'')]));
    $('weather').replaceChildren();if(!c.weather.length)$('weather').textContent='Chưa có weather observations/forecast phù hợp khung giờ.';
    c.weather.forEach(r=>{const p=document.createElement('p'),pre=document.createElement('pre');p.textContent=r.report_type+(r.observation_utc?' · '+local(r.observation_utc):' · dự báo; issue '+local(r.issue_utc));pre.textContent=r.raw;$('weather').append(p,pre);});
    $('hash').textContent=c.source_quality?'SHA-256 bộ input: '+c.source_quality.source_sha256:'Chưa có bộ track để tính SHA-256.';renderFrame();
  }
  async function load(){try{const response=await fetch('/api/vvts-cases/results');const data=await response.json();if(!response.ok)throw new Error(data.error);report=data;index=0;$('error').hidden=true;
    $('case-cards').replaceChildren();$('case-select').replaceChildren();data.cases.forEach((c,i)=>{const card=document.createElement('article'),h=document.createElement('h2'),state=document.createElement('span'),p=document.createElement('p'),count=document.createElement('strong'),option=document.createElement('option');
      h.textContent=c.label;state.className='state';state.textContent=c.status==='partial'?'Dữ liệu một phần':'Chưa có track';p.textContent=local(c.local_start)+' – '+clock(c.local_end)+' ICT';count.textContent=c.recorded_flights+' chuyến có track · '+c.source_samples_in_window+' mẫu trong khung';card.append(state,h,p,count);$('case-cards').append(card);option.value=i;option.textContent=c.label;$('case-select').append(option);});
    $('limits').replaceChildren();data.limitations.forEach(text=>{const li=document.createElement('li');li.textContent=text;$('limits').append(li);});choose();
  }catch(exc){$('error').textContent=exc.message;$('error').hidden=false;}}
  $('refresh').addEventListener('click',load);$('case-select').addEventListener('change',()=>{index=Number($('case-select').value);choose();});
  $('timeline').addEventListener('input',()=>{cursor=Number($('timeline').value);renderFrame();});$('play').addEventListener('click',()=>{playing=!playing;if(cursor>=Number($('timeline').max))cursor=0;$('play').textContent=playing?'Tạm dừng':'Phát';});window.addEventListener('resize',renderFrame);
  function tick(now){if(tickTime&&playing&&report){cursor=Math.min(Number($('timeline').max),cursor+(now-tickTime)/1000*Number($('speed').value));if(cursor>=Number($('timeline').max)){playing=false;$('play').textContent='Phát';}renderFrame();}tickTime=now;requestAnimationFrame(tick);}
  load();requestAnimationFrame(tick);
})();
