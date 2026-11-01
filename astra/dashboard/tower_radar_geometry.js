/* Equal-scale Tower cameras. Bearings are clockwise from true north. */
(function(root){
  'use strict';
  const DEFAULT_REFERENCE={runway_bearing_deg:249.1,metres_per_unit:2.74,
    threshold:{lat:10.8248555556,lon:106.663175},anchor:{x:1136.6553385,y:205.2403453}};
  const radians=value=>value*Math.PI/180;
  function rotate(p,angle){const c=Math.cos(radians(angle)),s=Math.sin(radians(angle));return {x:p.x*c-p.y*s,y:p.x*s+p.y*c};}
  function bearingPoint(origin,bearing,distance,reference=DEFAULT_REFERENCE){
    const angle=radians(bearing-(reference.runway_bearing_deg-270));
    return {x:origin.x+Math.sin(angle)*distance,y:origin.y-Math.cos(angle)*distance};
  }
  function geoToWorld(lat,lon,reference=DEFAULT_REFERENCE){
    const origin=reference.threshold,earth=6371000;
    const east=radians(lon-origin.lon)*earth*Math.cos(radians((lat+origin.lat)/2));
    const south=-radians(lat-origin.lat)*earth;
    const point=rotate({x:east/reference.metres_per_unit,y:south/reference.metres_per_unit},270-reference.runway_bearing_deg);
    return {x:reference.anchor.x+point.x,y:reference.anchor.y+point.y};
  }
  function projection(camera,width,height,reference=DEFAULT_REFERENCE,padding=16){
    const angle=reference.runway_bearing_deg-270-camera.up;
    const scale=Math.max(1,width-2*padding)/camera.span;
    const project=p=>{const q=rotate({x:p.x-camera.center.x,y:p.y-camera.center.y},angle);return {x:width/2+q.x*scale,y:height/2+q.y*scale};};
    const inverse=p=>{const q=rotate({x:(p.x-width/2)/scale,y:(p.y-height/2)/scale},-angle);return {x:camera.center.x+q.x,y:camera.center.y+q.y};};
    return {scale,project,inverse,contains:p=>{const q=project(p);return q.x>=padding&&q.x<=width-padding&&q.y>=padding&&q.y<=height-padding;}};
  }
  function fit(points,width,height,up=0,reference=DEFAULT_REFERENCE,padding=24){
    const angle=reference.runway_bearing_deg-270-up,rotated=points.map(p=>rotate(p,angle));
    const xs=rotated.map(p=>p.x),ys=rotated.map(p=>p.y);
    const left=Math.min(...xs),right=Math.max(...xs),top=Math.min(...ys),bottom=Math.max(...ys);
    const span=Math.max(right-left,(bottom-top)*Math.max(1,width-2*padding)/Math.max(1,height-2*padding),180)*1.08;
    return {center:rotate({x:(left+right)/2,y:(top+bottom)/2},-angle),span,up};
  }
  function zoom(camera,factor,anchor=camera.center){
    const span=Math.max(120,Math.min(40000,camera.span/factor)),ratio=span/camera.span;
    return {...camera,span,center:{x:anchor.x+(camera.center.x-anchor.x)*ratio,y:anchor.y+(camera.center.y-anchor.y)*ratio}};
  }
  const api={DEFAULT_REFERENCE,rotate,bearingPoint,geoToWorld,projection,fit,zoom};
  if(typeof module!=='undefined')module.exports=api;else root.MosaicTowerRadarGeometry=api;
})(typeof window==='undefined'?globalThis:window);
