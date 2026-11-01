const {test}=require('node:test');
const assert=require('node:assert/strict');
const {Motion}=require('../astra/dashboard/radar_motion.js');
const {distanceNm}=require('../astra/dashboard/traffic_style.js');
const degPerNm=180/(Math.PI*3440.065);
const aircraft=(nm,callsign='A001')=>({callsign,lat:nm*degPerNm,lon:106,heading_deg:0,ground_speed_kt:250,altitude_ft:10000});
const frame=(time,nm)=>({timestamp_s:time,aircraft:[aircraft(nm)]});
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-8,`${a} != ${b}`);

for(const rate of [1,5,30,60])test(`250 kt travels the correct distance smoothly at ${rate}x despite duplicate frames`,()=>{
    const motion=new Motion(),distance=250*rate/3600;
    const options=now=>({running:true,multiplier:rate,key:'case:1',now});
    motion.update(frame(0,0),options(0));
    motion.update(frame(rate,distance),options(1000));
    near(distanceNm(aircraft(0),motion.sample(1250)[0]),distance*.25);
    motion.update(frame(rate,distance),options(1500));
    near(distanceNm(aircraft(0),motion.sample(1500)[0]),distance*.5);
    near(distanceNm(aircraft(0),motion.sample(1750)[0]),distance*.75);
    near(distanceNm(aircraft(0),motion.sample(2000)[0]),distance);
    motion.update(frame(rate*2,distance*2),options(2000));
    near(distanceNm(aircraft(0),motion.sample(2500)[0]),distance*1.5);
    assert.equal(motion.sample(2500)[0].ground_speed_kt,250);
});

test('pause, resume, seek, rewind and a rate change do not replay old movement',()=>{
    const m=new Motion();
    const update=(time,nm,now,extra={})=>m.update(frame(time,nm),{running:true,multiplier:30,key:'case:1',now,...extra});
    update(0,0,0);update(30,2,1000);
    update(30,2,1500,{running:false});near(m.sample(50000)[0].lat,aircraft(2).lat);
    update(30,2,51000);near(m.sample(51000)[0].lat,aircraft(2).lat);
    update(60,4,52000);near(m.sample(52500)[0].lat,aircraft(3).lat);
    update(1000,50,52500,{key:'case:2'});near(m.sample(52500)[0].lat,aircraft(50).lat);
    update(0,0,53000,{key:'case:3'});near(m.sample(53500)[0].lat,0);
    update(30,2,54000,{key:'case:3'});
    update(30,2,54500,{key:'case:3',multiplier:60});near(m.sample(54500)[0].lat,aircraft(2).lat);
    update(90,6,55000,{key:'case:3',multiplier:60});near(m.sample(55500)[0].lat,aircraft(4).lat);
});

test('paused edits, new aircraft and removed aircraft apply immediately',()=>{
    const m=new Motion(),options={running:false,multiplier:30,key:'case:1',now:0};
    m.update(frame(0,0),options);
    m.update({timestamp_s:0,aircraft:[aircraft(5),aircraft(10,'D001')]},options);
    assert.deepEqual(m.sample().map(a=>a.lat),[aircraft(5).lat,aircraft(10).lat]);
    m.update({timestamp_s:0,aircraft:[]},options);assert.equal(m.sample().length,0);
});

