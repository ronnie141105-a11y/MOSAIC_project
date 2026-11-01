"""Run reconstructed study tracks on the existing standalone radar clock."""
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
import json

from astra.interface.airnav_replay import AirNavReplayConnector
from astra.studies.vvts_cases import dataset_for_case, utc
from astra.studies.system_tests import CASES as SYSTEM_TESTS, ROOT as SYSTEM_TEST_ROOT
from astra.studies.workbook_cases import CASES as WORKBOOK_CASES, ROOT as WORKBOOK_ROOT

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / 'scenarios/reconstructed/vvts_video_cases'
CASE_IDS = ('nominal', 'holiday_peak')


class CaseStudyReplay:
    def __init__(self, reader, pipeline=None, store=None, root=DEFAULT_ROOT):
        self.reader, self.pipeline, self.store = reader, pipeline, store
        self.root = Path(root)
        self.lock = RLock()
        self.active = False
        self.case_id = None
        self.manifest = None
        self.replay = None
        self.ground_replay = None
        connector = reader._connector
        self.previous_tick, self.previous_reset = connector.on_tick, connector.on_reset
        connector.on_tick, connector.on_reset = self.tick, self.reset
        connector.case_replay = self

    def catalog(self):
        cases = []
        folders = [(case_id, self.root/case_id) for case_id in CASE_IDS]
        folders += [(case_id, WORKBOOK_ROOT/case_id) for case_id in WORKBOOK_CASES]
        for case_id, folder in folders:
            path = folder / 'manifest.json'
            if not path.exists():
                continue
            manifest = json.loads(path.read_text(encoding='utf-8'))
            if case_id in WORKBOOK_CASES:
                manifest['supported_methods']=['TEAM_MIXED','FCFS','RECONSTRUCTED']
            cases.append({key: manifest.get(key) for key in
                          ('case_id', 'label', 'local_start', 'local_end', 'basis',
                           'coverage', 'limitations', 'counts', 'supported_methods',
                           'native_connected_tracks', 'baseline_sequencing', 'study_role',
                           'capacity_combined_per_hour', 'demand_capacity_ratio','sector_occupancy')})
        return cases

    def reset(self):
        with self.lock:
            self.active = False
            self.case_id = self.manifest = self.replay = None
            self.ground_replay = None
            if self.previous_reset:
                self.previous_reset()

    def load(self, case_id, method='RECONSTRUCTED', enroute=False, run_id=None):
        is_test=case_id in SYSTEM_TESTS if isinstance(case_id,str) else False
        is_workbook=case_id in WORKBOOK_CASES if isinstance(case_id,str) else False
        if case_id not in CASE_IDS and not is_test and not is_workbook:
            raise ValueError('Unknown case scenario')
        folder = (SYSTEM_TEST_ROOT if is_test else WORKBOOK_ROOT if is_workbook else self.root) / case_id
        if is_test and method!='RECONSTRUCTED':raise ValueError('System tests use their validated synthetic schedule')
        if is_workbook and method not in ('RECONSTRUCTED','NO_CONTROL','FCFS','TEAM_GROUND','TEAM_MIXED'):
            raise ValueError('Choose the full-route reference, FCFS, or a saved GA plan')
        if method not in ('RECONSTRUCTED','NO_CONTROL','FCFS','GA_GROUND','GA_MIXED','TEAM_GROUND','TEAM_MIXED') or (method=='FCFS' and not is_workbook):
            raise ValueError('Unknown case optimization method')
        if method in ('FCFS','TEAM_GROUND','TEAM_MIXED'):
            if is_workbook:
                from astra.optimization.full_route_cases import saved_folder,saved_result
                saved_result(case_id,WORKBOOK_ROOT,run_id)
                folder = saved_folder(case_id,WORKBOOK_ROOT,run_id)/method.lower()
            else:
                from astra.optimization.teammate_cases import saved_folder
                folder = saved_folder(case_id,self.root,run_id)/method.lower()
        elif method != 'RECONSTRUCTED' and not is_workbook:
            folder = folder / 'variants' / method.lower()
        manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        if is_workbook:
            manifest['label']=manifest['label'].replace('TEAM_MIXED','GA')
        if is_workbook and method in ('FCFS','TEAM_GROUND','TEAM_MIXED') and not manifest.get('native_execution_validation',{}).get('safe_for_replay'):
            raise ValueError('This GA plan has no validated stand-to-stand execution; rebuild its study run')
        if not isinstance(enroute,bool):raise ValueError('enroute must be true or false')
        metadata = {flight['callsign']:flight for flight in manifest['flights']}
        dataset = dataset_for_case(folder)
        if dataset is None:
            raise ValueError('The case has no runnable tracks')
        start = utc(manifest['local_start']).timestamp()
        study_start = start
        native_connected = manifest.get('native_connected_tracks', False)
        if native_connected and not manifest.get('flow_programme'):
            start = min(start, dataset.start_epoch_s)
        elif enroute and not is_test:
            from astra.studies.centre_replay import extend_dataset
            dataset = extend_dataset(dataset,metadata)
            start = max(start-3600,dataset.start_epoch_s)
            manifest['label'] += ' · FIR context (synthetic)'
        end = max(utc(manifest['local_end']).timestamp(), dataset.end_epoch_s)
        if manifest.get('flow_programme'):
            end=start+max(f['completed_s'] for f in manifest['flights'])+30
        if manifest.get('ground_replay_file') and not manifest.get('flow_programme'):
            end=max(end,study_start+manifest.get('duration_s',0))
        if native_connected and not manifest.get('ground_replay_file'):
            # Let the last endpoint expire before stopping the replay clock.
            end += 1
        replay = AirNavReplayConnector(dataset, start_epoch_s=start, end_epoch_s=end)
        ground_replay = None
        if manifest.get('ground_replay_file'):
            from astra.studies.ground_replay import GroundReplay
            ground_replay = GroundReplay(folder/manifest['ground_replay_file'])
        with self.lock:
            self.reader.reset_simulation()
            if self.pipeline:
                self.pipeline.reset()
            if self.store:
                self.store.clear_trails()
            self.manifest, self.replay, self.case_id = manifest, replay, case_id
            self.ground_replay = ground_replay
            self.method = method
            self.enroute = enroute or is_test or native_connected
            self.system_test=is_test
            self.study_window_s=manifest.get('duration_s',7200) if is_test else utc(manifest['local_end']).timestamp()-study_start
            self.study_offset_s = study_start-start
            self.metadata = metadata
            self.duration_s = end - start
            self.atfm_complete=False
            self.atfm_completed_at_s=None
            departures=[f['completed_s'] for f in metadata.values() if f['direction']=='departure'] if manifest.get('flow_programme') else []
            self.departure_phase_end_s=max(departures) if departures else None
            self.active = True
            airport = getattr(self.reader._connector, 'airport_integration', None)
            if airport:
                with airport._lock:
                    airport.study_key = 'recording_' + case_id
                    for cs, flight in self.metadata.items():
                        airport.fpl[cs] = dict(callsign=cs, aircraft_type=flight['aircraft_type'],
                            origin=flight['adep'], destination=flight['ades'],
                            arrival_route=flight.get('procedure') if flight['direction']=='arrival' else '',
                            departure_route=flight.get('procedure') if flight['direction']=='departure' else '',
                            star=flight.get('procedure') if flight['direction']=='arrival' else '',
                            sid=flight.get('procedure') if flight['direction']=='departure' else '',
                            runway=flight.get('runway'),
                            requested_fl=flight.get('requested_fl'), stand=flight.get('stand'),
                            off_block_time_s=flight.get('origin_tobt_s',flight.get('off_block_time_s')),
                            tobt_s=flight.get('origin_tobt_s',flight.get('tobt_s')),estimated_taxi_out_s=flight.get('origin_taxi_s',flight.get('estimated_taxi_out_s')),
                            ctot_s=flight.get('origin_ctot_s',flight.get('ctot_s')),route_family=flight.get('route_family'),
                            origin_name=flight.get('origin_name'),origin_pending=flight.get('origin_pending',False),
                            flow_actions=flight.get('flow_actions',{}),cto_s=flight.get('cto_s'),flow_gate=flight.get('flow_gate'),
                            centre_route=flight.get('centre_route'),
                            approach_transfer_fix=flight.get('approach_transfer_fix'),
                            transfer_time_s=flight.get('transfer_time_s'),
                            transfer_level_ft=flight.get('transfer_level_ft'),
                            waypoint_times_s=flight.get('waypoint_times_s'),
                            source=flight.get('evidence'))
            self.reader.set_speed_multiplier(30)
            self.tick()
            self.seed_trails()
            self.reader.send_command('HOLD')
        return self.status()

    def tick(self):
        with self.lock:
            if not self.active:
                if self.previous_tick:
                    self.previous_tick()
                return
            now = self.reader.simulation_time_s()
            if now > self.duration_s:
                self.reader.send_command('HOLD')
                self.reader._connector.restore_clock(self.duration_s)
                now = self.duration_s
            frame, _ = self.replay.frame_at(now)
            states = []
            for ac in frame:
                flight = self.metadata[ac.callsign]
                states.append(dict(callsign=ac.callsign, aircraft_type=ac.aircraft_type,
                    lat=ac.lat, lon=ac.lon, altitude_ft=ac.altitude_ft,
                    heading_deg=ac.heading_deg, ground_speed_kt=ac.ground_speed_kt,
                    vertical_speed_fpm=ac.vertical_speed_fpm,
                    replay_profile=dict(flight_type='CASE_STUDY_REPLAY',
                        direction='inbound' if flight['direction']=='arrival' else 'outbound',
                        procedure_id=flight.get('procedure'), runway=flight.get('runway'),
                        atfm_measure=flight.get('atfm_measure'),atfm_level=flight.get('atfm_level'),
                        origin=flight.get('adep'),origin_name=flight.get('origin_name'),flow_actions=flight.get('flow_actions',{}),
                        cto_s=flight.get('cto_s'),
                        connected_fir=self.enroute,centre_route=flight.get('centre_route'),
                        airborne_sequencing_kind=flight.get('initial_airborne_spec',{}).get('procedure_profile',{}).get('airborne_sequencing_kind'),
                        approach_transfer_fix=flight.get('approach_transfer_fix'),
                        approach_transfer_position=flight.get('approach_transfer_position'),
                        approach_transfer_complete=(now>=flight['transfer_time_s']) if flight['direction']=='arrival' and flight.get('initial_airborne_spec') else None,
                        synthetic=True, evidence=flight.get('evidence'))))
            self.reader._connector.replace_replay_frame(states)
            if (self.manifest.get('flow_programme') and not self.atfm_complete
                    and self.departure_phase_end_s is not None and now>=self.departure_phase_end_s):
                from astra.studies.study_sectors import current_counts
                if all(s['excess']==0 for s in current_counts(self.reader.list_aircraft())):
                    self.atfm_complete=True
                    self.atfm_completed_at_s=now
                    self.reader.send_command('HOLD')
            if now >= self.duration_s:
                self.reader.send_command('HOLD')

    def seed_trails(self):
        if not self.store:
            return
        now = self.reader.simulation_time_s()
        paths = {}
        for cs in self.reader._connector.latest_snapshot().aircraft:
            paths[cs] = [dict(lat=p.lat, lon=p.lon, time_s=p.epoch_s-self.replay.start_epoch_s)
                         for p in self.replay.dataset.points[cs]
                         if p.epoch_s-self.replay.start_epoch_s <= now and p.state is not None]
        self.store.seed_replay_trails(paths, now)

    def tower_view(self, payload):
        """Read-only final-area / initial climb context on the existing Tower.

        Workbook studies and full-cycle tests include saved native ground
        movements on the same replay clock. Legacy recordings may omit taxi.
        The radar display receives geographic arrival positions out to 20 NM.
        """
        with self.lock:
            if not self.active:return payload
            from astra.airspace import load_profile
            from astra.utils.geodesy import haversine_distance_nm
            threshold=load_profile('tsn_tma')['waypoint_data']['RW25R']
            approaches={};tower_arrivals={};departures=[]
            ground = self.ground_replay.frame_at(self.reader.simulation_time_s(),payload['fpl']) if self.ground_replay else None
            ground_callsigns = {a['callsign'] for a in ground['aircraft']} if ground else set()
            for ac in self.reader.list_aircraft():
                flight=self.metadata[ac['callsign']]
                d=haversine_distance_nm(ac['lat'],ac['lon'],threshold['lat'],threshold['lon'])
                if flight['direction']=='arrival' and d<=20 and ac['callsign'] not in ground_callsigns:
                    tower_arrivals[ac['callsign']]=dict(lat=ac['lat'],lon=ac['lon'],distance_nm=d,
                        altitude_ft=ac['altitude_ft'],speed_kt=ac['ground_speed_kt'],
                        heading_deg=ac['heading_deg'],vertical_speed_fpm=ac['vertical_speed_fpm'])
                if flight['direction']=='arrival' and d<=8 and ac['callsign'] not in ground_callsigns:
                    approaches[ac['callsign']]=dict(distance_nm=d,altitude_ft=ac['altitude_ft'],
                        speed_kt=ac['ground_speed_kt'],vertical_speed_fpm=ac['vertical_speed_fpm'])
                elif not ground and flight['direction']=='departure' and d<=4 and ac['altitude_ft']<=1500:
                    departures.append(dict(callsign=ac['callsign'],x=300-min(275,d/4*275),y=333-min(36,d/4*36),
                        state='CLIMBING',operation='dep',route=[],seg_idx=0,manual_route=False,stand=None,
                        altitude_ft=ac['altitude_ft'],speed_kt=ac['ground_speed_kt'],
                        vertical_speed_fpm=ac['vertical_speed_fpm'],fpl=payload['fpl'].get(ac['callsign']),metrics={}))
            payload.update(approaches=approaches,tower_arrivals=tower_arrivals,aircraft=departures,
                sim_time_s=self.reader.simulation_time_s(),running=self.reader.is_simulation_running(),
                replay_read_only=True)
            if ground:
                payload.update(ground)
            return payload

    def seek(self, seconds):
        with self.lock:
            if not self.active:
                raise ValueError('Load a case first')
            seconds = float(seconds)
            if not 0 <= seconds <= self.duration_s:
                raise ValueError('Time is outside this case replay')
            self.reader.send_command('HOLD')
            self.reader._connector.restore_clock(seconds)
            self.atfm_complete=False
            self.atfm_completed_at_s=None
            if self.pipeline:
                self.pipeline.reset()
            if self.store:
                self.store.clear_trails()
            self.tick()
            self.reader.clear_history()
            self.seed_trails()
        return self.status()

    def status(self):
        with self.lock:
            now = self.reader.simulation_time_s()
            result = dict(active=self.active, case_id=self.case_id,
                          time_s=now, running=self.reader.is_simulation_running(),
                          multiplier=self.reader._connector.get_speed_multiplier())
            if self.store:
                result['trail_generation'] = self.store.trail_generation
            if self.active:
                result.update(duration_s=self.duration_s, study_window_s=self.study_window_s, study_offset_s=self.study_offset_s,
                    atfm_complete=self.atfm_complete,atfm_completed_at_s=self.atfm_completed_at_s,
                    completion_basis='All TSN departures have left the modeled sector and no sector is over capacity',
                    remaining_arrivals=sum(f['direction']=='arrival' and now<f['completed_s'] for f in self.metadata.values()),
                    enroute=self.enroute, label=self.manifest['label'],method=self.method,
                    system_test=self.system_test,
                    ground_tracks=bool(self.ground_replay),
                    optimization_metrics=self.manifest.get('optimization_metrics'),
                    optimizer_run_id=self.manifest.get('optimizer_run_id'),
                    optimization_validation_5s=self.manifest.get('optimization_validation_5s'),
                    playback_utc=datetime.fromtimestamp(self.replay.start_epoch_s+now, timezone.utc).isoformat(),
                    total=len(self.metadata), visible=len(self.reader.list_aircraft()),
                    completed=sum(now >= flight['completed_s'] for flight in self.metadata.values())
                        if self.ground_replay else sum(now >= points[-1].epoch_s-self.replay.start_epoch_s
                                  for points in self.replay.dataset.points.values()))
                if self.manifest.get('study_settings',{}).get('sector_capacity_basis')=='simultaneous_occupancy':
                    from astra.studies.study_sectors import current_counts
                    result['sector_occupancy']=current_counts(self.reader.list_aircraft())
                    result['capacity_basis']='simultaneous_airborne_per_sector'
            return result
