/* Display layout derived from the supplied VVTS chart. Simulation coordinates stay intact. */
(function(root){
  'use strict';
  const ALIASES={p22:'S1',p23:'S1',p26:'S1',p27:'S3',p28:'S9',p29:'S9',p30:'S9',p31:'S10',p32:'S10',p33:'S10',p40:'S5',p41:'S4',p44:'P5',p47:'P5',p48:'P5 / S8',p69:'Y7',p191:'Y4',p192:'Y4',p193:'Y4',p194:'Y4',p195:'Y4',p196:'Y4'};
  const LABELS=[
    ['P1',1178,240],['P2',1020,236],['P3',873,235],['P4',443,233],['P5',352,233],['P6',52,246],
    ['S1',1380,366],['S3',1190,358],['S4',1080,357],['S5',992,357],['S6',803,353],['S7',559,356],['S8',315,357],['S9',88,364],['S10',25,414],
    ['S',604,386],['V',660,428],['V1',708,415],['Y',610,475],['Y1',810,529],['Y2',900,649],['Y3',806,629],['Y4',765,698],['Y6',712,464],['Y7',552,464],['Y8',463,463],
    ['P4',165,259,false],['P5',320,308,false],['P3',1096,259,false],['P2',1008,306,false],['P1',1154,307,false],
    ['S',190,386,false],['S',1100,387,false],['V',258,429,false],['V',1085,429,false],['S5',932,557,false],['Y1',835,583,false]
  ].map(([label,x,y,primary=true])=>({label,x,y,primary}));
  const key=(a,b)=>[a,b].sort().join(':');
  function build(layout,surface,options={}){
    const original=new Map(layout.nodes.map(n=>[n.id,n])),positions=new Map(layout.nodes.map(n=>[n.id,{...n,x:Math.round(n.x),y:Math.round(n.y)}]));
    const row=(ids,y)=>ids.forEach(id=>{const n=positions.get(id);if(n)n.y=y;});
    for(const path of surface.paths){
      if(path.type==='runway')row(path.ids,path.name.includes('25R')?205:333);
      else if(!options.preserveGeometry&&path.id==='p25')row(path.ids,396);
      else if(!options.preserveGeometry&&path.id==='p50')row(path.ids,438);
      else if(!options.preserveGeometry&&(path.id==='p142'||path.id==='p143'))row(path.ids,486);
    }
    if(!options.preserveGeometry){
    row(['n297','n298','n296','n295','n294','n293'],268);
    // Align the long S5 and Y1 corridors; shared nodes remain shared junctions.
    const s5=surface.paths.find(p=>p.id==='p64');
    if(s5)for(const id of s5.ids){const n=positions.get(id);n.x=978+(827-978)*(n.y-396)/(704-396);}
    const y1=['n219','n266','n267','n268','n269','n229'];
    positions.get('n229').y=574;
    for(const id of y1){const n=positions.get(id);n.x=851+(785-851)*(n.y-438)/(574-438);}
    const start=positions.get('n229'),end=positions.get('n226');
    for(const id of ['n228','n227']){const n=positions.get(id),t=(n.x-start.x)/(end.x-start.x);n.y=start.y+(end.y-start.y)*t;}
    // The source graph's cargo loop is drawn as a clean Y4 branch.
    for(const [id,x,y] of [['n249',725,656],['n248',740,663],['n247',755,670],['n246',773,678],['n245',787,685],['n244',800,691]])Object.assign(positions.get(id),{x,y});
    }
    const groups=new Map();
    for(const path of surface.paths){
      if(path.type==='runway')continue;
      const name=ALIASES[path.id]||path.name.replace(/^TWY-/,'').replace(/\.1$|\.2$/,'').toUpperCase();
      if(!groups.has(name))groups.set(name,new Map());const edges=groups.get(name);
      for(let i=1;i<path.ids.length;i++)edges.set(key(path.ids[i-1],path.ids[i]),[path.ids[i-1],path.ids[i]]);
    }
    const corridors=[];
    for(const [name,edges] of groups){
      const adjacency=new Map(),unused=new Set(edges.keys());
      for(const [a,b] of edges.values()){if(!adjacency.has(a))adjacency.set(a,[]);if(!adjacency.has(b))adjacency.set(b,[]);adjacency.get(a).push(b);adjacency.get(b).push(a);}
      const walk=(a,b)=>{
        const ids=[a];let previous=a,current=b;unused.delete(key(a,b));
        while(true){ids.push(current);const neighbors=adjacency.get(current);if(neighbors.length!==2)break;const next=neighbors.find(n=>n!==previous&&unused.has(key(current,n)));if(!next)break;unused.delete(key(current,next));previous=current;current=next;}
        corridors.push({name,ids,points:ids.map(id=>positions.get(id))});
      };
      for(const [id,neighbors] of adjacency)if(neighbors.length!==2)for(const n of neighbors)if(unused.has(key(id,n)))walk(id,n);
      while(unused.size){const [a,b]=edges.get(unused.values().next().value);walk(a,b);}
    }
    const junctions=[['n298','n174','n296','n113'],['n159','n111','n157'],['n158','n156','n220','n219'],['n153','n264','n254'],['n149','n261','n260'],['n168','n165','n128','n137']].map(ids=>ids.map(id=>positions.get(id)));
    const runways=surface.paths.filter(p=>p.type==='runway').map(p=>({name:p.name,points:p.ids.map(id=>positions.get(id))}));
    return {original,positions,corridors,junctions,runways,labels:LABELS};
  }
  function point(a,chart){
    if(a.operation==='approach')return {...a,x:1137+(a.x-1137)*.41,y:205};
    const ids=a.route||[],i=a.seg_idx||0,from=chart.original.get(ids[i]),to=chart.original.get(ids[i+1]),first=chart.positions.get(ids[i]),last=chart.positions.get(ids[i+1]);
    if(from&&to&&first&&last){const dx=to.x-from.x,dy=to.y-from.y,length=dx*dx+dy*dy,t=length?Math.max(0,Math.min(1,((a.x-from.x)*dx+(a.y-from.y)*dy)/length)):0;return {...a,x:first.x+(last.x-first.x)*t,y:first.y+(last.y-first.y)*t};}
    if(first&&a.state!=='CLIMBING')return {...a,x:first.x,y:first.y};
    return a;
  }
  function roundedPath(points,radius=5){
    if(!points.length)return '';
    let d=`M${points[0].x},${points[0].y}`;
    for(let i=1;i<points.length-1;i++){
      const a=points[i-1],b=points[i],c=points[i+1],l1=Math.hypot(b.x-a.x,b.y-a.y),l2=Math.hypot(c.x-b.x,c.y-b.y),r=Math.min(radius,l1/3,l2/3);
      if(!l1||!l2)continue;
      const p={x:b.x+(a.x-b.x)*r/l1,y:b.y+(a.y-b.y)*r/l1},q={x:b.x+(c.x-b.x)*r/l2,y:b.y+(c.y-b.y)*r/l2};
      d+=` L${p.x},${p.y} Q${b.x},${b.y} ${q.x},${q.y}`;
    }
    if(points.length>1){const last=points[points.length-1];d+=` L${last.x},${last.y}`;}return d;
  }
  const api={build,point,roundedPath};if(typeof module!=='undefined')module.exports=api;else root.MosaicTowerChartGeometry=api;
})(typeof window==='undefined'?globalThis:window);
