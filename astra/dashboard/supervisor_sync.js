/* Each embedded monitor renders the same timestamped Supervisor frame. */
(()=>{
 'use strict';
 const active=window.parent!==window&&new URLSearchParams(location.search).get('supervised')==='1';
 let latest=null,callback=null;
 function subscribe(fn){callback=fn;if(latest)fn(latest);if(active)parent.postMessage({type:'mosaic-supervisor-ready'},location.origin);}
 if(active)window.addEventListener('message',event=>{
  if(event.source!==parent||event.origin!==location.origin||event.data?.type!=='mosaic-supervisor-frame')return;
  const frame=event.data.frame;if(latest&&frame.sequence<=latest.sequence)return;
  latest=frame;document.body.dataset.supervisorSequence=String(frame.sequence);
  document.body.dataset.simTime=String(frame.airport.sim_time_s);
  if(callback)callback(frame);
 });
 window.MosaicSupervisorSync={active,subscribe};
})();
