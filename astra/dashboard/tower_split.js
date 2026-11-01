/* Compact airport chart with stand traffic throughout each surface journey. */
(()=>{
  'use strict';
  const NS='http://www.w3.org/2000/svg',geometry=window.MosaicTowerView,radar=window.MosaicTowerRadarGeometry;
  function svg(tag,attrs={},text){const e=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;return e;}
  const planePath='M0,-8 L1.5,-2 L7,2 L7,4 L1.5,2 L1.5,6 L3,8 L0,7 L-3,8 L-1.5,6 L-1.5,2 L-7,4 L-7,2 L-1.5,-2 Z';
  class SplitTower {
    constructor(container,layout,callbacks){
      this.container=container;this.layout=layout;this.callbacks=callbacks;this.nodes=new Map(layout.nodes.map(n=>[n.id,n]));
      this.surface=geometry.surfaceLayout(layout);
      this.reference=layout.display_reference||radar.DEFAULT_REFERENCE;
      this.chart=window.MosaicTowerChartGeometry.build(layout,this.surface,{preserveGeometry:true});
      this.aircraft=[];this.selected='';this.options={};this.panes=[];this.gesture=null;
      for(const [id,title] of [['ils','ILS · 25R / 25L'],['apron','APRON'],['airport','VVTS · TOWER']]){
        const section=document.createElement('section');section.className='split-pane';section.dataset.pane=id;
        const header=document.createElement('div');header.className='split-heading';
        const identity=document.createElement('div');identity.className='chart-identity';
        const label=document.createElement('strong');label.textContent=title;
        identity.append(label);header.append(identity);
        const controls=document.createElement('div');controls.className='split-controls';header.append(controls);
        const canvas=svg('svg',{'class':'split-map','aria-label':title});
        const pane={id,section,canvas,ils:id==='ils',range:12,autoFit:true,camera:{center:{x:700,y:400},span:1800,up:0},nav:svg('g'),routes:svg('g'),traffic:svg('g'),drag:svg('g'),overlay:svg('g'),markers:new Map()};
        const defs=svg('defs'),clip=svg('clipPath',{id:`split-${id}-clip`});pane.clipRect=svg('rect');clip.append(pane.clipRect);defs.append(clip);canvas.append(defs);
        const arrow=svg('marker',{id:'chart-route-arrow',markerWidth:6,markerHeight:6,refX:5,refY:3,orient:'auto',markerUnits:'userSpaceOnUse'});arrow.append(svg('path',{d:'M0,0 L6,3 L0,6 Z','class':'chart-route-arrow'}));defs.append(arrow);
        pane.navLines=svg('g',{'clip-path':`url(#split-${id}-clip)`});pane.routes.setAttribute('clip-path',`url(#split-${id}-clip)`);
        pane.traffic.setAttribute('clip-path',`url(#split-${id}-clip)`);
        canvas.append(pane.nav,pane.routes,pane.traffic,pane.drag,pane.overlay);section.append(header,canvas);
        const legend=document.createElement('div');legend.className='chart-legend';
        for(const [cls,text] of [['runway','Runway'],['taxiway','Taxiway'],['route','Selected route']]){const item=document.createElement('span'),swatch=document.createElement('i');swatch.className=cls;item.append(swatch,document.createTextNode(text));legend.append(item);}section.append(legend);
        container.append(section);this.panes.push(pane);
        const toggle=document.createElement('label');toggle.className='pane-ils-toggle';const check=document.createElement('input');check.type='checkbox';check.checked=pane.ils;check.setAttribute('aria-label',`Show ILS in ${title}`);
        check.onchange=()=>{pane.ils=check.checked;this.fit(pane);};toggle.append(check,document.createTextNode('ILS'));controls.append(toggle);const labels=document.createElement('label'),lc=document.createElement('input');lc.type='checkbox';lc.checked=true;lc.setAttribute('aria-label',title+' aircraft labels');lc.onchange=()=>{pane.hideAircraftLabels=!lc.checked;this.render(this.aircraft,this.selected,this.options);};labels.append(lc,document.createTextNode('Labels'));controls.append(labels);
        const range=document.createElement('select');range.setAttribute('aria-label',`${title} ILS range`);
        for(const nm of [8,12,20]){const option=document.createElement('option');option.value=nm;option.textContent=`${nm} NM`;option.selected=nm===12;range.append(option);}range.onchange=()=>{pane.range=Number(range.value);this.fit(pane);};controls.append(range);
        const upLabel=document.createElement('label');upLabel.className='pane-bearing';upLabel.append(document.createTextNode('UP '));const bearing=document.createElement('input');bearing.type='number';bearing.min=0;bearing.max=359;bearing.step=1;bearing.value='0';bearing.setAttribute('aria-label',`${title} up bearing`);bearing.title='True bearing at the top of this map; 0 is north up';
        bearing.onchange=()=>{const value=Number(bearing.value);if(Number.isFinite(value)){pane.camera.up=((value%360)+360)%360;this.resize();}};bearing.oninput=bearing.onchange;upLabel.append(bearing,document.createTextNode('°'));controls.append(upLabel);
        for(const [action,text] of [['north','N↑'],['fit','Fit'],['out','−'],['in','+']]){
          const button=document.createElement('button');button.type='button';button.textContent=text;button.dataset.action=action;
          button.setAttribute('aria-label',`${action==='north'?'North up':action==='fit'?'Fit':action==='out'?'Zoom out':'Zoom in'} ${title}`);
          button.onclick=()=>{this.activePane=pane;if(action==='north'){pane.camera.up=0;bearing.value='0';this.resize();}else if(action==='fit')this.fit(pane);else this.zoom(pane,action==='in'?1.25:1/1.25);};controls.append(button);
        }
        canvas.addEventListener('contextmenu',event=>event.preventDefault());
        canvas.addEventListener('wheel',event=>{event.preventDefault();this.zoom(pane,event.deltaY<0?1.15:1/1.15,this.pointer(pane,event));},{passive:false});
        canvas.addEventListener('pointerdown',event=>this.down(pane,event));
      }
      container.addEventListener('pointermove',event=>this.move(event));
      container.addEventListener('pointerup',event=>this.up(event));
      container.addEventListener('pointercancel',()=>this.cancel());
      container.addEventListener('pointerleave',()=>this.callbacks.hideTooltip?.());
      this.setLayout('split');new ResizeObserver(()=>this.resize()).observe(container);
    }
    visiblePanes(){return this.panes.filter(p=>!p.section.hidden);}
    setLayout(mode){this.container.dataset.layout=mode;for(const pane of this.panes)pane.section.hidden=mode==='split'?pane.id==='airport':pane.id!=='airport';this.activePane=this.visiblePanes()[0];this.resize();}
    displayPoint(a){return a.operation==='approach'?a:window.MosaicTowerChartGeometry.point(a,this.chart);}
    shows(pane,a){return pane.id==='ils'?(a.operation==='approach'||a.state==='CLIMBING'||(!['PARKED','ARRIVED'].includes(a.state)&&this.displayPoint(a).y<=340)):pane.id==='apron'?a.operation!=='approach':true;}
    fitPoints(pane){
      let points=pane.id==='ils'?this.chart.runways.flatMap(r=>r.points):[...this.chart.positions.values()].filter(n=>pane.id!=='apron'||n.type==='stand');
      if(pane.ils){points=points.slice();for(const id of ['n125','n123'])for(const offset of [-2.5,0,2.5])points.push(radar.bearingPoint(this.chart.positions.get(id),this.reference.runway_bearing_deg+180+offset,pane.range*1852/this.reference.metres_per_unit,this.reference));}return points;
    }
    resize(){
      if(!this.container.clientWidth||!this.container.clientHeight)return;
      for(const pane of this.visiblePanes()){
        pane.width=pane.canvas.clientWidth;pane.height=pane.canvas.clientHeight;
        pane.canvas.setAttribute('viewBox',`0 0 ${pane.width} ${pane.height}`);
        for(const [key,value] of Object.entries({x:22,y:22,width:Math.max(1,pane.width-44),height:Math.max(1,pane.height-44)}))pane.clipRect.setAttribute(key,value);
        if(!pane.width||!pane.height)continue;
        if(pane.autoFit)pane.camera=radar.fit(this.fitPoints(pane),pane.width,pane.height,pane.camera.up,this.reference);
        pane.projection=radar.projection(pane.camera,pane.width,pane.height,this.reference,22);
        pane.canvas.dataset.upBearing=String(pane.camera.up);pane.canvas.dataset.span=String(pane.camera.span);
        this.navigation(pane);
      }
      this.render(this.aircraft,this.selected,this.options);
    }
    fit(pane){pane.autoFit=true;this.resize();}
    fitAll(){for(const pane of this.visiblePanes())pane.autoFit=true;this.resize();}
    zoom(pane,factor,point){
      if(!pane.projection)return;
      this.activePane=pane;pane.autoFit=false;pane.camera=radar.zoom(pane.camera,factor,point);this.resize();
    }
    pointer(pane,event){const b=pane.canvas.getBoundingClientRect();return pane.projection.inverse({x:event.clientX-b.left,y:event.clientY-b.top});}
    text(pane,parent,point,label,cls='split-nav-label',priority=false){
      if(!pane.projection.contains(point))return;
      const p=pane.projection.project(point),width=label.length*(cls==='split-runway-label'?8:6)+8;
      const x=Math.max(width/2+6,Math.min(pane.width-width/2-6,p.x)),y=Math.max(13,Math.min(pane.height-5,p.y));
      const runway=cls==='split-runway-label';
      const rect={x:x-width/2,y:y-(runway?14:11),width,height:runway?18:14,runway};
      if(!priority&&pane.labels.some(r=>rect.x<r.x+r.width&&rect.x+width>r.x&&rect.y<r.y+r.height&&y>r.y))return;
      pane.labels.push(rect);parent.append(svg('text',{x,y,'class':cls,'text-anchor':'middle','data-chart-label':label},label));
    }
    polyline(pane,points,cls,parent=pane.nav){
      if(points.length<2)return;
      if(parent===pane.nav)parent=pane.navLines;
      parent.append(svg('polyline',{points:points.map(p=>{const q=pane.projection.project(p);return `${q.x},${q.y}`;}).join(' '),'class':cls}));
    }
    navigation(pane){
      pane.navLines.replaceChildren();pane.nav.replaceChildren(pane.navLines);pane.overlay.replaceChildren();pane.labels=[];
      if(pane.ils)this.drawILS(pane);
      if(this.options.taxiways!==false){
        for(const junction of this.chart.junctions)pane.navLines.append(svg('polygon',{points:junction.map(p=>{const q=pane.projection.project(p);return `${q.x},${q.y}`;}).join(' '),'class':'split-junction'}));
        for(const corridor of this.chart.corridors){
          const points=corridor.points.map(p=>pane.projection.project(p));
          pane.navLines.append(svg('path',{d:window.MosaicTowerChartGeometry.roundedPath(points,5),'class':'split-taxi-edge','data-taxiway':corridor.name}));
        }
        for(const n of this.nodes.values())if(n.type==='stand'){
          const display=this.chart.positions.get(n.id);
          if(!pane.projection.contains(display))continue;
          const p=pane.projection.project(display);
          pane.nav.append(svg('rect',{x:p.x-2,y:p.y-2,width:4,height:4,'class':'split-stand','data-stand':n.id}));
        }
      }
      for(const {name,points} of this.chart.runways){
        this.polyline(pane,points,'split-runway');
        const west=points.reduce((a,b)=>a.x<b.x?a:b),east=points.reduce((a,b)=>a.x>b.x?a:b);
        const side=name.includes('25R')?['07L','25R']:['07R','25L'];
        this.text(pane,pane.nav,{x:west.x,y:west.y-19},side[0],'split-runway-label',true);
        this.text(pane,pane.nav,{x:east.x,y:east.y-19},side[1],'split-runway-label',true);
        for(const end of [west,east]){
          const p=pane.projection.project(end);
          const stripes=svg('g',{transform:`translate(${p.x} ${p.y}) rotate(${this.reference.runway_bearing_deg-270-pane.camera.up})`}),half=pane.id==='ils'?1:5,spacing=pane.id==='ils'?1:3;
          for(let i=0;i<3;i++)stripes.append(svg('line',{x1:end===west?i*spacing:-i*spacing,y1:-half,x2:end===west?i*spacing:-i*spacing,y2:half,'class':'split-threshold'}));pane.nav.append(stripes);
        }
      }
      for(const n of this.nodes.values()){
        const display=this.chart.positions.get(n.id);
        if(n.type!=='hold'||!pane.projection.contains(display))continue;
        const p=pane.projection.project(display);pane.nav.append(svg('line',{x1:p.x-4,y1:p.y,x2:p.x+4,y2:p.y,'class':'split-hold'}));
      }
      if(this.options.taxiways!==false&&pane.camera.span<3500){
        for(const label of this.chart.labels)this.text(pane,pane.nav,label,label.label,'split-nav-label',label.primary);
      }
      const compass=svg('g',{transform:'translate(25 34)','class':'tower-compass','aria-label':`North reference, ${pane.camera.up} degrees true up`}),needle=svg('g',{transform:`rotate(${-pane.camera.up})`}),north=radar.rotate({x:0,y:-20},-pane.camera.up);needle.append(svg('path',{d:'M0,-13 L-4,-4 L0,-6 L4,-4 Z','class':'compass-needle'}),svg('line',{x1:0,y1:-6,x2:0,y2:12,'class':'compass-stem'}));compass.append(needle,svg('text',{x:north.x,y:north.y+3,'text-anchor':'middle'},'N'));pane.overlay.append(compass,svg('text',{x:pane.width-10,y:16,'text-anchor':'end','class':'tower-reference'},`${String(pane.camera.up).padStart(3,'0')}°T UP · RWY 249.1°T`));
      const bar=1852/this.reference.metres_per_unit*pane.projection.scale;if(bar>20&&bar<pane.width*.4)pane.overlay.append(svg('line',{x1:22,y1:pane.height-15,x2:22+bar,y2:pane.height-15,'class':'radar-scale'}),svg('text',{x:22,y:pane.height-21,'class':'split-distance'},'1 NM'));
    }
    drawILS(pane){
      for(const [id,name] of [['n125','25R'],['n123','25L']]){
        const start=this.chart.positions.get(id),course=(this.reference.runway_bearing_deg+180)%360,length=pane.range*1852/this.reference.metres_per_unit,edges=[start,...[-2.5,2.5].map(offset=>radar.bearingPoint(start,course+offset,length,this.reference))];
        pane.navLines.append(svg('polygon',{points:edges.map(p=>{const q=pane.projection.project(p);return `${q.x},${q.y}`;}).join(' '),'class':'ils-fan','data-ils-runway':name}));this.polyline(pane,[start,radar.bearingPoint(start,course,length,this.reference)],'ils-axis');
        for(let nm=2;nm<=pane.range;nm+=2){const at=radar.bearingPoint(start,course,nm*1852/this.reference.metres_per_unit,this.reference),half=6/pane.projection.scale;this.polyline(pane,[radar.bearingPoint(at,course-90,half,this.reference),radar.bearingPoint(at,course+90,half,this.reference)],'ils-tick');if(name==='25R')this.text(pane,pane.nav,{x:at.x,y:at.y-14/pane.projection.scale},`${nm} NM`,'split-distance');}
      }
    }
    render(aircraft,selected,options={}){
      const navChanged=this.selected!==selected||this.options.taxiways!==options.taxiways;
      this.aircraft=aircraft;this.selected=selected;this.options=options;
      for(const pane of this.visiblePanes()){
        if(!pane.projection)continue;
        if(navChanged)this.navigation(pane);
        pane.routes.replaceChildren();pane.traffic.replaceChildren();pane.markers.clear();
        for(const a of aircraft){
          if(options.routes!==false&&a.callsign===selected){
            const route=[this.displayPoint(a)],ids=a.route||[];
            for(let i=(a.seg_idx||0)+1;i<ids.length;i++){
              const n=this.chart.positions.get(ids[i]);if(!n)break;route.push(n);
            }
            this.polyline(pane,route,'split-selected-route',pane.routes);
          }
          if(!geometry.onSurface(a,this.surface))continue;
          const g=svg('g',{'class':'aircraft-symbol split-aircraft','data-callsign':a.callsign,'data-region':pane.id});
          g.setAttribute('aria-label',`${a.callsign} · ${a.state} · ${a.fpl?.stand||a.stand||''}`);
          g.append(svg('title',{},`${a.callsign} · ${a.state} · ${a.fpl?.stand||a.stand||''}`));
          const atStand=['PARKED','ARRIVED'].includes(a.state);
          g.append(svg('circle',{r:atStand?7:14,fill:'transparent'}));
          if(a.callsign===selected)g.append(svg('circle',{r:12,'class':'aircraft-halo'}));
          const circle=svg('circle',{r:atStand?4:7,'class':`aircraft-circle ${a.operation==='dep'?'dep':'arr'}`});
          const plane=svg('path',{d:planePath,'class':'aircraft-plane'});g.append(circle,plane);
          let tag=null;const width=Math.max(108,a.callsign.length*7.5+14);
          if(!pane.hideAircraftLabels && options.labels!==false && !['PARKED','ARRIVED'].includes(a.state)){
            tag=svg('g',{'class':'aircraft-tag split-tag'});tag.append(svg('rect',{width,height:45,rx:4,'class':'tag-plate'}));
            const altitude=a.altitude_ft==null?'GROUND':a.altitude_ft<10000?`${Math.round(a.altitude_ft).toLocaleString()} ft`:`FL${Math.round(a.altitude_ft/100)}`;
            tag.append(svg('text',{x:6,y:13,'class':'tag-name'},a.callsign),svg('text',{x:6,y:27,'class':'tag-data'},altitude),svg('text',{x:6,y:40,'class':'tag-data'},`${Math.round(a.speed_kt||0)} kt${a.distance_nm==null?'':` · ${a.distance_nm.toFixed(1)} NM`}`));g.append(tag);
          }
          pane.traffic.append(g);pane.markers.set(a.callsign,{g,plane,circle,tag,width,scale:atStand?.65:1,atStand});
        }
      }
      this.position(aircraft);
    }
    position(aircraft){
      for(const pane of this.panes)pane.trafficLabels=[];
      for(const pane of this.visiblePanes())for(const a of aircraft){
        if(!geometry.onSurface(a,this.surface))continue;
        if(!pane.projection)continue;
        const marker=pane.markers.get(a.callsign);
        if(!marker){this.render(aircraft,this.selected,this.options);return;}
        const display=this.displayPoint(a),visible=this.shows(pane,a)&&pane.projection.contains(display);marker.g.style.display=visible?'':'none';if(!visible)continue;
        const p=pane.projection.project(display);marker.g.setAttribute('transform',`translate(${p.x} ${p.y})`);
        marker.g.dataset.worldX=a.x;marker.g.dataset.worldY=a.y;
        const target=a.operation==='approach'||a.state==='CLIMBING'?radar.bearingPoint(display,a.heading_deg??this.reference.runway_bearing_deg,10,this.reference):this.chart.positions.get(a.route?.[(a.seg_idx||0)+1]);
        let angle=270;
        if(target){const q=pane.projection.project(target);angle=Math.atan2(q.y-p.y,q.x-p.x)*180/Math.PI+90;}
        const groundScale=a.operation==='approach'?1:Math.max(.2,Math.min(1,2500/pane.camera.span));
        marker.circle.setAttribute('r',(marker.atStand?4:7)*groundScale);
        marker.plane.setAttribute('transform',`rotate(${angle}) scale(${marker.scale*groundScale})`);
        if(marker.tag)marker.tag.style.display=pane.camera.span>3500&&a.operation!=='approach'&&a.callsign!==this.selected?'none':'';
        if(marker.tag){
          const candidates=[[12,-62],[-marker.width-12,-62],[12,14],[-marker.width-12,14],[-marker.width/2,-106],
            [12,60],[-marker.width-12,60],[12,-108],[-marker.width-12,-108],[-marker.width/2,106]];
          const obstacles=[...pane.labels,...pane.trafficLabels];
          const choices=candidates.map(([x,y])=>{x=Math.max(22-p.x,Math.min(x,pane.width-marker.width-22-p.x));y=Math.max(22-p.y,Math.min(y,pane.height-67-p.y));const box={x:p.x+x,y:p.y+y,width:marker.width,height:45};const score=obstacles.reduce((sum,r)=>sum+(r.runway?100:1)*Math.max(0,Math.min(box.x+box.width,r.x+r.width)-Math.max(box.x,r.x))*Math.max(0,Math.min(box.y+box.height,r.y+r.height)-Math.max(box.y,r.y)),0);return {x,y,box,score};});
          choices.sort((a,b)=>a.score-b.score);const chosen=choices[0];pane.trafficLabels.push(chosen.box);marker.tag.setAttribute('transform',`translate(${chosen.x} ${chosen.y})`);
        }
      }
      for(const pane of this.panes)for(const [cs,marker] of pane.markers){if(!aircraft.some(a=>a.callsign===cs&&geometry.onSurface(a,this.surface))){marker.g.remove();pane.markers.delete(cs);}}
    }
    down(pane,event){
      if(event.button!==0&&event.button!==2)return;event.preventDefault();this.activePane=pane;
      const symbol=event.target.closest('.split-aircraft');
      if(event.button===0&&symbol&&this.options.readOnly){this.callbacks.select(symbol.dataset.callsign);return;}
      this.gesture={pane,type:event.button===2||!symbol?'pan':'aircraft',callsign:symbol?.dataset.callsign,startX:event.clientX,startY:event.clientY,point:this.pointer(pane,event),moved:false};
      this.container.setPointerCapture(event.pointerId);
    }
    move(event){
      const drag=this.gesture;if(!drag){this.callbacks.hover?.(event);return;}
      if(drag.type==='pan'){
        if(Math.hypot(event.clientX-drag.startX,event.clientY-drag.startY)<3)return;drag.moved=true;
        const p=this.pointer(drag.pane,event),c=drag.pane.camera;drag.pane.autoFit=false;c.center={x:c.center.x+drag.point.x-p.x,y:c.center.y+drag.point.y-p.y};this.resize();return;
      }
      if(Math.hypot(event.clientX-drag.startX,event.clientY-drag.startY)<6)return;
      drag.moved=true;drag.node=null;
      for(const pane of this.visiblePanes()){
        pane.drag.replaceChildren();const b=pane.canvas.getBoundingClientRect();
        if(event.clientX<b.left||event.clientX>b.right||event.clientY<b.top||event.clientY>b.bottom)continue;
        let best=15;
        for(const n of this.nodes.values()){
          const display=this.chart.positions.get(n.id);
          if(!this.surface.visibleNodes.has(n.id)||!pane.projection.contains(display))continue;const p=pane.projection.project(display),d=Math.hypot(p.x+b.left-event.clientX,p.y+b.top-event.clientY);
          if(d<best){best=d;drag.node=n;}
        }
        if(drag.node){const p=pane.projection.project(this.chart.positions.get(drag.node.id));pane.drag.append(svg('circle',{cx:p.x,cy:p.y,r:9,'class':'drag-target'}));}
      }
    }
    up(event){
      const drag=this.gesture;if(!drag)return;this.cancel();
      if(drag.type==='pan'&&!drag.moved)this.callbacks.select('');
      if(drag.type==='aircraft'){
        if(!drag.moved)this.callbacks.select(drag.callsign);
        else if(drag.node)this.callbacks.reroute(drag.callsign,drag.node,event.shiftKey);
      }
    }
    cancel(){this.gesture=null;for(const pane of this.panes)pane.drag.replaceChildren();}
  }
  window.MosaicSplitTower=SplitTower;
})();
