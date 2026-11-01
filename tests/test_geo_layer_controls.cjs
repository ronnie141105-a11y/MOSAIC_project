const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const context={window:{}};vm.runInNewContext(fs.readFileSync('astra/dashboard/geo_layers.js','utf8')+'\nthis.Manager=GeoLayerManager;',context);
const m=new context.Manager();
m.layers=[
    {id:'firs',toggleable:false,visible:true},
    {id:'centre_firs',toggleable:false,visible:false},
    {id:'a_route',toggleGroup:'a',visible:false},
    {id:'a_fixes',toggleGroup:'a',visible:false},
    {id:'b_route',toggleGroup:'b',visible:false},
    {id:'legacy_layer',visible:true}
];
assert.deepEqual(Array.from(m.getToggleList(),x=>x.id),['a','b','legacy_layer']);
m.setVisible('a',true);
assert.ok(m.layers[2].visible && m.layers[3].visible);
assert.equal(m.layers[4].visible,false);
assert.equal(m.setVisible('firs',false),false);
assert.equal(m.setVisible('centre_firs',true),false);
assert.equal(m.layers[0].visible,true);assert.equal(m.layers[1].visible,false);
assert.equal(m.setVisible('legacy_layer',false),true);
console.log('Layer controls: procedure isolation, fixed visibility and legacy toggles passed.');
