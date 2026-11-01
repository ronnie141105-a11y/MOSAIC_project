/* Observed-position trails, limited by flown distance in nautical miles. */
(function(root) {
    function distanceNm(a,b) {
        const rad=Math.PI/180,la=a.lat*rad,lb=b.lat*rad;
        const h=Math.sin((lb-la)/2)**2+Math.cos(la)*Math.cos(lb)*Math.sin((b.lon-a.lon)*rad/2)**2;
        return 6880.13*Math.asin(Math.sqrt(Math.min(1,h)));
    }
    function clipTrailNm(points,limit=10) {
        if(!points.length)return [];
        const result=[points[0]];let remaining=limit;
        for(let i=1;i<points.length&&remaining>1e-8;i++) {
            const a=result[result.length-1],b=points[i],d=distanceNm(a,b);
            if(d<1e-9)continue;
            if(d<=remaining)result.push(b);
            else {const f=remaining/d;result.push({lat:a.lat+(b.lat-a.lat)*f,lon:a.lon+(b.lon-a.lon)*f});}
            remaining-=d;
        }
        return result;
    }
    function color(direction, fallback) {
        return direction === 'outbound' ? '#42e582' : direction === 'inbound' ? '#49b8ff' : fallback;
    }
    function clipTrail(points, limit=600) {
        const result=points.length ? [points[0]] : [];
        let remaining=limit;
        for(let i=1;i<points.length && remaining>0;i++) {
            const a=result[result.length-1],b=points[i],d=Math.hypot(b[0]-a[0],b[1]-a[1]);
            if(!d) continue;
            const fraction=Math.min(1,remaining/d);
            result.push([a[0]+(b[0]-a[0])*fraction,a[1]+(b[1]-a[1])*fraction]);
            remaining-=d;
        }
        return result;
    }
    class History {
        constructor(){this.time=null;this.paths=new Map();}
        seed(payload){
            if(!payload || !payload.paths || typeof payload.paths!=='object')return;
            this.time=payload.timestamp_s ?? null;
            this.paths=new Map(Object.entries(payload.paths).map(([id,points])=>[
                id,Array.isArray(points) ? points.filter(p=>Number.isFinite(p.lat) && Number.isFinite(p.lon)).slice(-1800) : []
            ]));
        }
        observe(snapshot){
            const time=snapshot.timestamp_s;
            if(this.time!==null && time<this.time)this.paths.clear();
            const alive=new Set(snapshot.aircraft.map(a=>a.callsign));
            for(const id of this.paths.keys())if(!alive.has(id))this.paths.delete(id);
            for(const ac of snapshot.aircraft){
                let path=this.paths.get(ac.callsign)||[];
                const previous=path[path.length-1];
                // A large discontinuity is a respawn/reset, not flown track.
                if(previous && Math.hypot(ac.lat-previous.lat,ac.lon-previous.lon)>.1)path=[];
                const point={lat:ac.lat,lon:ac.lon,time_s:time};
                if(previous && previous.time_s===time)path[path.length-1]=point;
                else path.push(point);
                this.paths.set(ac.callsign,path.slice(-1800));
            }
            this.time=time;
        }
        trail(ac,project){
            const path=this.paths.get(ac.callsign)||[];
            return clipTrailNm([ac,...path.slice(0,-1).reverse()]).map(p=>project(p.lat,p.lon));
        }
        stats(callsign){
            const path=this.paths.get(callsign)||[];
            return {samples:path.length,start_time_s:path[0]?.time_s ?? null};
        }
    }
    const api={color,clipTrail,clipTrailNm,distanceNm,History};
    if(typeof module!=='undefined')module.exports=api;else root.AstraTrafficStyle=api;
})(typeof window==='undefined'?globalThis:window);
