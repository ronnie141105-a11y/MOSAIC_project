/* Animate distinct simulation snapshots at their selected playback rate. */
(function(root) {
    class Motion {
        constructor() {
            this.entries=new Map();this.time=null;this.key=null;
            this.running=false;this.multiplier=null;this.started=0;this.duration=0;
        }
        update(snapshot,{running=true,multiplier=null,key='',now=performance.now()}={}) {
            const rate=Number.isFinite(multiplier)&&multiplier>0?multiplier:null;
            const same=this.time===snapshot.timestamp_s&&this.key===key&&this.running===running&&this.multiplier===rate;
            if(same) {
                // Supervisor also sends frames between simulation ticks. Preserve
                // the current animation's origin and clock on those duplicates.
                this.entries=new Map(snapshot.aircraft.map(target=>{
                    const old=this.entries.get(target.callsign);
                    const unchanged=old&&old.target.lat===target.lat&&old.target.lon===target.lon;
                    return [target.callsign,{target,from:unchanged?old.from:target}];
                }));
                return;
            }
            const current=new Map(this.sample(now).map(ac=>[ac.callsign,ac]));
            const smooth=running&&this.running&&this.key===key&&rate===this.multiplier&&this.time!==null&&snapshot.timestamp_s>this.time;
            this.duration=smooth?(rate?(snapshot.timestamp_s-this.time)*1000/rate:Math.max(1,now-this.started)):0;
            this.started=now;this.time=snapshot.timestamp_s;this.key=key;
            this.running=running;this.multiplier=rate;
            this.entries=new Map(snapshot.aircraft.map(target=>[target.callsign,{
                target,from:smooth?(current.get(target.callsign)||target):target
            }]));
        }
        sample(now=performance.now()) {
            const fraction=this.duration?Math.max(0,Math.min(1,(now-this.started)/this.duration)):1;
            return [...this.entries.values()].map(({from,target})=>({...target,
                lat:from.lat+(target.lat-from.lat)*fraction,
                lon:from.lon+(target.lon-from.lon)*fraction,
                heading_deg:((from.heading_deg||0)+(((target.heading_deg||0)-(from.heading_deg||0)+540)%360-180)*fraction+360)%360
            }));
        }
    }
    const api={Motion};
    if(typeof module!=='undefined')module.exports=api;else root.MosaicRadarMotion=api;
})(typeof window==='undefined'?globalThis:window);
