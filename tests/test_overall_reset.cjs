const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('astra/dashboard/dashboard.js','utf8');
const start=source.indexOf('    function resetToOverallFir()');
const end=source.indexOf('\n    }',start)+6;
const slider={value:'10'},ui={selectedArhacId:'event',displayMode:'event',selectedHorizon:10,selectedAircraftCallsign:'A'};
const noop=()=>{};
vm.runInNewContext(source.slice(start,end)+'\nresetToOverallFir();',{
    ui,document:{getElementById:()=>slider},window:{__astraLastCycle:{}},updateTimeBox:noop,
    syncDisplayModeSelector:noop,updateTimeSliderAlertSegment:noop,renderTracksTable:noop,
    selectTrack:noop,renderEventPanel:noop,renderMap:noop
});
assert.equal(ui.selectedArhacId,null);assert.equal(ui.selectedAircraftCallsign,null);
assert.equal(ui.displayMode,'overall');assert.equal(ui.manualOverallFir,true);
assert.equal(ui.selectedHorizon,0);assert.equal(slider.value,'0');
console.log('Overall reset clears event and aircraft selection, resets time and suppresses automatic reselection.');
