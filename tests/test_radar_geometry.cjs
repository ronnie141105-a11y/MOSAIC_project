const assert = require('node:assert/strict');
const {normalize, zoom} = require('../astra/dashboard/radar_geometry.js');
const cos = Math.cos(10.818333*Math.PI/180);
for (const [w,h] of [[1200,600],[600,1200],[800,800]]) {
    let b = normalize({minLat:9,maxLat:12,minLon:105,maxLon:108},w,h);
    const x=w*.28,y=h*.72;
    const anchor = b => [b.minLon+x/w*(b.maxLon-b.minLon),b.maxLat-y/h*(b.maxLat-b.minLat)];
    const initial = anchor(b);
    for (const factor of [...Array(100).fill(1/1.15),...Array(200).fill(1.15)]) {
        b=zoom(b,w,h,x,y,factor,.02,30);
        const current=anchor(b);
        assert.ok(Math.abs(current[0]-initial[0])<1e-10);
        assert.ok(Math.abs(current[1]-initial[1])<1e-10);
        assert.ok(Math.abs((b.maxLon-b.minLon)*cos/(b.maxLat-b.minLat)-w/h)<1e-9);
    }
}
console.log('Radar geometry: 900 zoom/limit/anchor/aspect checks passed.');
