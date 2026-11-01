"""Categorical GA on the reviewed video identities and existing TMA paths.

No automatic queue repairs: violations remain in the score and exported replay.
Arrival measures are planned 60 minutes before the window. Departures retain
their recorded-case synthetic schedules. Screen labels are not actual FPLs.
"""
from collections import Counter
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import time

import numpy as np

from astra.airspace import load_profile
from astra.optimization.formulation import OPTIONS, optimize, Evaluator
from astra.studies.case_replay import DEFAULT_ROOT, CASE_IDS
from astra.studies.vvts_cases import utc

VERSION = 'video-categorical-1'
SEEDS = tuple(range(11, 111, 11))


def epoch(value):
    return utc(value).timestamp()


def iso(value):
    return datetime.fromtimestamp(float(value), timezone.utc).isoformat(timespec='seconds')


class VideoCaseEvaluator:
    encode = Evaluator.encode
    decode = Evaluator.decode

    def __init__(self, case_id, root=DEFAULT_ROOT, sample_s=20, capacity=42):
        if case_id not in CASE_IDS:
            raise ValueError('Only the two active video cases may be optimized')
        self.folder = Path(root)/case_id
        self.manifest = json.loads((self.folder/'manifest.json').read_text(encoding='utf-8'))
        self.start = epoch(self.manifest['local_start'])
        self.sample_s = sample_s
        self.capacity = capacity
        self.metadata = {f['callsign']:f for f in self.manifest['flights']}
        with (self.folder/'tracks.csv').open(encoding='utf-8-sig',newline='') as stream:
            self.track_rows = list(csv.DictReader(stream))
        self.paths = {}
        for cs in self.metadata:
            rows = [r for r in self.track_rows if r['callsign']==cs]
            rows.sort(key=lambda r:r['time_utc'])
            self.paths[cs] = np.asarray([[epoch(r['time_utc'])-self.start,float(r['lat']),float(r['lon']),
                float(r['altitude_ft']),float(r['heading_deg'])] for r in rows])
        self.flights = []
        self.domains = []
        self.delays = []
        self.costs = []
        self.arrivals = [f for f in self.manifest['flights'] if f['direction']=='arrival']
        for f in self.arrivals:
            eta = (epoch(f['planned_event_utc'])-self.start)/60
            # The prior scenario provides an assumed 95 minute origin lead.
            takeoff = eta-95
            eligible = takeoff >= -60
            self.flights.append(dict(id=f['callsign'],eta_min=eta,reference_takeoff_min=takeoff,
                travel_to_entry_min=95,ground_eligible=eligible,aircraft_type=f['aircraft_type']))
            self.domains.append(tuple(j for j,(m,level) in enumerate(OPTIONS)
                                      if m!=1 or eligible))
            delay = np.asarray([level if m==1 else 20*level/(100-level) if m==2 else 0 for m,level in OPTIONS])
            self.delays.append(delay)
            self.costs.append(np.asarray([d*(1 if m==1 else 2) for d,(m,_) in zip(delay,OPTIONS)]))
        self.n = len(self.flights)
        self.etas = np.asarray([f['eta_min'] for f in self.flights])
        self.delays, self.costs = np.asarray(self.delays),np.asarray(self.costs)
        self.fixed_departures = [f for f in self.manifest['flights'] if f['direction']=='departure']
        self.fixed_events = np.asarray([(epoch(f['simulated_slot_utc'])-self.start)/60 for f in self.fixed_departures])
        maximum = max(max(p[:,0]) for p in self.paths.values())+1200
        minimum = min(min(p[:,0]) for p in self.paths.values())-1200
        self.timeline = np.arange(math.floor(minimum/sample_s)*sample_s,maximum+sample_s,sample_s)
        samples = []
        for f in self.arrivals:
            path = self.paths[f['callsign']].copy()
            path[:,0] += epoch(f['planned_event_utc'])-epoch(f['simulated_slot_utc'])
            samples.append(self.sample(path,self.delays[len(samples)]*60))
        fixed = [self.sample(self.paths[f['callsign']],np.asarray([0])) for f in self.fixed_departures]
        self.pairs = []
        self.tables = []
        for i in range(self.n):
            for j in range(i+1,self.n):
                self.pairs.append((i,j))
                self.tables.append(self.conflicts(samples[i],samples[j],True))
        self.tables = np.asarray(self.tables,dtype=bool)
        self.pair_i = np.asarray([i for i,j in self.pairs],dtype=int)
        self.pair_j = np.asarray([j for i,j in self.pairs],dtype=int)
        self.arr_dep = np.asarray([[self.conflicts(a,b,False)[:,0] for b in fixed] for a in samples],dtype=bool)
        self.base_pairs = self.tables[:,0,0]
        self.base_arr_dep = self.arr_dep[:,:,0]
        self.input_sha256 = {name:hashlib.sha256((self.folder/name).read_bytes()).hexdigest()
                             for name in ('manifest.json','tracks.csv','flights.csv')}

    def sample(self,path,delays):
        result=[]
        center=load_profile('tsn_tma')['center']
        for shift in delays:
            t=path[:,0]+shift
            values=np.asarray([np.interp(self.timeline,t,path[:,k]) for k in range(1,5)])
            valid=(self.timeline>=t[0]) & (self.timeline<=t[-1]) & (values[2]>=3000) & (values[2]<=16570)
            radius=self.distance(values[0],values[1],center['lat'],center['lon'])
            valid &= radius<=40
            result.append((values,valid))
        return result

    @staticmethod
    def distance(lat1,lon1,lat2,lon2):
        a,b=np.radians(lat1),np.radians(lat2)
        h=np.sin((b-a)/2)**2+np.cos(a)*np.cos(b)*np.sin(np.radians(lon2-lon1)/2)**2
        return 2*3440.065*np.arcsin(np.sqrt(np.clip(h,0,1)))

    def conflicts(self,left,right,arrival_pair):
        a=np.asarray([v for v,valid in left]);b=np.asarray([v for v,valid in right])
        valid=np.asarray([valid for v,valid in left])[:,None,:] & np.asarray([valid for v,valid in right])[None,:,:]
        distance=self.distance(a[:,None,0,:],a[:,None,1,:],b[None,:,0,:],b[None,:,1,:])
        if arrival_pair:
            heading=np.abs((a[:,None,3,:]-b[None,:,3,:]+180)%360-180)
            violation=(distance<10) | ((distance<20) & (heading<=25))
        else:
            violation=(distance<5) & (np.abs(a[:,None,2,:]-b[None,:,2,:])<1000)
        return np.any(valid & violation,axis=-1)

    def state(self,codes):
        indices=np.arange(self.n)
        delays=self.delays[indices,codes]
        events=np.concatenate((self.etas+delays,self.fixed_events))
        events=events[events>=0]  # airborne pre-window departures are not new movements
        bins,counts=np.unique(np.floor(events/60).astype(int),return_counts=True)
        excess=int(np.maximum(counts-self.capacity,0).sum())
        conflicts=self.tables[np.arange(len(self.pairs)),np.asarray(codes)[self.pair_i],np.asarray(codes)[self.pair_j]]
        cross=self.arr_dep[np.arange(self.n)[:,None],np.arange(len(self.fixed_departures))[None,:],np.asarray(codes)[:,None]]
        new=int((conflicts & ~self.base_pairs).sum()+(cross & ~self.base_arr_dep).sum())
        pair_count=int(conflicts.sum()+cross.sum())
        cost=float(self.costs[indices,codes].sum())
        penalty=excess+pair_count+new
        return dict(objective=cost+1000*penalty,cost=cost,penalty=penalty,
                    arrival_pairs=conflicts,cross_pairs=cross,new_pairs=new,
                    capacity_excess=excess,bins=bins,counts=counts,delays=delays)

    def objective(self,codes):
        return self.state(codes)['objective']

    def evaluate(self,plan):
        codes=self.encode(plan)
        state=self.state(codes)
        rows=[]
        for i,(flight,code) in enumerate(zip(self.flights,codes)):
            m,level=OPTIONS[code]
            delay=float(state['delays'][i])
            rows.append(dict(**flight,measure=m,level=level,ground_delay_min=delay if m==1 else 0,
                speed_delay_min=delay if m==2 else 0,total_delay_min=delay,
                adjusted_landing_min=flight['eta_min']+delay,converted_cost=float(self.costs[i,code]),
                upstream_speed_kt=240*(1-level/100) if m==2 else 240))
        metric=dict(objective=state['objective'],converted_cost=state['cost'],penalty=state['penalty'],
            capacity_excess_flights=state['capacity_excess'],arrival_conflict_pairs=int(state['arrival_pairs'].sum()),
            arrival_departure_conflict_pairs=int(state['cross_pairs'].sum()),new_conflict_pairs=state['new_pairs'],
            feasible_sampled=state['penalty']==0,total_delay_min=float(sum(state['delays'])),
            mean_delay_min=float(np.mean(state['delays'])),max_delay_min=float(max(state['delays'])),
            ground_delay_min=sum(r['ground_delay_min'] for r in rows),speed_delay_min=sum(r['speed_delay_min'] for r in rows),
            no_action_flights=sum(c==0 for c in codes),ground_flights=sum(1<=c<=4 for c in codes),
            speed_flights=sum(c>=5 for c in codes),optimized_arrivals=self.n,
            fixed_departures=len(self.fixed_departures))
        audit=dict(arrival_pairs=[[self.flights[i]['id'],self.flights[j]['id']] for (i,j),v in zip(self.pairs,state['arrival_pairs']) if v],
            arrival_departure_pairs=[[self.flights[i]['id'],self.fixed_departures[j]['callsign']]
                for i,j in zip(*np.where(state['cross_pairs']))],
            capacity_bins=[dict(start_min=int(b)*60,count=int(c),capacity=self.capacity)
                           for b,c in zip(state['bins'],state['counts'])])
        return metric,rows,audit

    def unavoidable_pairs(self,mode):
        domains=[tuple(c for c in d if mode!='ground' or c<5) for d in self.domains]
        return [[self.flights[i]['id'],self.flights[j]['id']]
                for k,(i,j) in enumerate(self.pairs) if self.tables[k][np.ix_(domains[i],domains[j])].all()]

    def export_variant(self,method,run,folder=None):
        folder=Path(folder) if folder is not None else self.folder/'variants'/method.lower()
        folder.mkdir(parents=True,exist_ok=True)
        by_id={r['id']:r for r in run['flights']}
        metadata=deepcopy(self.manifest)
        metadata['optimization_method']=method
        metadata['label'] += {'NO_CONTROL':' · Không điều tiết','GA_GROUND':' · GA Ground Delay',
            'GA_MIXED':' · GA đa biện pháp','TEAM_GROUND':' · GA cộng tác · chỉ GDP',
            'TEAM_MIXED':' · GA cộng tác · GDP + giảm tốc'}.get(method,' · '+method)
        metadata['optimization_metrics']=run['metrics']
        metadata['limitations'].insert(0,'Đề xuất GA còn vi phạm ràng buộc nên chỉ dùng để phân tích mô phỏng.' if not run['metrics']['feasible_sampled'] else 'Phương án vượt kiểm tra lấy mẫu 20 giây, vẫn cần kiểm chứng liên tục và quy trình ATC.')
        shifts={}
        for f in metadata['flights']:
            if f['direction']=='arrival':
                row=by_id[f['callsign']]
                target=epoch(f['planned_event_utc'])+row['total_delay_min']*60
                shifts[f['callsign']]=target-epoch(f['simulated_slot_utc'])
                f.update(simulated_slot_utc=iso(target),simulated_delay_min=row['total_delay_min'],atfm_measure=row['measure'],atfm_level=row['level'])
                f['first_track_utc']=iso(epoch(f['first_track_utc'])+shifts[f['callsign']])
                f['last_track_utc']=iso(epoch(f['last_track_utc'])+shifts[f['callsign']])
        with (folder/'tracks.csv').open('w',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(self.track_rows[0]));writer.writeheader()
            for original in self.track_rows:
                row=dict(original);row['time_utc']=iso(epoch(row['time_utc'])+shifts.get(row['callsign'],0))
                row['source']='GA_synthetic_schedule_'+method
                writer.writerow(row)
        (folder/'manifest.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        return str(folder)


def experiment(case_id,seeds=SEEDS,population=80,generations=160,max_evaluations=6000,root=DEFAULT_ROOT):
    started=time.perf_counter()
    evaluator=VideoCaseEvaluator(case_id,root)
    setup_s=time.perf_counter()-started
    runs={}
    def record(name,plan,history=None,search=None):
        metrics,flights,audit=evaluator.evaluate(plan)
        runs[name]=dict(plan=plan,metrics=metrics,flights=flights,audit=audit,history=history or [],search=search or {})
    record('NO_CONTROL',[[0,0]]*evaluator.n)
    for seed in seeds:
        ground,_,preparation=optimize(evaluator,'ground',seed,population,generations,max_evaluations//2)
        remaining=max_evaluations-preparation['total_evaluations']
        for mode,label in (('ground','GA_GROUND'),('mixed','GA_MIXED')):
            plan,history,search=optimize(evaluator,mode,seed+1000,population,generations,remaining,ground)
            search.update(preparation_evaluations=preparation['total_evaluations'],
                total_evaluations=preparation['total_evaluations']+search['total_evaluations'],
                total_elapsed_s=preparation['total_elapsed_s']+search['total_elapsed_s'])
            record(label+'_'+str(seed),plan,history,search)
        print(case_id,'seed',seed,'ground',round(runs['GA_GROUND_'+str(seed)]['metrics']['objective'],2),
              'mixed',round(runs['GA_MIXED_'+str(seed)]['metrics']['objective'],2),flush=True)
    summary=[]
    for method in ('GA_GROUND','GA_MIXED'):
        selected=[run for name,run in runs.items() if name.startswith(method+'_')]
        row=dict(method=method,seeds=len(selected),feasible_runs=sum(r['metrics']['feasible_sampled'] for r in selected))
        for key in ('objective','converted_cost','penalty','total_delay_min','mean_delay_min','arrival_conflict_pairs',
                    'arrival_departure_conflict_pairs','capacity_excess_flights','new_conflict_pairs','ground_flights','speed_flights'):
            values=[r['metrics'][key] for r in selected]
            row['mean_'+key]=statistics.mean(values);row['std_'+key]=statistics.stdev(values) if len(values)>1 else 0
        row['mean_runtime_s']=statistics.mean(r['search']['total_elapsed_s'] for r in selected)
        summary.append(row)
    best={m:min((name for name in runs if name.startswith(m+'_')),key=lambda n:runs[n]['metrics']['objective'])
          for m in ('GA_GROUND','GA_MIXED')}
    variants={'NO_CONTROL':evaluator.export_variant('NO_CONTROL',runs['NO_CONTROL'])}
    for method,name in best.items(): variants[method]=evaluator.export_variant(method,runs[name])
    return dict(version=VERSION,case_id=case_id,case_counts=evaluator.manifest['counts'],
        settings=dict(population=population,generations=generations,seeds=list(seeds),max_evaluations=max_evaluations,
            planning_min=-60,origin_lead_assumption_min=95,ground_levels_min=[5,10,15,20],speed_levels_pct=[5,10,15],
            upstream_segment_min=20,nominal_upstream_speed_kt=240,capacity_combined_per_hour=42,
            penalty_lambda=1000,ground_cost_per_min=1,speed_cost_per_min=2,sample_s=evaluator.sample_s,
            arrival_spacing_nm=10,arrival_same_heading_spacing_nm=20,arrival_departure_diagnostic_nm=5,
            arrival_departure_diagnostic_vertical_ft=1000,setup_s=setup_s),
        input_sha256=evaluator.input_sha256,baseline=runs['NO_CONTROL']['metrics'],runs=runs,summary=summary,
        best_methods=best,variants=variants,
        domain_diagnostics={mode:dict(unavoidable_arrival_pairs=evaluator.unavoidable_pairs(mode)) for mode in ('ground','mixed')},
        limitations=[
            'Video identities and visibility clocks; all routes, coordinates, runway targets and origin takeoff times are reconstructed.',
            'Only arriving flights receive GA measures. Local departures retain the saved synthetic schedule.',
            '42 combined movements/hour is a common study assumption from the supplied Chapter 3 model, not declared airport capacity.',
            'No queue repairs violations. An infeasible plan remains infeasible even when its objective decreases.',
            'Separation is sampled every 20 seconds inside 40 NM and 3000–16570 ft, not certified continuous separation.',
            'New conflict pairs are a penalty diagnostic, not DBSCAN hotspot counts. No PCA or fuel-saving claim.',
            'Speed control occurs on an assumed 20 minute upstream segment. Replay shifts the terminal route time without drawing that upstream segment.',
            'Ground delay and speed reduction are mutually exclusive for each flight in this categorical model.',
        ],elapsed_s=time.perf_counter()-started)
