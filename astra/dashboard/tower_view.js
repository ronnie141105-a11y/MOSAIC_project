/* Tower display geometry and interpolation. Never changes simulation time or speed. */
(function(root){
  'use strict';
  const BOUNDS={x:0,y:0,width:1820,height:965};
  function orientation(mode,width,height){return mode==='vertical'||(mode==='auto'&&height>width*1.15)?90:0;}
  function fitBounds(angle){
    return angle===90?{x:427.5,y:-427.5,width:965,height:1820}:{...BOUNDS};
  }
  const SPLIT_BOUNDS={runway:{x:0,y:165,width:1820,height:220},ground:{x:0,y:345,width:1421,height:445}};
  function splitRegion(a){return a.operation==='approach'||a.state==='CLIMBING'||a.y<=365?'runway':'ground';}
  function projection(bounds,width,height,padding=22){
    const sx=Math.max(1,width-padding*2)/bounds.width,sy=Math.max(1,height-padding*2)/bounds.height;
    return {sx,sy,
      project:p=>({x:padding+(p.x-bounds.x)*sx,y:padding+(p.y-bounds.y)*sy}),
      inverse:p=>({x:bounds.x+(p.x-padding)/sx,y:bounds.y+(p.y-padding)/sy}),
      contains:p=>p.x>=bounds.x&&p.x<=bounds.x+bounds.width&&p.y>=bounds.y&&p.y<=bounds.y+bounds.height};
  }
  function pathBetween(from,to,nodes){
    const points=[from];
    const sameRoute=from.route?.length&&from.route.length===to.route?.length&&from.route.every((id,i)=>id===to.route[i]);
    if(sameRoute&&to.seg_idx>=from.seg_idx&&from.operation===to.operation){
      for(let i=from.seg_idx+1;i<=to.seg_idx;i++){
        const node=nodes.get(to.route[i]);if(node)points.push({...node,seg_idx:i});
      }
    }
    points.push(to);return points;
  }
  const CHART_BOUNDS={x:0,y:160,width:1440,height:590};
  function chartProjection(bounds,width,height){
    const drawingHeight=Math.min(height,Math.max(100,width*1.08)),offset=(height-drawingHeight)/2;
    const base=projection(bounds,width,drawingHeight);
    return {...base,project:p=>{const q=base.project(p);return {...q,y:q.y+offset};},
      inverse:p=>base.inverse({...p,y:p.y-offset})};
  }
  function surfaceLayout(layout){
    const nodes=new Map(layout.nodes.map(n=>[n.id,n])),paths=[],edges=new Set(),visibleNodes=new Set();
    const key=(a,b)=>[a,b].sort().join(':');
    for(const path of layout.paths){
      if(path.type!=='taxiway'&&path.type!=='runway')continue;
      let chain=[];
      const finish=()=>{if(chain.length>1){paths.push({...path,name:path.name==='TWY-v'?'TWY-V':path.name,ids:chain});for(let i=1;i<chain.length;i++)edges.add(key(chain[i-1],chain[i]));chain.forEach(n=>visibleNodes.add(n));}chain=[];};
      for(const id of path.ids){if(nodes.get(id)?.type==='stand')finish();else chain.push(id);}finish();
    }
    return {paths,edges,visibleNodes,key};
  }
  function onSurface(a,surface){
    if(a.operation==='approach'||a.state==='CLIMBING')return true;
    // Stands and their connecting spurs are part of the traffic display even
    // though the compact chart simplifies the taxiway background.
    return a.state!=='DEPARTED'&&Number.isFinite(a.x)&&Number.isFinite(a.y);
  }
  function alongPath(points,fraction){
    const lengths=points.slice(1).map((p,i)=>Math.hypot(p.x-points[i].x,p.y-points[i].y));
    let remaining=lengths.reduce((a,b)=>a+b,0)*Math.max(0,Math.min(1,fraction));
    for(let i=0;i<lengths.length;i++){
      const length=lengths[i];
      if(remaining<length){const t=remaining/length,a=points[i],b=points[i+1];return {x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t,seg_idx:a.seg_idx};}
      remaining-=length;
    }
    const last=points[points.length-1];return {x:last.x,y:last.y,seg_idx:last.seg_idx};
  }
  class Motion {
    constructor(){this.entries=new Map();this.time=null;this.key=null;this.running=false;this.started=0;this.duration=0;}
    update(aircraft,time,running,key,now,nodes){
      if(time===this.time&&key===this.key&&running===this.running){
        this.entries=new Map(aircraft.map(a=>[a.callsign,{target:a,path:running&&this.entries.has(a.callsign)?this.entries.get(a.callsign).path:[a]}]));
        return;
      }
      const current=new Map(this.sample(now).map(a=>[a.callsign,a]));
      const smooth=running&&this.running&&key===this.key&&time>this.time;
      this.duration=smooth?Math.max(100,Math.min(1200,now-this.started)):0;
      this.started=now;this.time=time;this.running=running;this.key=key;
      this.entries=new Map(aircraft.map(a=>{
        const previous=current.get(a.callsign);
        return [a.callsign,{target:a,path:smooth&&previous?pathBetween(previous,a,nodes):[a]}];
      }));
    }
    sample(now){
      const t=this.duration?Math.min(1,(now-this.started)/this.duration):1;
      return [...this.entries.values()].map(e=>({...e.target,...alongPath(e.path,t)}));
    }
  }
  const api={orientation,fitBounds,SPLIT_BOUNDS,splitRegion,projection,CHART_BOUNDS,chartProjection,surfaceLayout,onSurface,pathBetween,alongPath,Motion};
  if(typeof module!=='undefined')module.exports=api;else root.MosaicTowerView=api;
})(typeof window==='undefined'?globalThis:window);
