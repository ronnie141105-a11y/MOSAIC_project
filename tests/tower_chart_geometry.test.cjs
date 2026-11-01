const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {surfaceLayout}=require('../astra/dashboard/tower_view.js');
const {build,point,roundedPath}=require('../astra/dashboard/tower_chart_geometry.js');
const layout=JSON.parse(fs.readFileSync(path.join(__dirname,'../astra/airport/vvts_layout.json'),'utf8'));
const surface=surfaceLayout(layout),chart=build(layout,surface);

test('every stand remains inside the chart before taxi and after arrival parking',()=>{
 const {onSurface,CHART_BOUNDS}=require('../astra/dashboard/tower_view.js');
 for(const n of layout.nodes.filter(n=>n.type==='stand'))for(const state of ['PARKED','ARRIVED']){
  const a={callsign:'STAND01',operation:state==='PARKED'?'dep':'arr',state,route:[n.id],seg_idx:0,x:n.x,y:n.y,speed_kt:0};
  assert(onSurface(a,surface));const p=point(a,chart);
  assert(p.x>=CHART_BOUNDS.x&&p.x<=CHART_BOUNDS.x+CHART_BOUNDS.width);
  assert(p.y>=CHART_BOUNDS.y&&p.y<=CHART_BOUNDS.y+CHART_BOUNDS.height);
 }
});
test('display straightens the main corridors without changing source nodes',()=>{
 const original=JSON.stringify(layout);build(layout,surface);assert.equal(JSON.stringify(layout),original);
 for(const [id,y] of [['p25',396],['p50',438],['p142',486],['p250',333],['p261',205]]){
  const path=surface.paths.find(p=>p.id===id);assert(path.ids.every(n=>chart.positions.get(n).y===y));
 }
});
test('merged roads retain every original surface connection',()=>{
 const key=(a,b)=>[a,b].sort().join(':'),expected=new Set(),actual=new Set();
 for(const p of surface.paths)if(p.type!=='runway')for(let i=1;i<p.ids.length;i++)expected.add(key(p.ids[i-1],p.ids[i]));
 for(const p of chart.corridors)for(let i=1;i<p.ids.length;i++)actual.add(key(p.ids[i-1],p.ids[i]));
 assert.deepEqual(actual,expected);
});
test('moving aircraft map onto the same organized edge as its route',()=>{
 for(const ids of [['n164','n107'],['n248','n247'],['n219','n266'],['n228','n227']]){
  const a=chart.original.get(ids[0]),b=chart.original.get(ids[1]),first=chart.positions.get(ids[0]),last=chart.positions.get(ids[1]);
  for(const fraction of [0,.3,1]){
   const ac={callsign:'TAXI22',route:ids,seg_idx:0,x:a.x+(b.x-a.x)*fraction,y:a.y+(b.y-a.y)*fraction,speed_kt:22};
   const result=point(ac,chart);assert(Math.abs(result.x-first.x-(last.x-first.x)*fraction)<1e-6);assert(Math.abs(result.y-first.y-(last.y-first.y)*fraction)<1e-6);assert.equal(result.speed_kt,22);
  }
 }
});
test('reference labels include the previously missing connecting taxiways',()=>{
 const labels=new Set(chart.labels.filter(p=>p.primary).map(p=>p.label));
 for(const label of ['P1','P2','P3','P4','P5','P6','S','S1','S3','S4','S5','S6','S7','S8','S9','S10','V','V1','Y','Y1','Y2','Y3','Y4','Y6','Y7','Y8'])assert(labels.has(label));
 assert(chart.corridors.some(c=>c.name==='S1'));assert(chart.corridors.some(c=>c.name==='S10'));
});
test('rounded corridor paths handle repeated points without invalid coordinates',()=>{
 const d=roundedPath([{x:0,y:0},{x:10,y:0},{x:10,y:0},{x:10,y:10},{x:20,y:10}]);assert(d.includes('Q'));assert(!/NaN|Infinity/.test(d));
});
