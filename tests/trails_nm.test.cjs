const {test}=require('node:test');
const assert=require('node:assert/strict');
const {clipTrailNm,distanceNm,History}=require('../astra/dashboard/traffic_style.js');
test('trail follows bends for ten nautical miles independent of zoom',()=>{
 const points=[{lat:11,lon:107},{lat:11.1,lon:107},{lat:11.1,lon:107.2},{lat:11.5,lon:107.2}];
 const clipped=clipTrailNm(points);
 const total=clipped.slice(1).reduce((s,p,i)=>s+distanceNm(clipped[i],p),0);
 assert(Math.abs(total-10)<.001);assert(clipped.length<points.length);
 const history=new History();history.seed({timestamp_s:3,paths:{A:[...points].reverse().map((p,i)=>({...p,time_s:i}))}});
 const ac={callsign:'A',...points[0]};
 const small=history.trail(ac,(lat,lon)=>[lat,lon]);
 const large=history.trail(ac,(lat,lon)=>[lat*10000,lon*10000]);
 assert.equal(small.length,large.length);
 small.forEach((p,i)=>p.forEach((v,k)=>assert(Math.abs(v*10000-large[i][k])<1e-6)));
});
test('stationary points and short histories stay finite',()=>{
 assert.deepEqual(clipTrailNm([]),[]);
 const p={lat:10,lon:106};assert.deepEqual(clipTrailNm([p,p]),[p]);
});
