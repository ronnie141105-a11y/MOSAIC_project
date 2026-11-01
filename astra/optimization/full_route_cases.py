"""Full-route synthetic studies: physical upstream controls and all movements.

All trajectories, costs, origin schedules and capacity are scenario assumptions.
Search tables cover complete airborne paths; selected plans are checked at 1 s.
"""
from copy import deepcopy
import csv
import gzip
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import time
from uuid import uuid4

import numpy as np

from astra.studies.workbook_cases import ROOT, CASES, csv_bytes, json_bytes, stamp, TRACK_FIELDS
from astra.studies.study_routes import trajectory
from astra.studies.study_sectors import sample_masks
from astra.studies.flow_routes import controlled_spec,spec_trajectory
from astra.optimization.teammate_ga import greedy_plan, optimize
from astra.optimization.fcfs import fcfs_plan
from astra.airport.surface_policy import arrival_blocks_departure
from astra.studies.separation_policy import low_terminal

VERSION = 'fixed-order-regional-gate-ga-10'
RUN_ID = re.compile(r'\d{8}T\d{6}Z-[0-9a-f]{8}')


def epoch(value):
    return datetime.fromisoformat(value).timestamp()


class FullRouteEvaluator:
    def __init__(self, case_id, root=ROOT, sample_s=None, progress=None, expanded=False):
        if case_id not in CASES:
            raise ValueError('Choose a synthetic workbook study')
        self.folder = Path(root)/case_id
        self.manifest = json.loads((self.folder/'manifest.json').read_text(encoding='utf-8'))
        self.s = deepcopy(self.manifest['study_settings'])
        self.expanded=expanded
        self.flow=bool(self.manifest.get('flow_programme'))
        if expanded:
            self.s.update(ground_levels_min=list(range(0,61)),speed_levels_pct=[1,2,3,5,10,15],
                airborne_prediction_step_s=1,arrival_pair_check_s=1,ground_action_step_min=1)
        if self.flow:self.s.update(ground_levels_min=list(range(0,61,5)),speed_levels_pct=[-10,-5,5,10,15],
            rta_levels_min=[-3,-2,-1,1,2,3,5,8,12,20,30],fixed_departure_order=True,ground_action_step_min=5)
        self.start = epoch(self.manifest['local_start'])
        self.metadata = self.manifest['flights']
        if self.s.get('sector_capacity_basis')!='simultaneous_occupancy':
            raise ValueError('Rebuild the native sector-capacity studies first')
        self.flights = [dict(id=f['callsign']) for f in self.metadata]
        self.n = len(self.flights)
        self.sample_s = sample_s or self.s['search_sample_s']
        self.options = ((0, 0), *[(1, d) for d in self.s['ground_levels_min']],
                        *[(2, d) for d in self.s['speed_levels_pct']],
                        *([(4,d) for d in self.s['rta_levels_min']]+[(5,d) for d in (180,220,260)] if self.flow else []))
        self.input_sha256 = {name: hashlib.sha256((self.folder/name).read_bytes()).hexdigest()
                            for name in ('manifest.json', 'tracks.csv', 'ground_tracks.json.gz','planning.csv', 'capacity.csv', 'fpl.csv')}
        from astra.studies.ground_replay import GroundReplay
        self.ground=GroundReplay(self.folder/'ground_tracks.json.gz')
        groups = {f['callsign']: [] for f in self.metadata}
        with (self.folder/'tracks.csv').open(encoding='utf-8', newline='') as stream:
            for r in csv.DictReader(stream):
                groups[r['callsign']].append([epoch(r['time_utc'])-self.start,
                    *[float(r[k]) for k in ('lat','lon','altitude_ft','ground_speed_kt','heading_deg','vertical_speed_fpm')]])
        self.paths, self.domains = [], []
        self.events = np.zeros((self.n, len(self.options)))
        self.runway_starts=np.zeros_like(self.events)
        self.runway_ends=np.zeros_like(self.events)
        self.landing_releases=np.zeros_like(self.events)
        self.arrival_protection_starts=np.zeros_like(self.events)
        self.transfers = np.zeros_like(self.events)
        self.delays, self.costs = np.zeros_like(self.events), np.zeros_like(self.events)
        self.ground_delays,self.air_delays=np.zeros_like(self.events),np.zeros_like(self.events)
        planning = epoch(self.manifest['planning_utc'])
        for i, f in enumerate(self.metadata):
            base = np.asarray(groups[f['callsign']])
            arrival = f['direction'] == 'arrival'
            scheduled = epoch(f['planned_event_utc'])-self.start
            ready=scheduled if arrival else epoch(f['requested_event_utc'])-self.start
            domain, paths = [], []
            ground_ok = f['ground_delay_eligible'] and epoch(f['origin_takeoff_utc']) >= planning
            speed_ok = arrival and f.get('speed_control_eligible',True) and self.start+base[0, 0] >= planning
            for c, (measure, level) in enumerate(self.options):
                legal=True
                if self.flow and measure==5 and f.get('origin_pending') and level<f['requested_fl']:
                    from astra.studies.gate_flow import level_cap_spec
                    relative,transfer=spec_trajectory(level_cap_spec(f['initial_airborne_spec'],level*100),1)
                    p=relative.copy();p[:,0]+=base[0,0];transfer_time=base[0,0]+transfer;event=p[-1,0]
                elif self.flow and arrival and measure in (2,4) and speed_ok:
                    from astra.studies.gate_flow import speed_spec,realize_rta
                    if measure==4 and f.get('origin_pending') and level>=0:
                        p=base.copy();p[:,0]+=level*60;transfer_time=f['transfer_time_s']+level*60;event=scheduled+level*60
                    else:
                        result=realize_rta(f['initial_airborne_spec'],level*60) if measure==4 else None
                        if measure==4 and result is None:
                            legal=False;p=base.copy();transfer_time=f['transfer_time_s'];event=scheduled
                        else:
                            relative,transfer=(result['path'],result['transfer_s']) if result else spec_trajectory(speed_spec(f['initial_airborne_spec'],-level),1)
                            p=relative.copy();p[:,0]+=base[0,0];transfer_time=base[0,0]+transfer;event=p[-1,0]
                elif measure == 2 and speed_ok:
                    if f.get('initial_airborne_spec'):
                        relative,transfer=spec_trajectory(controlled_spec(f['initial_airborne_spec'],level),1 if expanded else 5)
                    else:
                        from astra.studies.full_cycle import _transfer
                        relative, _ = trajectory(f['route_family'],f['requested_fl'],level)
                        transfer = _transfer(relative,'arrival')['time_s']
                    p = relative.copy()
                    p[:, 0] += base[0, 0]
                    transfer_time = base[0, 0]+transfer
                    event = p[-1, 0]
                else:
                    p = base.copy()
                    target=(ready if f.get('origin_status_at_planning','PARKED')=='PARKED' else scheduled)+level*60
                    shift = target-scheduled if measure == 1 and ground_ok else 0
                    p[:, 0] += shift
                    event = scheduled+shift
                    transfer_time = f['transfer_time_s']+shift
                paths.append(p)
                self.events[i, c], self.transfers[i, c] = event, transfer_time
                delay=max(0,(event-ready)/60)
                if f.get('origin_pending'):
                    embedded=max(0,(f['origin_ctot_s']-f['origin_requested_ctot_s'])/60)
                    added=level if measure==1 or measure==4 and level>=0 else 0
                    gd=embedded+added;ad=max(0,(event-scheduled)/60-added)
                else:gd,ad=(0,delay) if arrival else (delay,0)
                self.ground_delays[i,c]=gd;self.air_delays[i,c]=ad;self.delays[i,c]=gd+ad
                self.costs[i,c]=gd*self.s['ground_cost_per_min']+ad*self.s['speed_cost_per_delay_min']
                if legal and (measure == 0 or (measure == 1 and ground_ok) or (measure in (2,4) and speed_ok) or (measure==5 and f.get('origin_pending') and level<f['requested_fl'])):
                    domain.append(c)
            marks=self.ground.milestones[f['callsign']]
            delta=self.events[i]-scheduled
            self.runway_starts[i]=(marks['touchdown'] if arrival else marks.get('takeoff_roll',marks['runway_entry']))+delta
            self.runway_ends[i]=marks['runway_exit' if arrival else 'takeoff']+delta
            self.landing_releases[i]=(marks['runway_exit'] if arrival else marks['takeoff'])+delta
            if arrival:
                from astra.studies.operational_cases import arrival_protection_start
                self.arrival_protection_starts[i]=[arrival_protection_start(p) for p in paths]
            self.paths.append(paths)
            self.domains.append(tuple(domain))
        self.minimum = max(0,math.floor(min(self.paths[i][c][0,0] for i,d in enumerate(self.domains) for c in d)))
        self.maximum = math.ceil(max(self.paths[i][c][-1,0] for i,d in enumerate(self.domains) for c in d))
        self.pairs = [(i,j) for i in range(self.n) for j in range(i+1,self.n)]
        self.pair_i = np.asarray([i for i,j in self.pairs])
        self.pair_j = np.asarray([j for i,j in self.pairs])
        self.indices = np.arange(self.n)
        samples = [self.sample([paths[c] for c in domain], self.sample_s,i,domain) for i,(paths,domain) in enumerate(zip(self.paths,self.domains))]
        masks=[]
        for sample,domain in zip(samples,self.domains):
            full=np.zeros((len(self.s['sectors']),len(self.options),sample['valid'].shape[-1]),dtype=bool)
            full[:,domain,:]=sample['sector_masks'];masks.append(full)
        self.occupancy_masks=np.stack(masks,axis=1)
        self.tables = []
        # Ground delays translate unchanged paths. A departure pair therefore
        # needs only 121 relative-shift checks, not 61 x 61 full comparisons.
        fine_arrivals={i:self.sample([self.paths[i][c] for c in self.domains[i]],1,i,self.domains[i])
            for i,f in enumerate(self.metadata) if expanded and f['direction']=='arrival'}
        for k,(i,j) in enumerate(self.pairs):
            table=np.zeros((len(self.options),len(self.options)),dtype=bool)
            if expanded and self.metadata[i]['direction']==self.metadata[j]['direction']=='departure':
                table[np.ix_(self.domains[i],self.domains[j])]=self.departure_shift_table(i,j)
            else:
                a,b=(fine_arrivals[i],fine_arrivals[j]) if i in fine_arrivals and j in fine_arrivals else (samples[i],samples[j])
                table[np.ix_(self.domains[i],self.domains[j])]=self.conflicts(a,b)[0]
            self.tables.append(table)
            if progress and k % 100 == 0:
                progress(dict(phase='full_route_tables', pair=k+1, pairs=len(self.pairs)))
        self.tables = np.asarray(self.tables)
        self.base_pairs = self.tables[:,0,0]
        self.fine_baseline = {}
        self.arrival_pair = np.asarray([self.metadata[i]['direction']==self.metadata[j]['direction']=='arrival' for i,j in self.pairs])
        self.departure_pair = np.asarray([self.metadata[i]['direction']==self.metadata[j]['direction']=='departure' for i,j in self.pairs])
        self.committed_departures=np.asarray([f['direction']=='departure' and
            f.get('origin_status_at_planning','PARKED')!='PARKED' for f in self.metadata])
        self.queue_ranks=np.asarray([f.get('queue_rank',0) for f in self.metadata])
        self.origin_order_pairs=[(k,i,j) for k,(i,j) in enumerate(self.pairs) if self.metadata[i].get('origin_pending')
            and self.metadata[j].get('origin_pending') and self.metadata[i]['adep']==self.metadata[j]['adep']]
        self.feeder_order_pairs=[(k,i,j) for k,(i,j) in enumerate(self.pairs) if self.metadata[i]['direction']==self.metadata[j]['direction']=='arrival'
            and self.metadata[i]['route_family']==self.metadata[j]['route_family']]
        self.gate_tables=np.zeros_like(self.tables)
        if self.flow:
            from astra.studies.gate_flow import cluster_member
            config=self.manifest['flow_programme']
            for k,(i,j) in enumerate(self.pairs):
                if not(cluster_member(self.metadata[i]) and cluster_member(self.metadata[j])):continue
                for a in self.domains[i]:
                    for b in self.domains[j]:
                        ti,tj=self.transfers[i,a],self.transfers[j,b];t=max(ti,tj)
                        from astra.utils.geodesy import haversine_distance_nm
                        distance=haversine_distance_nm(*[np.interp(t,p[:,0],p[:,col]) for p in (self.paths[i][a],self.paths[j][b]) for col in (1,2)])
                        self.gate_tables[k,a,b]=abs(ti-tj)<config['minit_s']-1 or distance<config['mit_nm']-.1
        self.safety_barrier=self.s['penalty_lambda']*(self.n*len(self.s['sectors'])*
            (self.maximum-self.minimum+self.sample_s)/60+1)+self.n*120

    def departure_shift_table(self,i,j):
        """Translate by whole grid steps, preserving sub-grid CTOT phases."""
        left=np.rint(self.events[i,list(self.domains[i])]-self.events[i,0]).astype(int)
        right=np.rint(self.events[j,list(self.domains[j])]-self.events[j,0]).astype(int)
        result=np.zeros((len(left),len(right)),dtype=bool)
        for phase in np.unique(left%self.sample_s):
            rows=np.flatnonzero(left%self.sample_s==phase)
            delta=right[None,:]-left[rows,None]
            shifts=np.unique(delta)
            p=self.paths[i][0].copy();p[:,0]+=phase
            a=self.sample([p],self.sample_s,i,[0])
            paths=[]
            for shift in shifts:
                p=self.paths[j][0].copy();p[:,0]+=phase+shift;paths.append(p)
            b=self.sample(paths,self.sample_s,j,[0]*len(paths))
            values=self.conflicts(a,b)[0][0]
            result[rows,:]=values[np.searchsorted(shifts,delta)]
        return result

    def encode(self, plan, mode='mixed'):
        if mode not in ('ground','mixed') or not isinstance(plan,(list,tuple)) or len(plan)!=self.n:
            raise ValueError('One [measure, level] gene per movement is required')
        codes=[]
        for i,gene in enumerate(plan):
            if not isinstance(gene,(list,tuple)) or len(gene)!=2 or any(type(x) is not int for x in gene):
                raise ValueError('Genes must be two integers')
            try:
                code=self.options.index(tuple(gene))
            except ValueError as exc:
                raise ValueError('Unknown measure or level') from exc
            if code not in self.domains[i] or (mode=='ground' and gene[0] not in (0,1)):
                raise ValueError('Measure unavailable for this flight')
            codes.append(code)
        return codes

    def decode(self,codes):
        return [list(self.options[c]) for c in codes]

    def sample(self, paths, step,flight_index=None,codes=None):
        times=np.arange(self.minimum, self.maximum+step, step)
        values=np.asarray([[np.interp(times,p[:,0],p[:,k]) for k in (1,2,3)] +
            [np.degrees(np.interp(times,p[:,0],np.unwrap(np.radians(p[:,5])))) % 360] for p in paths])
        lat,lon=np.radians(values[:,0]),np.radians(values[:,1])
        xyz=3440.065*np.asarray([np.cos(lat)*np.cos(lon),np.cos(lat)*np.sin(lon),np.sin(lat)])
        valid=np.asarray([(times>=p[0,0]) & (times<=p[-1,0]) for p in paths])
        centre=np.zeros_like(valid)
        if self.s.get('centre_arrival_horizontal_spacing') and flight_index is not None and self.metadata[flight_index]['direction']=='arrival':
            centre=np.asarray([times<=self.transfers[flight_index,c] for c in codes])&valid
        return dict(values=values,xyz=xyz,valid=valid,centre_arrival=centre,
            direction=self.metadata[flight_index]['direction'] if flight_index is not None else None,
            low_terminal=low_terminal(values[:,0],values[:,1],values[:,2]),
            sector_masks=sample_masks(values,valid,self.s['sectors']))

    def conflicts(self,a,b,areas=False):
        av,bv=a['values'],b['values']
        valid=a['valid'][:,None,:] & b['valid'][None,:,:]
        vertical=np.abs(av[:,None,2]-bv[None,:,2]) < self.s['vertical_ft']
        centre=a['centre_arrival'][:,None,:]&b['centre_arrival'][None,:,:]
        angle=np.abs((av[:,None,3]-bv[None,:,3]+180) % 360-180)
        horizontal2=sum((a['xyz'][k,:,None,:]-b['xyz'][k,None,:,:])**2 for k in range(3))
        threshold=np.where(angle<=self.s['same_heading_tolerance_deg'],
            self.s['same_heading_horizontal_nm'],self.s['horizontal_nm'])
        threshold=np.where(centre&~vertical,self.s['horizontal_nm'],threshold)
        if a.get('direction') and b.get('direction') and a['direction']!=b['direction']:
            threshold=np.where(a['low_terminal'][:,None,:]&b['low_terminal'][None,:,:],
                self.s.get('terminal_mixed_horizontal_nm',self.s['horizontal_nm']),threshold)
        vertical |= centre
        chord2=(6880.13*np.sin(threshold/6880.13))**2
        violation=valid & vertical & (horizontal2<chord2)
        result=np.any(violation,axis=-1)
        if not areas:
            return result,None
        # Great-circle radius, using the same airport centre as the native route.
        from astra.centre import centre_point
        clat,clon=np.radians(centre_point())
        def outside(values):
            lat,lon=np.radians(values[:,0]),np.radians(values[:,1])
            h=np.sin((lat-clat)/2)**2+np.cos(lat)*np.cos(clat)*np.sin((lon-clon)/2)**2
            return 6880.13*np.arcsin(np.sqrt(np.clip(h,0,1))) > 40
        ao,bo=outside(av)[:,None,:],outside(bv)[None,:,:]
        return result,dict(centre=bool(np.any(violation & ao & bo)),
            terminal=bool(np.any(violation & ~ao & ~bo)),
            boundary=bool(np.any(violation & (ao != bo))))

    def state(self,codes,conflicts=None,baseline_pairs=None,sector_counts=None,step_s=None):
        codes=np.asarray(codes,dtype=int)
        events=self.events[self.indices,codes]
        transfers=self.transfers[self.indices,codes]
        conflicts=self.tables[np.arange(len(self.pairs)),codes[self.pair_i],codes[self.pair_j]] if conflicts is None else conflicts
        sector_counts=self.occupancy_masks[:,self.indices,codes,:].sum(axis=1) if sector_counts is None else sector_counts
        capacities=np.asarray([s['capacity'] for s in self.s['sectors']])
        excess=np.maximum(sector_counts-capacities[:,None],0)
        occupancy_penalty=float(excess.sum()*(step_s or self.sample_s)/60)
        peak_excess=int(excess.max())
        rs=self.runway_starts[self.indices,codes]
        re=self.runway_ends[self.indices,codes]
        release=self.landing_releases[self.indices,codes]
        protection=self.arrival_protection_starts[self.indices,codes]
        mixed=~self.arrival_pair & ~self.departure_pair
        left_arr=np.asarray([f['direction']=='arrival' for f in self.metadata])[self.pair_i]
        runway=(~mixed)&(np.maximum(rs[self.pair_i],rs[self.pair_j])<np.minimum(re[self.pair_i],re[self.pair_j])+1e-6)
        ai=np.where(left_arr,self.pair_i,self.pair_j);di=np.where(left_arr,self.pair_j,self.pair_i)
        runway |= mixed&arrival_blocks_departure(rs[di],re[di],protection[ai],rs[ai],release[ai])
        runway |= self.departure_pair & (np.abs(events[self.pair_i]-events[self.pair_j])<self.s.get('minimum_takeoff_gap_s',0)-1e-6)
        transfer=self.arrival_pair & (np.abs(transfers[self.pair_i]-transfers[self.pair_j]) < self.s['arrival_transfer_minimum_gap_s']-1e-6)
        left_committed=self.committed_departures[self.pair_i];right_committed=self.committed_departures[self.pair_j]
        gap=self.s.get('minimum_takeoff_gap_s',120)
        sequence=self.departure_pair&np.where(self.queue_ranks[self.pair_i]<self.queue_ranks[self.pair_j],
            events[self.pair_j]<events[self.pair_i]+gap-1e-6,events[self.pair_i]<events[self.pair_j]+gap-1e-6)
        if self.flow:
            transfer |= self.gate_tables[np.arange(len(self.pairs)),codes[self.pair_i],codes[self.pair_j]]
            for k,i,j in self.feeder_order_pairs:
                sequence[k] |= transfers[j]<=transfers[i] if self.transfers[i,0]<self.transfers[j,0] else transfers[i]<=transfers[j]
            for k,i,j in self.origin_order_pairs:
                a,b=self.metadata[i],self.metadata[j]
                ta=a['origin_ctot_s']+self.paths[i][codes[i]][0,0]-self.paths[i][0][0,0]
                tb=b['origin_ctot_s']+self.paths[j][codes[j]][0,0]-self.paths[j][0][0,0]
                sequence[k] |= tb<ta+240-1 if a['origin_queue_rank']<b['origin_queue_rank'] else ta<tb+240-1
        new=conflicts & ~(self.base_pairs if baseline_pairs is None else baseline_pairs)
        penalty=occupancy_penalty+int(conflicts.sum()+runway.sum()+transfer.sum()+sequence.sum()+new.sum())
        cost=float(self.costs[self.indices,codes].sum())
        safety=int(conflicts.sum()+runway.sum()+transfer.sum()+sequence.sum()+new.sum())
        objective=cost+self.s['penalty_lambda']*occupancy_penalty+safety*(self.safety_barrier if self.expanded else self.s['penalty_lambda'])
        return dict(objective=objective,cost=cost,penalty=penalty,
            conflicts=conflicts,new=new,runway=runway,transfer=transfer,sequence=sequence,events=events,
            capacity_excess=peak_excess,occupancy_penalty=occupancy_penalty,sector_peaks=sector_counts.max(axis=1))

    def objective(self,codes):
        return self.state(codes)['objective']

    def evaluate(self,plan,sample_s=None):
        codes=self.encode(plan)
        sample_s=sample_s or self.sample_s
        area_counts=dict(centre=0,terminal=0,boundary=0)
        if sample_s!=self.sample_s:
            samples=[self.sample([self.paths[i][c]],sample_s,i,[c]) for i,c in enumerate(codes)]
            flags=[]
            for i,j in self.pairs:
                flag,areas=self.conflicts(samples[i],samples[j],True)
                flags.append(bool(flag[0,0]))
                for key,value in areas.items():
                    area_counts[key]+=value
            if sample_s not in self.fine_baseline:
                if not any(codes):
                    self.fine_baseline[sample_s]=np.asarray(flags)
                else:
                    self.evaluate(self.decode([0]*self.n),sample_s=sample_s)
            sector_counts=np.stack([s['sector_masks'][:,0,:] for s in samples],axis=1).sum(axis=1)
            state=self.state(codes,np.asarray(flags),self.fine_baseline[sample_s],sector_counts,sample_s)
        else:
            state=self.state(codes)
        rows=[]
        for i,(f,c) in enumerate(zip(self.metadata,codes)):
            measure,level=self.options[c]
            delay=float(self.delays[i,c])
            ground=float(self.ground_delays[i,c])
            rows.append(dict(id=f['callsign'],direction=f['direction'],measure=measure,level=level,
                ground_delay_min=ground,speed_delay_min=float(self.air_delays[i,c]),
                total_delay_min=delay,converted_cost=float(self.costs[i,c]),
                planned_runway_utc=f['planned_event_utc'],adjusted_runway_utc=stamp(self.start+state['events'][i]),
                adjusted_origin_takeoff_utc=(stamp(epoch(f['origin_takeoff_utc'])+self.paths[i][c][0,0]-self.paths[i][0][0,0]) if f.get('origin_pending') else f['origin_takeoff_utc']) if f['direction']=='arrival' else stamp(self.start+state['events'][i]),
                adjusted_admission_utc=stamp(self.start+self.paths[i][c][0,0]),
                adjusted_transfer_utc=stamp(self.start+self.transfers[i,c]),
                first_track_utc=stamp(self.start+self.paths[i][c][0,0]),
                last_track_utc=stamp(self.start+self.paths[i][c][-1,0]),
                ground_eligible=bool(any(self.options[x][0]==1 for x in self.domains[i])),
                procedure=f['procedure'],speed_scope='Centre legs before 40 NM' if measure==2 else 'none'))
        metrics=dict(objective=state['objective'],converted_cost=state['cost'],penalty=state['penalty'],
            capacity_excess_flights=state['capacity_excess'],sector_peak_excess_aircraft=state['capacity_excess'],
            sector_excess_aircraft_minutes=state['occupancy_penalty'],
            sector_peaks={s['id']:int(p) for s,p in zip(self.s['sectors'],state['sector_peaks'])},
            arrival_conflict_pairs=int((state['conflicts'] & self.arrival_pair).sum()),
            departure_conflict_pairs=int((state['conflicts'] & self.departure_pair).sum()),
            arrival_departure_conflict_pairs=int((state['conflicts'] & ~self.arrival_pair & ~self.departure_pair).sum()),
            separation_conflict_pairs=int(state['conflicts'].sum()),new_conflict_pairs=int(state['new'].sum()),
            departure_sequence_pairs=int(state['sequence'].sum()),
            runway_spacing_pairs=int(state['runway'].sum()),arrival_transfer_spacing_pairs=int(state['transfer'].sum()),
            feasible_sampled=state['penalty']==0,sample_s=sample_s,
            total_delay_min=sum(r['total_delay_min'] for r in rows),
            ground_delay_min=sum(r['ground_delay_min'] for r in rows),speed_delay_min=sum(r['speed_delay_min'] for r in rows),
            mean_delay_min=statistics.mean(r['total_delay_min'] for r in rows),max_delay_min=max(r['total_delay_min'] for r in rows),
            no_action_flights=sum(c==0 for c in codes),ground_flights=sum(self.options[c][0]==1 for c in codes),
            speed_flights=sum(self.options[c][0]==2 for c in codes),optimized_movements=self.n,
            completed_in_original_window=int(sum(0<=t<epoch(self.manifest['local_end'])-self.start for t in state['events'])))
        if sample_s!=self.sample_s:
            metrics.update(centre_conflict_pairs=area_counts['centre'],terminal_conflict_pairs=area_counts['terminal'],
                           across_boundary_conflict_pairs=area_counts['boundary'])
        pairs=lambda flags:[[self.metadata[i]['callsign'],self.metadata[j]['callsign']] for (i,j),v in zip(self.pairs,flags) if v]
        audit=dict(conflict_pairs=pairs(state['conflicts']),runway_spacing_pairs=pairs(state['runway']),
            arrival_transfer_spacing_pairs=pairs(state['transfer']),
            sector_occupancy=[dict(sector_id=s['id'],peak=int(p),capacity=s['capacity']) for s,p in zip(self.s['sectors'],state['sector_peaks'])],
            scope='Complete Centre / TMA / runway paths, all pair types, full lead-in and tail')
        return metrics,rows,audit

    def export_variant(self,method,run,folder,retain_replay=True):
        from astra.studies.operational_cases import build,AirbornePlanConflict
        folder=Path(folder)
        folder.mkdir(parents=True,exist_ok=True)
        cache=getattr(self,'_native_packages',{})
        policy='fcfs' if method.startswith('FCFS') else 'optimized'
        genes=tuple(map(tuple,run['plan']))
        dep=[i for i,f in enumerate(self.metadata) if f['direction']=='departure']
        order=tuple(sorted(dep,key=lambda i:(0 if self.committed_departures[i] else 1,
            epoch(self.metadata[i]['requested_event_utc'])-self.start if policy=='fcfs' else self.events[i,self.options.index(genes[i])],self.metadata[i]['callsign'])))
        key=(policy,order,genes)
        if key not in cache:
            if not any(m for m,l in genes):
                names=('manifest.json','summary.json','tracks.csv','ground_tracks.json.gz',
                       'planning.csv','capacity.csv','fpl.csv','flights.csv','demand.csv','source_rows.json')
                files={name:(self.folder/name).read_bytes() for name in names}
            else:
                records=json.loads((self.folder/'source_rows.json').read_text(encoding='utf-8'))
                executed=deepcopy(run['plan']);adjustments=[]
                for _ in range(self.n+1):
                    if not any(m for m,l in executed):
                        names=('manifest.json','summary.json','tracks.csv','ground_tracks.json.gz','planning.csv','capacity.csv','fpl.csv','flights.csv','demand.csv','source_rows.json')
                        files={name:(self.folder/name).read_bytes() for name in names}
                        break
                    try:
                        files=build(self.manifest['case_id'],records,self.manifest['source']['sha256'],
                            controls=executed,baseline_manifest=self.manifest,departure_order=policy,control_basis='requested_ready_time')
                        break
                    except AirbornePlanConflict as exc:
                        changed=False
                        for i,f in enumerate(self.metadata):
                            if executed[i]!=[0,0] and f['callsign'] in exc.callsigns and (executed[i][0] in (2,4,5) or executed[i][0]==1 and f.get('origin_pending')):
                                adjustments.append(dict(callsign=f['callsign'],proposed=executed[i],executed=[0,0],
                                    reason='Native spacing check; retain baseline forward stream'))
                                executed[i]=[0,0];changed=True
                        if not changed:
                            # A held origin leader can delay an unchanged
                            # follower. Withdraw the coupled proposal rather
                            # than treating the follower as an isolated cause.
                            for i,control in enumerate(executed):
                                if control!=[0,0]:
                                    adjustments.append(dict(callsign=self.metadata[i]['callsign'],proposed=control,executed=[0,0],reason='Coupled origin/gate conflict: retain validated reference'))
                                    executed[i]=[0,0];changed=True
                            if not changed:raise
                else:raise ValueError('Native control repair did not converge')
                m=json.loads(files['manifest.json']);m['native_control_adjustments']=adjustments
                files['manifest.json']=json_bytes(m)
            cache[key]=files
            self._native_packages=cache
        files=cache[key]
        manifest=json.loads(files['manifest.json'])
        summary=json.loads(files['summary.json'])
        occupancy=summary['sector_occupancy']
        peak=max(max(0,s['peak']-s['capacity']) for s in occupancy['sectors'])
        capacity_minutes=occupancy['total_excess_aircraft_seconds']/60
        total=ground=speed=airborne_hold=0.0
        actual_delays=[];origin_ground=local_ground=0.0
        requested_delays=[];embedded_delays=[];additional_delays=[];net_changes=[]
        for i,f in enumerate(manifest['flights']):
            old=self.metadata[i]
            requested=epoch(old['simulated_slot_utc'] if f['direction']=='arrival' else old['requested_event_utc'])
            change=(epoch(f['simulated_slot_utc'])-epoch(old['simulated_slot_utc']))/60
            additional_delays.append(max(0,change));net_changes.append(change)
            delay=max(0,(epoch(f['simulated_slot_utc'])-requested)/60)
            actual_measure=f.get('atfm_measure',0)
            if f.get('origin_pending'):
                gd=max(0,(f['origin_ctot_s']-old['origin_requested_ctot_s'])/60)
                added=(f['origin_ctot_s']-old['origin_ctot_s'])/60
                airborne=max(0,change-added)
                delay=gd+airborne;origin_ground+=gd;ground+=gd
            else:airborne=delay if f['direction']=='arrival' and actual_measure in (2,4,5) else 0
            total+=delay;speed+=airborne
            if f['direction']=='arrival' and not f.get('origin_pending'):airborne_hold+=delay-airborne
            elif f['direction']=='departure':ground+=delay;local_ground+=delay
            actual_delays.append(delay)
            requested_delays.append(max(0,(epoch(f['simulated_slot_utc'])-requested)/60))
            embedded_delays.append(max(0,(epoch(self.metadata[i]['simulated_slot_utc'])-requested)/60))
        metrics=deepcopy(run['metrics'])
        actual_measures=[f.get('atfm_measure',0) for f in manifest['flights']]
        ground_data=json.loads(gzip.decompress(files['ground_tracks.json.gz']))
        departures=[f for f in manifest['flights'] if f['direction']=='departure']
        arrivals=[f for f in manifest['flights'] if f['direction']=='arrival']
        marks=ground_data['milestones']
        hold_seconds=0
        for f in departures:
            rows=ground_data['flights'][f['callsign']]['samples']
            hold_seconds+=sum(max(0,b[0]-max(0,a[0])) for a,b in zip(rows,rows[1:]) if a[6] in ('HOLDING','LINING_UP'))
        metrics.update(total_delay_min=total,ground_delay_min=ground,speed_delay_min=speed,
            origin_ground_delay_min=origin_ground,local_departure_delay_min=local_ground,
            no_action_flights=actual_measures.count(0),ground_flights=actual_measures.count(1),speed_flights=actual_measures.count(2),
            native_withdrawn_control_proposals=len(manifest.get('native_control_adjustments',[])),
            native_withdrawn_speed_proposals=sum(a.get('proposed',[0])[0]==2 for a in manifest.get('native_control_adjustments',[])),
            departure_sequence_pairs=0,completion_time_s=max(f['completed_s'] for f in manifest['flights']),
            departure_stand_wait_min=sum(max(0,marks[f['callsign']]['off_block']) for f in departures)/60,
            departure_taxi_out_min=sum(marks[f['callsign']]['takeoff']-max(0,marks[f['callsign']]['off_block']) for f in departures)/60,
            departure_hold_min=hold_seconds/60,
            arrival_taxi_in_min=sum(marks[f['callsign']]['stand_arrival']-marks[f['callsign']]['touchdown'] for f in arrivals)/60,
            maximum_committed_surface_departures=summary['stream_audit']['maximum_committed_surface_departures'],
            maximum_airborne_holding_aircraft=summary['stream_audit']['maximum_airborne_holding_aircraft'],
            airborne_holding_delay_min=airborne_hold,converted_cost=ground+2*speed+2*airborne_hold,capacity_excess_flights=peak,
            sector_peak_excess_aircraft=peak,sector_excess_aircraft_minutes=capacity_minutes,
            sector_peaks={s['id']:s['peak'] for s in occupancy['sectors']},
            separation_conflict_pairs=0,arrival_conflict_pairs=0,departure_conflict_pairs=0,
            arrival_departure_conflict_pairs=0,new_conflict_pairs=0,runway_spacing_pairs=0,
            arrival_transfer_spacing_pairs=0,penalty=capacity_minutes,
            feasible_sampled=peak==0,mean_delay_min=total/self.n,sample_s=1,
            max_delay_min=max(actual_delays),
            requested_schedule_delay_min=sum(requested_delays),max_requested_schedule_delay_min=max(requested_delays),
            reference_embedded_delay_min=sum(embedded_delays),
            additional_delay_min=sum(additional_delays),net_delay_change_min=sum(net_changes),
            delay_basis='Fixed departure requested ready-event; arrival uncontrolled touchdown from identical initial state',
            native_prediction_error_min=abs(total-run['metrics']['total_delay_min']),
            completed_in_original_window=sum(self.start<=epoch(f['simulated_slot_utc'])<epoch(self.manifest['local_end']) for f in manifest['flights']),
            objective=ground+2*speed+2*airborne_hold+self.s['penalty_lambda']*capacity_minutes,
            centre_conflict_pairs=0,terminal_conflict_pairs=0,across_boundary_conflict_pairs=0,
            measurement_basis='native_airport_and_airborne_execution',
            safety_metering_delay_min=airborne_hold+sum(max(0,actual_delays[i]-self.delays[i,self.options.index(genes[i])])
                for i,f in enumerate(self.metadata) if f['direction']=='departure'))
        if self.flow:
            gate=manifest['flow_audit'];violations=gate['violating_pairs']
            metrics.update(gate_flow_violations=violations,gate_flow_compliant=violations==0,
                rta_flights=actual_measures.count(4),level_cap_flights=actual_measures.count(5),
                vector_flights=sum(f.get('flow_actions',{}).get('path_extension_nm',0)>.01 for f in manifest['flights']),
                gdp_origin_flights=sum(bool(f.get('origin_pending')) and f.get('atfm_measure',0) in (1,4) for f in manifest['flights']),
                fixed_order=True)
            if violations:raise ValueError('Shared AC–BAOMY MIT/MINIT programme failed native validation')
        manifest.update(optimization_method=method,optimization_metrics=metrics,study_settings=deepcopy(self.s),
            search_projection_metrics=run['metrics'],label=manifest['label']+' · '+method,
            native_execution_validation=dict(safe_for_replay=True,sample_s=1,
                gate_flow_audit=manifest.get('flow_audit'),fixed_order=True,
                surface_audit=summary['surface_audit'],sector_occupancy=occupancy,
                separation_audit=summary['separation_audit']))
        manifest['replay_retained']=retain_replay
        for name,data in files.items():
            if retain_replay or name=='manifest.json':
                (folder/name).write_bytes(json_bytes(manifest) if name=='manifest.json' else data)
        flight_rows=[]
        for i,f in enumerate(manifest['flights']):
            old=self.metadata[i]
            flight_rows.append(dict(callsign=f['callsign'],direction=f['direction'],
                proposed_measure=run['plan'][i][0],proposed_level=run['plan'][i][1],
                executed_measure=f.get('atfm_measure',0),executed_level=f.get('atfm_level',0),
                reference_runway_utc=old['simulated_slot_utc'],executed_runway_utc=f['simulated_slot_utc'],
                delay_clock_utc=old['simulated_slot_utc'] if f['direction']=='arrival' else old['requested_event_utc'],
                event_delay_min=actual_delays[i],
                net_runway_change_min=(epoch(f['simulated_slot_utc'])-epoch(old['simulated_slot_utc']))/60,
                runway_delay_min=max(0,(epoch(f['simulated_slot_utc'])-epoch(old['simulated_slot_utc']))/60),
                completion_delay_min=max(0,(f['completed_s']-old['completed_s'])/60),
                tobt_s=f.get('tobt_s'),off_block_s=f.get('off_block_time_s'),ctot_s=f.get('ctot_s')))
        (folder/'execution_flights.csv').write_bytes(csv_bytes(list(flight_rows[0]),flight_rows))
        return metrics

def saved_folder(case_id,root=ROOT,run_id=None):
    if case_id not in CASES:
        raise ValueError('Unknown synthetic study')
    base=Path(root)/case_id/'variants/full_route_ga'
    if run_id is None:
        run_id=json.loads((base/'latest.json').read_text())['run_id']
    if not isinstance(run_id,str) or not RUN_ID.fullmatch(run_id):
        raise ValueError('Invalid saved full-route run identifier')
    return base/run_id


def saved_result(case_id,root=ROOT,run_id=None):
    result=json.loads((saved_folder(case_id,root,run_id)/'results.json').read_text(encoding='utf-8'))
    if result['version'] not in (VERSION,'full-route-hybrid-ga-7','full-route-hybrid-ga-6','full-route-fcfs-ga-5') or result['case_id']!=case_id:
        raise ValueError('Saved result uses another evaluator version')
    for name,digest in result['input_sha256'].items():
        if hashlib.sha256((Path(root)/case_id/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('Scenario changed; rerun the full-route study')
    return result


def export_comparison(root=ROOT):
    """Compare executed means, never a single best GA against an FCFS mean."""
    rows=[]
    for case_id in CASES:
        result=saved_result(case_id,root)
        for method in ('TEAM_MIXED','FCFS','NO_CONTROL'):
            row=next(r for r in result['native_summary'] if r['method']==method)
            rows.append(dict(case_id=case_id,role=result['study_role'],run_id=result['run_id'],
                demand=result['case_counts']['total'],measurement_basis='native_execution_1s',**row))
    path=Path(root)/'study_comparison.csv'
    path.write_bytes(csv_bytes(list(rows[0]),rows))
    return path


def summarize_native(trials):
    rows=[]
    for method in ('NO_CONTROL','FCFS','TEAM_GROUND','TEAM_MIXED'):
        selected=[r['metrics'] for r in trials if r['method']==method]
        if not selected:continue
        row=dict(method=method,runs=len(selected),safe_runs=sum(m['separation_conflict_pairs']==0 and
            m['runway_spacing_pairs']==0 and m['arrival_transfer_spacing_pairs']==0 for m in selected),
            capacity_feasible_runs=sum(m['feasible_sampled'] for m in selected))
        for key,value in selected[0].items():
            if type(value) not in (int,float):continue
            values=[m[key] for m in selected]
            row['mean_'+key]=statistics.mean(values)
            row['std_'+key]=statistics.stdev(values) if len(values)>1 else 0.0
        rows.append(row)
    return rows


def experiment(case_id,seeds=tuple(range(11,111,11)),population=60,generations=120,max_evaluations=6000,
               root=ROOT,publish=True,progress=None,evaluator=None):
    from .teammate_cases import validate_settings
    validate_settings('nominal',seeds,population,generations,max_evaluations)
    started=time.perf_counter()
    from .hybrid_ga import optimize as hybrid_optimize
    from tempfile import TemporaryDirectory
    e=evaluator if evaluator is not None else FullRouteEvaluator(case_id,root,progress=progress,expanded=True)
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]
    temporary=TemporaryDirectory() if not publish else None
    folder=saved_folder(case_id,root,run_id) if publish else Path(temporary.name)
    folder.mkdir(parents=True,exist_ok=True)
    runs={}
    def record(name,plan,history=None,search=None):
        metrics,flights,audit=e.evaluate(plan)
        runs[name]=dict(plan=plan,metrics=metrics,flights=flights,audit=audit,history=history or [],search=search or {})
    record('NO_CONTROL',[[0,0]]*e.n)
    fcfs,fcfs_search=fcfs_plan(e)
    record('FCFS_FINE',fcfs,search=fcfs_search)
    fine_domains=e.domains
    try:
        e.domains=[tuple(c for c in d if e.options[c][0]!=1 or e.options[c][1]%(10 if e.flow else 5)==0) for d in fine_domains]
        coarse,coarse_search=fcfs_plan(e)
    finally:e.domains=fine_domains
    record('FCFS_COARSE',coarse,search=coarse_search)
    fcfs_variants=[]
    for name in ('FCFS_FINE','FCFS_COARSE'):
        actual=e.export_variant(name,runs[name],folder/'fcfs_benchmarks'/name.lower(),retain_replay=False)
        fcfs_variants.append(dict(method=name,run=name,seed=None,metrics=actual))
    fcfs_selected=min(fcfs_variants,key=lambda r:r['metrics']['objective'])['run']
    # The primary FCFS is the stronger measured baseline; both resolutions
    # remain visible and both are offered to every GA as warm starts.
    runs['FCFS']=deepcopy(runs[fcfs_selected])
    runs['FCFS']['search']['selected_resolution']=fcfs_selected
    preparation=fcfs_search['candidate_checks']+coarse_search['candidate_checks']
    remaining=max_evaluations-preparation
    if remaining<1:raise ValueError('Search budget must exceed FCFS warm-start checks')
    native_candidates={}
    def native_callback(name):
        def execute(plan,generation):
            key=tuple(map(tuple,plan))
            if key not in native_candidates:
                metrics,_,_=e.evaluate(plan)
                target=folder/'native_candidates'/f'candidate_{len(native_candidates):03d}'
                if progress:progress(dict(phase='native_search_feedback',method=name,generation=generation,
                    native_candidates=len(native_candidates)+1,completed_seeds=len([n for n in runs if n.startswith('TEAM_MIXED_')]),total_seeds=len(seeds)))
                actual=e.export_variant('TEAM_MIXED' if 'MIXED' in name else 'TEAM_GROUND',dict(plan=plan,metrics=metrics),target,retain_replay=False)
                manifest=json.loads((target/'manifest.json').read_text(encoding='utf-8'))
                repaired=[[f.get('atfm_measure',0),f.get('atfm_level',0)] for f in manifest['flights']]
                native_candidates[key]=dict(metrics=actual,executed_plan=repaired,path=str(target.relative_to(folder)))
            return native_candidates[key]
        return execute
    for k,seed in enumerate(seeds):
        for mode in ('mixed',):
            name='TEAM_'+mode.upper()+'_'+str(seed)
            plan,history,search=hybrid_optimize(e,mode,seed,population,generations,remaining,fcfs,
                native=native_callback(name),native_budget=4,coarse_incumbent=coarse)
            search.update(preparation_evaluations=preparation,total_budget=max_evaluations,
                total_evaluations=preparation+search['search_evaluations'])
            record('TEAM_'+mode.upper()+'_'+str(seed),plan,history,search)
            (folder/'search_progress.json').write_bytes(json_bytes(runs))
        if progress:
            progress(dict(phase='search',completed_seeds=k+1,total_seeds=len(seeds)))
    best={m:min((n for n in runs if n.startswith(m+'_')),key=lambda n:runs[n]['metrics']['objective'])
          for m in ('TEAM_MIXED',)}
    summary=[]
    for method in best:
        selected=[r for n,r in runs.items() if n.startswith(method+'_')]
        row=dict(method=method,seeds=len(selected),feasible_runs=sum(r['metrics']['feasible_sampled'] for r in selected))
        for key in ('objective','converted_cost','penalty','total_delay_min','arrival_conflict_pairs',
                    'arrival_departure_conflict_pairs','departure_conflict_pairs','separation_conflict_pairs',
                    'runway_spacing_pairs','arrival_transfer_spacing_pairs','capacity_excess_flights','new_conflict_pairs'):
            values=[r['metrics'][key] for r in selected]
            row['mean_'+key]=statistics.mean(values)
            row['std_'+key]=statistics.stdev(values) if len(values)>1 else 0
        summary.append(row)
    checks={}
    if progress:
        progress(dict(phase='validation_1s',completed_seeds=len(seeds),total_seeds=len(seeds)))
    for method,name in [('NO_CONTROL','NO_CONTROL'),('FCFS','FCFS'),*best.items()]:
        metrics,_,audit=e.evaluate(runs[name]['plan'],sample_s=e.s['validation_sample_s'])
        checks[method]=dict(selected_run=name,metrics=metrics,audit=audit)
    result=dict(version=VERSION,run_id=run_id,
        case_id=case_id,case_counts=e.manifest['counts'],study_role=e.manifest['study_role'],
        input_sha256=e.input_sha256,settings=dict(**e.s,seeds=list(seeds),population=population,
            generations=generations,max_evaluations=max_evaluations,sample_s=e.sample_s,
            trajectory_tables_cache_reused=getattr(e,'trajectory_tables_cache_reused',False),
            budget_basis='Fast objective calls include fine and coarse FCFS warm-start checks; up to 4 separately counted native checkpoints per method/seed',
            native_check_budget_per_seed=4,search_operators=['fixed_origin_fifo','route_cohort_crossover','coordinated_arrival_speed','rta_speed_vector_realization','regional_gdp','local_refinement','diversity_restarts','native_error_calibration','multi_resolution_warm_start'],
            objective='Safety barrier first; then delay cost + lambda * sector excess aircraft-minutes. Final selection uses native execution.',
            fcfs_policy=fcfs_search['policy'],fcfs_selected_resolution=fcfs_selected,
            delay_basis='Fixed departure requested ready-event; arrival uncontrolled touchdown from identical initial state',
            primary_comparison='GA coordinated ATFM vs fixed FIFO FCFS vs the shared-gate reference'),
        baseline=runs['NO_CONTROL']['metrics'],runs=runs,summary=summary,best_methods=best,
        post_validation=dict(sample_s=e.s['validation_sample_s'],checks=checks),
        limitations=e.manifest['limitations']+[
            'All study inputs are synthetic. Feasible_sampled is a model diagnostic, not operational validation.',
            'Search uses native 1 s arrival trajectories and 1 s arrival-pair checks; occupancy and mixed/departure screening use 20 s. Up to four native execution checkpoints per method/seed guide selection.',
            'Regional origins use approximate dispatch positions, virtual stand/taxi timelines and explicit airborne paths; they are not detailed airport surface models.',
            'Delay uses fixed departure requested ready-events and the uncontrolled arrival touchdown from identical initial airborne states. Additional and signed changes from the reference are reported separately.',
            f'FCFS and GA preserve frozen origin departure queues. Both {e.s["ground_action_step_min"]}-minute and {10 if e.flow else 5}-minute grids are executed; the better native FCFS is the comparator.',
            f'GA coordinates GDP/CTOT with physically feasible RTA, speed, short rejoining vectors and regional level caps. This run has {len(seeds)} fixed seed(s); it is not evidence of operational statistical significance.',
            'Native safety metering may extend CTOT/RTA proposals; withdrawn proposals and executed controls are recorded per flight.'
        ],elapsed_s=time.perf_counter()-started)
    from .teammate_cases import export_tables
    # Save search evidence before the expensive native replay pass. A failed
    # pass never updates latest.json or publishes an unvalidated plan.
    (folder/'search_results.json').write_bytes(json_bytes(result))
    trials=[]
    native_names=['NO_CONTROL','FCFS']+[n for n in runs if n.startswith('TEAM_')]
    for index,name in enumerate(native_names):
        method=next((m for m in ('TEAM_GROUND','TEAM_MIXED') if name.startswith(m+'_')),name)
        if progress:progress(dict(phase='native_airport_validation',method=name,completed_trials=index,total_trials=len(native_names)))
        actual=e.export_variant(method,runs[name],folder/'native_trials'/name.lower(),retain_replay=False)
        trials.append(dict(method=method,run=name,seed=int(name.rsplit('_',1)[1]) if name.startswith('TEAM_') else None,metrics=actual))
        (folder/'native_trials.json').write_bytes(json_bytes(trials))
    # Choose a replay using measured execution, while comparison means include
    # every seed, including proposals repaired by the native safety controller.
    best={method:min((r for r in trials if r['method']==method),key=lambda r:r['metrics']['objective'])['run']
          for method in ('TEAM_MIXED',)}
    for name,r in runs.items():
        if not name.startswith('TEAM_'):continue
        history=r['search'].get('native_history',[])
        warm=[h for h in history if h.get('generation',0)<0]
        # Keep the raw checkpoint history. Derive the attribution from it in
        # the reporting layer so improvements are never assumed to be genetic.
        r['search']['initialization_checkpoints']=warm
    result.update(best_methods=best,native_trials=trials,native_summary=summarize_native(trials),
        fcfs_benchmarks=fcfs_variants,fcfs_selected_resolution=fcfs_selected)
    for method,name in [('NO_CONTROL','NO_CONTROL'),('FCFS','FCFS'),*best.items()]:
        metrics,_,audit=e.evaluate(runs[name]['plan'],sample_s=e.s['validation_sample_s'])
        actual=next(r['metrics'] for r in trials if r['run']==name)
        checks[method]=dict(selected_run=name,metrics=metrics,audit=audit,native_execution_metrics=actual)
        if method=='NO_CONTROL':continue
        target=folder/method.lower()
        e.export_variant(method,runs[name],target)
        manifest=json.loads((target/'manifest.json').read_text(encoding='utf-8'))
        manifest.update(optimizer_run_id=result['run_id'],optimizer_version=VERSION)
        (target/'manifest.json').write_bytes(json_bytes(manifest))
    result['elapsed_s']=time.perf_counter()-started
    export_tables(folder,result)
    (folder/'native_summary.csv').write_bytes(csv_bytes(list(result['native_summary'][0]),result['native_summary']))
    flat_trials=[dict(method=r['method'],run=r['run'],seed=r['seed'],**{k:v for k,v in r['metrics'].items() if not isinstance(v,dict)}) for r in trials]
    (folder/'native_trials.csv').write_bytes(csv_bytes(list(flat_trials[0]),flat_trials))
    if publish:
        pointer=folder.parent/(result['run_id']+'.tmp')
        pointer.write_bytes(json_bytes(dict(run_id=result['run_id'])))
        pointer.replace(folder.parent/'latest.json')
    if temporary:temporary.cleanup()
    return result
