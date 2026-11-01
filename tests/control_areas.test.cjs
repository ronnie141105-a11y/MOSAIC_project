const {test}=require('node:test');
const assert=require('node:assert/strict');
const api=require('../astra/dashboard/control_areas.js');
const b={lat:10.818333333333333,lon:106.65055555555556,radius_nm:40};
test('one owner, gray Centre handoff at 7000 ft, and unrelated overflight stays at Centre',()=>{
 for(const d of [30,38,39.9,40.1,42,50]){
  const a={lat:b.lat+d/60.04,lon:b.lon,altitude_ft:7000};
  const inbound=api.classify(a,{direction:'inbound'},b);
  const outbound=api.classify(a,{direction:'outbound'},b);
  assert.equal(inbound.owner,d<40?'APPROACH':'CENTRE');assert.equal(outbound.owner,inbound.owner);
  if(d<40){assert.equal(inbound.centre_opacity,.7);assert.equal(api.classify({...a,altitude_ft:6999},{direction:'inbound'},b).centre_opacity,0);}
  if(d===42)assert(outbound.approach_opacity>0&&outbound.approach_opacity<1);
 }
 assert.equal(api.classify({lat:b.lat,lon:b.lon},{flight_type:'OVERFLIGHT'},b).owner,'CENTRE');
});
test('Centre retains the full route through TMA; Approach keeps the inside section',()=>{
 const path=[{lat:b.lat-1.5,lon:b.lon},{lat:b.lat+1.5,lon:b.lon}];
 const centre=api.segments(path,b,'centre'),approach=api.segments(path,b,'approach');
 assert.equal(centre.length,1);assert.equal(approach.length,1);
 assert.deepEqual(centre[0],path);
 assert(approach.flat().every(p=>Math.abs(p.lat-b.lat)<=40/60+1e-8));
});

test('only arrival route drawings stop at the named transfer fix or 40 NM circle',()=>{
 const gate={lat:b.lat+.68,lon:b.lon,radius_nm:api.distance({lat:b.lat+.68,lon:b.lon},b)};
 const route=[{lat:b.lat+1.3,lon:b.lon},gate,{lat:b.lat+.3,lon:b.lon},{lat:b.lat,lon:b.lon}];
 const arrival=api.routeSegments(route,b,'centre',{direction:'inbound',procedure_id:'BITIS2H'},{BITIS2H:gate});
 assert.deepEqual(arrival,[[route[0],gate]]);
 assert.deepEqual(api.routeSegments(route,b,'centre',{direction:'outbound'}),[route]);
 assert.deepEqual(api.routeSegments(route.slice(2),b,'centre',{direction:'inbound'}),[]);
 const dalap=api.routeSegments(route,b,'centre',{direction:'inbound',procedure_id:'DALAP2H'});
 assert.equal(dalap.length,1);assert(Math.abs(api.distance(dalap[0].at(-1),b)-40)<1e-6);
 // A STAR can loop back toward the boundary later: never draw a later portion.
 const loop=[...route,{lat:b.lat+1.2,lon:b.lon}];
 assert.deepEqual(api.routeSegments(loop,b,'centre',{direction:'inbound'}),dalap);
});

test('named handoff waits for the actual fix crossing even inside the 40 NM area',()=>{
 const a={lat:b.lat+.5,lon:b.lon,altitude_ft:10000};
 assert.equal(api.classify(a,{direction:'inbound',approach_transfer_complete:false},b).owner,'CENTRE');
 assert.equal(api.classify(a,{direction:'inbound',approach_transfer_complete:true},b).owner,'APPROACH');
 const gate=[b.lat+.5,b.lon],route=[{lat:b.lat+.9,lon:b.lon},a,{lat:b.lat,lon:b.lon}];
 assert.deepEqual(api.routeSegments(route,b,'centre',{direction:'inbound',approach_transfer_position:gate,approach_transfer_complete:true}),[]);
});
