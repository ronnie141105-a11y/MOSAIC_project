/* Display ownership only. Flight motion and identity stay on the shared server. */
(function(root){
 'use strict';
 function distance(p,b){const rad=Math.PI/180,a=p.lat*rad,c=b.lat*rad,d=(b.lat-p.lat)*rad,e=(b.lon-p.lon)*rad;return 6880.13*Math.asin(Math.sqrt(Math.min(1,Math.sin(d/2)**2+Math.cos(a)*Math.cos(c)*Math.sin(e/2)**2)));}
 function classify(ac,profile,b){
  const d=distance(ac,b),through=profile?.flight_type==='OVERFLIGHT';
  const owner=profile?.direction==='inbound'&&typeof profile.approach_transfer_complete==='boolean'
   ?(profile.approach_transfer_complete?'APPROACH':'CENTRE'):(through||d>b.radius_nm?'CENTRE':'APPROACH');
  return {owner,distance_nm:d,centre_opacity:owner==='CENTRE'?1:ac.altitude_ft>=7000?.7:0,
   approach_opacity:owner==='APPROACH'?1:profile?.direction==='outbound'&&!through?Math.max(0,(b.radius_nm+4-d)/4):0};
 }
 function opacity(ac,profile,b,view){const c=classify(ac,profile,b);return view==='centre'?c.centre_opacity:c.approach_opacity;}
 function segments(points,b,view){
  if(!b||view==='centre')return [points];
  const scale=60*Math.cos(b.lat*Math.PI/180),radius=b.radius_nm;
  const result=[];let line=[];
  for(let i=1;i<points.length;i++){
   const a=points[i-1],z=points[i],x=(a.lon-b.lon)*scale,y=(a.lat-b.lat)*60,dx=(z.lon-a.lon)*scale,dy=(z.lat-a.lat)*60;
   const A=dx*dx+dy*dy,B=2*(x*dx+y*dy),C=x*x+y*y-radius*radius,D=B*B-4*A*C;
   const cuts=[0,1];if(A>0&&D>0){for(const t of [(-B-Math.sqrt(D))/(2*A),(-B+Math.sqrt(D))/(2*A)])if(t>0&&t<1)cuts.push(t);}cuts.sort((a,b)=>a-b);
   const at=t=>({lat:a.lat+(z.lat-a.lat)*t,lon:a.lon+(z.lon-a.lon)*t});
   for(let k=1;k<cuts.length;k++){
    const m=(cuts[k]+cuts[k-1])/2,inside=(x+dx*m)**2+(y+dy*m)**2<=radius*radius;
    if((view==='approach')===inside){
     const start=at(cuts[k-1]),end=at(cuts[k]);
     if(!line.length)line.push(start);line.push(end);
    }else if(line.length){result.push(line);line=[];}
   }
  }
  if(line.length)result.push(line);return result;
 }
 function routeSegments(points,b,view,profile,transfers={}){
  if(view!=='centre'||profile?.direction!=='inbound'||!b)return segments(points,b,view);
  if(profile.approach_transfer_complete===true)return [];
  const point=profile.approach_transfer_position;
  const gate=point?{lat:point[0],lon:point[1],radius_nm:distance({lat:point[0],lon:point[1]},b)}:transfers[profile.procedure_id]||{radius_nm:b.radius_nm};
  if(!points.length||distance(points[0],b)<gate.radius_nm-1e-6)return [];
  const result=[points[0]];
  for(let i=1;i<points.length;i++){
   const a=points[i-1],z=points[i];
   if(gate.lat!==undefined&&distance(z,{lat:gate.lat,lon:gate.lon})<.02){result.push(z);return result.length>1?[result]:[];}
   // Only the prefix to the first inward crossing belongs on Centre.
   const length=distance(a,{lat:z.lat,lon:z.lon});
   const steps=Math.max(1,Math.ceil(length));let previous=0;
   const at=t=>({lat:a.lat+(z.lat-a.lat)*t,lon:a.lon+(z.lon-a.lon)*t});
   for(let j=1;j<=steps;j++){
    const t=j/steps;
    if(distance(at(t),b)<gate.radius_nm){
     let low=previous,high=t;
     for(let n=0;n<35;n++){const mid=(low+high)/2;if(distance(at(mid),b)>=gate.radius_nm)low=mid;else high=mid;}
     result.push(at((low+high)/2));return [result];
    }
    previous=t;
   }
   result.push(z);
  }
  return result.length>1?[result]:[];
 }
 const api={distance,classify,opacity,segments,routeSegments};if(typeof module!=='undefined')module.exports=api;else root.MosaicControlAreas=api;
})(typeof window==='undefined'?globalThis:window);
