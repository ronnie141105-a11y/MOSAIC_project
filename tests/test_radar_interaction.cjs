const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('astra/dashboard/dashboard.js','utf8');
const start=source.indexOf('    function setupMapInteraction()');
const end=source.indexOf('\n    }',start)+6;
// Hover now uses the shared escaped HTML / altitude formatting helpers.
const helperStart=source.indexOf('    function escapeInfo(');
const helperEnd=source.indexOf('\n    }',source.indexOf('    function aircraftAltitude(',helperStart))+6;
function target() {
    return {events:{},addEventListener(n,fn){(this.events[n]??=[]).push(fn);},
        fire(n,e){for(const fn of this.events[n]||[])fn(e);},
        classList:{add(){},remove(){},toggle(){}},style:{}};
}
for(const dpr of [1,2,3]) {
    const stack=target(),win=target(),hover=target();
    Object.assign(stack,{clientWidth:800,clientHeight:600});
    Object.assign(hover,{offsetWidth:240,offsetHeight:30});
    const canvas={clientWidth:800,clientHeight:600,width:800*dpr,height:600*dpr,
        getBoundingClientRect:()=>({left:20,top:30,width:800,height:600})};
    const cycle={snapshot:{aircraft:[{callsign:'TEST1',altitude_ft:5000,ground_speed_kt:180}]}};
    const ui={view:{minLat:9,maxLat:12,minLon:105,maxLon:109},mapProject:()=>{},selectedAircraftCallsign:null};
    const context={window:win,document:{getElementById:id=>({'map-stack':stack,'map-canvas':canvas,'aircraft-hover-box':hover}[id])},
        ui,MIN_SPAN_DEG:.02,MAX_SPAN_DEG:30,renderMap(){},savePersistedView(){},
        makeProjector(b,w,h){assert.equal(w,800);assert.equal(h,600);return ()=>{};},
        findAircraftAtPixel(c,p,x,y){assert.equal(x,200);assert.equal(y,150);return 'TEST1';}};
    win.__astraLastCycle=cycle;win.AstraRadarGeometry=require('../astra/dashboard/radar_geometry.js');
    vm.runInNewContext(source.slice(helperStart,helperEnd)+'\n'+source.slice(start,end)+'\nsetupMapInteraction();',context);
    const event={clientX:220,clientY:180,button:0,target:{closest:()=>null},preventDefault(){},deltaY:-1};
    stack.fire('mousemove',event);
    assert.equal(hover.innerHTML,'<strong>TEST1</strong><span>5,000 ft</span><span>180 kt</span>');
    stack.fire('mousedown',event);win.fire('mouseup',event);
    assert.equal(ui.selectedAircraftCallsign,'TEST1');
    stack.fire('wheel',event);
    assert.ok(ui.view.maxLat-ui.view.minLat<3);
}
console.log('Radar interaction: hover, click and CSS-pixel zoom passed at DPR 1, 2 and 3.');
