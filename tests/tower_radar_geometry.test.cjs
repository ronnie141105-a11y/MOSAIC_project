const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const radar=require('../astra/dashboard/tower_radar_geometry.js');
const {surfaceLayout}=require('../astra/dashboard/tower_view.js');
const {build}=require('../astra/dashboard/tower_chart_geometry.js');
const layout=JSON.parse(fs.readFileSync(require('node:path').join(__dirname,'../astra/airport/vvts_layout.json'),'utf8'));
const chart=build(layout,surfaceLayout(layout),{preserveGeometry:true});
const all=[...chart.positions.values()];
const heading=(a,b)=>(Math.atan2(b.x-a.x,a.y-b.y)*180/Math.PI+360)%360;

test('both 25 runways retain 249.1 true bearing in narrow, wide and rotated views',()=>{
 for(const [width,height] of [[400,230],[500,500],[1400,700]])for(const up of [0,70,249.1]){
  const camera=radar.fit(all,width,height,up),p=radar.projection(camera,width,height);
  for(const [start,end] of [['n125','n126'],['n123','n124']]){
   const bearing=(heading(p.project(chart.positions.get(start)),p.project(chart.positions.get(end)))+up)%360;
   assert(Math.abs(bearing-249.1)<1e-8);
  }
  for(const n of all){const point=p.project(n),back=p.inverse(point);assert(Math.abs(back.x-n.x)<1e-8&&Math.abs(back.y-n.y)<1e-8);assert(p.contains(n));}
 }
});

test('uniform scale preserves taxi distances and stand geometry after rotation',()=>{
 const camera=radar.fit(all,480,300,35),p=radar.projection(camera,480,300);
 for(const [a,b] of [[all[0],all[1]],[all[8],all[70]],[{x:0,y:0},{x:0,y:100}]]){
  const x=p.project(a),y=p.project(b);
  assert(Math.abs(Math.hypot(x.x-y.x,x.y-y.y)-Math.hypot(a.x-b.x,a.y-b.y)*p.scale)<1e-8);
 }
});

test('arrival latitude/longitude uses the same north reference and threshold as the ground map',()=>{
 const ref=radar.DEFAULT_REFERENCE,camera={center:ref.anchor,span:10000,up:0},p=radar.projection(camera,600,400);
 const threshold=radar.geoToWorld(ref.threshold.lat,ref.threshold.lon,ref),origin=p.project(threshold);
 assert(Math.hypot(threshold.x-ref.anchor.x,threshold.y-ref.anchor.y)<1e-7);
 // Independently specified 1 NM north/east displacements on a 6371 km sphere.
 const degree=1852/6371000*180/Math.PI;
 const north=p.project(radar.geoToWorld(ref.threshold.lat+degree,ref.threshold.lon,ref));
 const east=p.project(radar.geoToWorld(ref.threshold.lat,ref.threshold.lon+degree/Math.cos(ref.threshold.lat*Math.PI/180),ref));
 assert(Math.abs(north.x-origin.x)<1e-8&&north.y<origin.y);
 assert(Math.abs(east.y-origin.y)<1e-8&&east.x>origin.x);
 assert(Math.abs(Math.hypot(north.x-origin.x,north.y-origin.y)-1852/ref.metres_per_unit*p.scale)<1e-7);
});

test('zoom keeps the pointer anchored and leaves the second camera unchanged',()=>{
 const first=radar.fit(all,500,300,30),second=radar.fit(all,500,300,0),saved=JSON.stringify(second);
 const anchor={x:1200,y:500},before=radar.projection(first,500,300).project(anchor);
 const next=radar.zoom(first,1.5,anchor),after=radar.projection(next,500,300).project(anchor);
 assert(Math.hypot(before.x-after.x,before.y-after.y)<1e-8);
 assert.equal(JSON.stringify(second),saved);assert(first.span>next.span);
});
