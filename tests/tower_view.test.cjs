const {test}=require('node:test');
const assert=require('node:assert/strict');
const {orientation,fitBounds,Motion,SPLIT_BOUNDS,splitRegion,projection,CHART_BOUNDS,chartProjection,surfaceLayout,onSurface}=require('../astra/dashboard/tower_view.js');

test('automatic orientation fits the whole airport in narrow and expanded panels',()=>{
  assert.equal(orientation('auto',540,780),90);
  assert.equal(orientation('auto',1600,780),0);
  assert.equal(orientation('horizontal',540,780),0);
  for(const angle of [0,90]){
    const bounds=fitBounds(angle),rad=angle*Math.PI/180;
    for(const [x,y] of [[0,0],[1820,0],[1820,965],[0,965]]){
      const rx=910+(x-910)*Math.cos(rad)-(y-482.5)*Math.sin(rad);
      const ry=482.5+(x-910)*Math.sin(rad)+(y-482.5)*Math.cos(rad);
      assert(rx>=bounds.x-1e-8&&rx<=bounds.x+bounds.width+1e-8);
      assert(ry>=bounds.y-1e-8&&ry<=bounds.y+bounds.height+1e-8);
    }
  }
});

test('smooth taxi follows the corner and preserves the authoritative speed',()=>{
  const nodes=new Map([['A',{x:0,y:0}],['B',{x:10,y:0}],['C',{x:10,y:10}]]);
  const motion=new Motion(),base={callsign:'TAXI1',operation:'dep',route:['A','B','C'],speed_kt:22};
  motion.update([{...base,x:0,y:0,seg_idx:0}],0,true,'live',0,nodes);
  motion.update([{...base,x:10,y:10,seg_idx:1}],10,true,'live',1000,nodes);
  for(const [time,x,y] of [[1250,5,0],[1500,10,0],[1750,10,5],[2000,10,10]]){
    const a=motion.sample(time)[0];
    assert.equal(a.x,x);assert.equal(a.y,y);assert.equal(a.speed_kt,22);
  }
});

test('duplicate frames do not stall motion; pause and seek snap without drift',()=>{
  const motion=new Motion(),nodes=new Map(),a={callsign:'ARR1',operation:'approach',y:205,seg_idx:0,speed_kt:140};
  motion.update([{...a,x:100}],0,true,'case:1',0,nodes);
  motion.update([{...a,x:200}],10,true,'case:1',1000,nodes);
  motion.update([{...a,x:200}],10,true,'case:1',1200,nodes);
  assert.equal(motion.sample(1500)[0].x,150);
  motion.update([{...a,x:200}],10,false,'case:1',1600,nodes);
  assert.equal(motion.sample(1600)[0].x,200);
  assert.equal(motion.sample(9999)[0].x,200);
  motion.update([{...a,x:200}],10,true,'case:1',1700,nodes);
  motion.update([{...a,x:600}],90,true,'case:2',1800,nodes);
  assert.equal(motion.sample(1800)[0].x,600);
  motion.update([],90,true,'case:2',1900,nodes);
  assert.deepEqual(motion.sample(2000),[]);
});

test('split schematics change proportions independently and invert pointer positions',()=>{
  const runway=projection(SPLIT_BOUNDS.runway,540,360),ground=projection(SPLIT_BOUNDS.ground,540,400);
  assert(runway.sy/runway.sx>3);
  assert(ground.sy/ground.sx>1.5);
  assert.notEqual(runway.sy,ground.sy);
  for(const view of [runway,ground])for(const p of [{x:1366.8985,y:363.553},{x:800,y:500}]){
    const q=view.inverse(view.project(p));assert(Math.abs(q.x-p.x)<1e-8);assert(Math.abs(q.y-p.y)<1e-8);
  }
});

test('one aircraft transfers between surface panels with identity and speed preserved',()=>{
  const a={callsign:'DEP22',operation:'dep',speed_kt:22};
  const positions=[{...a,x:1366,y:410},{...a,x:1366,y:365},{...a,x:1341,y:333}];
  assert.deepEqual(positions.map(splitRegion),['ground','runway','runway']);
  assert(positions.every(p=>p.callsign==='DEP22'&&p.speed_kt===22));
  assert.equal(splitRegion({operation:'approach',y:205}),'runway');
  assert.equal(splitRegion({operation:'dep',state:'CLIMBING',y:400}),'runway');
});

test('compact chart fits both runways and inverts pointer coordinates after aspect changes',()=>{
  const chart=chartProjection(CHART_BOUNDS,550,850);
  assert(chart.sy>chart.sx*2);
  for(const p of [{x:0,y:160},{x:1440,y:750},{x:1366.9,y:363.55}]){
    const q=chart.project(p),back=chart.inverse(q);
    assert(q.x>=0&&q.x<=550&&q.y>=0&&q.y<=850);
    assert(Math.abs(back.x-p.x)<1e-7&&Math.abs(back.y-p.y)<1e-7);
  }
});

test('chart removes stand spurs while preserving S1 access and the V taxiway',()=>{
  const fs=require('node:fs'),path=require('node:path');
  const layout=JSON.parse(fs.readFileSync(path.join(__dirname,'../astra/airport/vvts_layout.json'),'utf8'));
  const original=JSON.stringify(layout),surface=surfaceLayout(layout),nodes=new Map(layout.nodes.map(n=>[n.id,n]));
  assert.equal(surface.paths.filter(p=>p.type==='runway').length,2);
  assert(surface.paths.every(p=>p.ids.every(id=>nodes.get(id).type!=='stand')));
  assert(surface.edges.has(surface.key('n164','n107')));
  assert(surface.edges.has(surface.key('n107','n123')));
  assert(surface.paths.some(p=>p.id==='p50'&&p.name==='TWY-V'));
  assert.equal(JSON.stringify(layout),original);
  const a={callsign:'SURF1',state:'TAXIING',operation:'dep',speed_kt:22,x:1360,y:400,route:['n164','n107','n123'],seg_idx:0};
  assert(onSurface(a,surface));assert.equal(a.speed_kt,22);
  for(const state of ['PARKED','ARRIVED','TAXIING']){
    assert(onSurface({...a,x:600,y:550,state,route:['stand-spur','stand'],seg_idx:0},surface));
  }
  assert.equal(onSurface({...a,x:600,y:550,state:'DEPARTED'},surface),false);
});
