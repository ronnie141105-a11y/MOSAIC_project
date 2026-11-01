const assert=require('node:assert/strict');
const {color,clipTrail,History}=require('../astra/dashboard/traffic_style.js');
assert.equal(color('outbound','other'),'#42e582');
assert.equal(color('inbound','other'),'#49b8ff');
assert.equal(color(null,'other'),'other');
assert.deepEqual(clipTrail([[0,0],[20,0],[20,20]],30),[[0,0],[20,0],[20,10]]);
for(const scale of [1,2,50,200]) {
    const trail=clipTrail([[0,0],[scale,0],[scale,scale],[scale*2,scale]],30);
    const length=trail.slice(1).reduce((sum,p,i)=>sum+Math.hypot(p[0]-trail[i][0],p[1]-trail[i][1]),0);
    assert.ok(length<=30.000001);
}
const h=new History(),snap=(time,lat)=>({timestamp_s:time,aircraft:[{callsign:'A',lat,lon:106}]});
h.observe(snap(1,10));h.observe(snap(2,10.001));h.observe(snap(2,10.001));
assert.equal(h.paths.get('A').length,2);
const restored=new History();restored.seed({timestamp_s:2,paths:{A:[{lat:10,lon:106,time_s:1},{lat:10.001,lon:106,time_s:2}]}});
restored.observe(snap(3,10.002));assert.equal(restored.paths.get('A').length,3);
assert.equal(restored.stats('A').start_time_s,1);
h.observe(snap(0,10));assert.equal(h.paths.get('A').length,1);
h.observe(snap(1,11));assert.equal(h.paths.get('A').length,1);
h.observe({timestamp_s:2,aircraft:[]});assert.equal(h.paths.size,0);
console.log('Traffic styling: direction colors, longer trail, reload hydration, reset, teleport and removal passed.');
