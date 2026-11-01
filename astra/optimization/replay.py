"""Replay optimized entry/exit events through MOSAIC's shared MockConnector.
Geometric paths are illustrative. Optimizer KPIs come from flow evaluation;
this adapter does not validate the objective with independent 4D dynamics.
"""
from threading import RLock
from astra.airspace import load_profile
from astra.utils.geodesy import move_position, bearing_deg, haversine_distance_nm


class ATFMReplay:
    def __init__(self,reader,pipeline=None,store=None):
        self.reader=reader;self.pipeline=pipeline;self.store=store;self.lock=RLock()
        self.rows=[];self.method=None;self.active=False;self.entered=set();self.exited=set()
        c=reader._connector;self.previous_tick=c.on_tick;self.previous_reset=c.on_reset
        c.on_tick=self.tick;c.on_reset=self.reset
        p=load_profile('tsn_tma');self.center=(p['center']['lat'],p['center']['lon'])

    def reset(self):
        with self.lock:
            self.active=False;self.rows=[];self.method=None;self.entered.clear();self.exited.clear()
            if self.previous_reset:self.previous_reset()

    def load(self,method,rows):
        with self.lock:
            self.reader.reset_simulation()
            if self.pipeline:self.pipeline.reset()
            if self.store:self.store.clear_trails()
            self.rows=rows;self.method=method;self.active=True
            self.reader.set_speed_multiplier(60)
            self.tick();self.reader.send_command('OP')

    def tick(self):
        with self.lock:
            if not self.active:
                if self.previous_tick:self.previous_tick()
                return
            now=self.reader.simulation_time_s()/60
            states=[]
            if self.rows and 'trajectory_local_nm_ft' in self.rows[0]:
                from .formulation_validation import frame
                states=frame(self.rows,now)
            for r in self.rows:
                if now>=r['entry_min']:self.entered.add(r['id'])
                if now>=r['exit_min']:self.exited.add(r['id'])
                if 'trajectory_local_nm_ft' in r:continue
                if not r['entry_min']<=now<r['exit_min']:continue
                frac=(now-r['entry_min'])/(r['exit_min']-r['entry_min'])
                angle={'G_N':0,'G_E':90,'G_W':270}[r['gate']]
                # A schematic multi-leg path stays inside the 40 NM study circle.
                # Its length supports the assumed dwell without unrealistically
                # slow jets on a straight 35 NM radial. Not a published STAR.
                points=[move_position(*self.center,angle,40),
                        move_position(*self.center,angle+75,25),
                        move_position(*self.center,angle+35,15),
                        move_position(*self.center,angle+50,5)]
                lengths=[haversine_distance_nm(*a,*b) for a,b in zip(points,points[1:])]
                distance=sum(lengths);remaining=distance*frac;leg=0
                while leg<len(lengths)-1 and remaining>lengths[leg]:
                    remaining-=lengths[leg];leg+=1
                heading=bearing_deg(*points[leg],*points[leg+1])
                lat,lon=move_position(*points[leg],heading,remaining)
                states.append(dict(callsign=r['id'],aircraft_type=r['aircraft_type'],lat=lat,lon=lon,
                    heading_deg=heading,altitude_ft=11000-9000*frac,
                    ground_speed_kt=distance/r['dwell_min']*60,vertical_speed_fpm=-9000/r['dwell_min'],
                    route_waypoints=points[leg+1:],
                    replay_profile={'flight_type':'SYNTHETIC_REPLAY','direction':'inbound','synthetic':True}))
            self.reader._connector.replace_replay_frame(states)
            if len(self.exited)==len(self.rows):self.reader.send_command('HOLD')

    def status(self):
        with self.lock:
            now=self.reader.simulation_time_s()/60
            holding=sum(r['request_min']<=now<r['entry_min'] for r in self.rows)
            return dict(active=self.active,method=self.method,time_min=now,entered=len(self.entered),
                completed=len(self.exited),total=len(self.rows),upstream_holding=holding,
                occupancy=sum(r['entry_min']<=now<r['exit_min'] for r in self.rows),
                running=self.reader.is_simulation_running())
