/* Uniform simulated TMA weather footprint; never inferred radar echoes from METAR. */
(() => {
  'use strict';
  const colors = {rain:'#54bde0',strong_wind:'#87b9e8',heavy_rain:'#efbb54',thunderstorm:'#ee8655',low_visibility:'#b5b9ce',severe:'#f16c7c'};
  function circle(center, radiusNm, count=72) {
    const lat=center.lat*Math.PI/180, lon=center.lon*Math.PI/180, d=radiusNm/3440.065;
    return Array.from({length:count+1},(_,i)=>{
      const bearing=i/count*2*Math.PI;
      const a=Math.asin(Math.sin(lat)*Math.cos(d)+Math.cos(lat)*Math.sin(d)*Math.cos(bearing));
      const b=lon+Math.atan2(Math.sin(bearing)*Math.sin(d)*Math.cos(lat),Math.cos(d)-Math.sin(lat)*Math.sin(a));
      return [a*180/Math.PI,b*180/Math.PI];
    });
  }
  function draw(canvas, project, data, horizonMin=0) {
    if (!canvas) return;
    const dpr=window.devicePixelRatio||1, w=canvas.clientWidth, h=canvas.clientHeight;
    canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);
    const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
    const weather=data?.tma_weather, report=data?.weather;
    const expired=weather?.until_s!=null && data.sim_time_s+horizonMin*60>=weather.until_s;
    const active=weather && weather.preset!=='clear' && !expired;
    const legend=document.getElementById('wx-radar-legend');
    if (legend) {
      legend.hidden=!active;
      legend.replaceChildren();
      if(active){const title=document.createElement('strong'),detail=document.createElement('span');title.textContent='SIM WX · '+report.label;detail.textContent='TMA speed & ETA effects';legend.append(title,detail);}
    }
    if (!active || !project) return;
    const color=colors[weather.preset]||'#54bde0';
    const points=circle(weather.center,weather.radius_nm).map(p=>project(...p));
    ctx.save();ctx.beginPath();points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.closePath();
    ctx.globalAlpha=.09;ctx.fillStyle=color;ctx.fill();ctx.globalAlpha=.55;ctx.strokeStyle=color;ctx.lineWidth=1.5;ctx.setLineDash([7,5]);ctx.stroke();ctx.setLineDash([]);
    ctx.clip();ctx.globalAlpha=.13;ctx.strokeStyle=color;ctx.lineWidth=1;
    const stride=weather.preset==='low_visibility'?28:38;
    for(let x=-h;x<w+h;x+=stride){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x+h,h);ctx.stroke();}
    ctx.restore();
    if(weather.wind_direction_deg!=null){
      const [x,y]=project(weather.center.lat,weather.center.lon), angle=(weather.wind_direction_deg+180)*Math.PI/180;
      const dx=Math.sin(angle)*28,dy=-Math.cos(angle)*28;
      ctx.save();ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+dx,y+dy);ctx.stroke();
      const endX=x+dx,endY=y+dy;ctx.beginPath();ctx.moveTo(endX,endY);ctx.lineTo(endX-dx*.3+dy*.16,endY-dy*.3-dx*.16);ctx.lineTo(endX-dx*.3-dy*.16,endY-dy*.3+dx*.16);ctx.closePath();ctx.fill();
      ctx.restore();
    }
  }
  window.MosaicWeatherRadar={circle,draw};
})();
