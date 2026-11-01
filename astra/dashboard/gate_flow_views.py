"""Centre read models for shared gates and origin GDP/TOBT/CTOT boards."""
from datetime import datetime
from astra.studies.gate_flow import AIRPORTS
from astra.centre import airway_network

def flow_board(reader,integration):
    replay=getattr(reader._connector,'case_replay',None)
    active=bool(replay and replay.active)
    now=reader.simulation_time_s()
    manifest=replay.manifest if active else {}
    flights=manifest.get('flights',[])
    if not active:
        flights=[dict(callsign=cs,adep=f.get('origin','VVTS'),ades=f.get('destination','VVTS'),
            direction='departure' if f.get('origin')=='VVTS' else 'arrival',aircraft_type=f.get('aircraft_type'),
            tobt_s=f.get('tobt_s',f.get('off_block_time_s')),ctot_s=f.get('ctot_s'),
            procedure=f.get('sid') or f.get('star'),transfer_time_s=f.get('transfer_time_s')) for cs,f in integration.fpl.items()]
    airports=[]
    for icao,airport in AIRPORTS.items():
        rows=[];arrivals=[]
        for f in flights:
            if f.get('adep')==icao and (icao=='VVTS' or f.get('origin_pending') or not active):
                pending=f.get('origin_pending',False)
                tobt=f.get('origin_tobt_s') if pending else f.get('tobt_s') if icao=='VVTS' else None
                ctot=f.get('origin_ctot_s') if pending else f.get('ctot_s') if icao=='VVTS' else None
                state='AIRBORNE' if ctot is None or now>=ctot else 'TAXI' if tobt is not None and now>=tobt else 'STAND'
                if not active:
                    ac=getattr(integration.sim,'aircraft',{}).get(f['callsign'])
                    actual=getattr(getattr(ac,'state',None),'value',getattr(ac,'state',None))
                    if actual in ('PARKED','ARRIVED'):state='STAND' if actual=='PARKED' else 'COMPLETE'
                    elif actual in ('TAXIING','HOLDING','LINING_UP','TAKING_OFF'):state='TAXI'
                if f.get('completed_s') is not None and now>=f['completed_s']:state='COMPLETE'
                rows.append(dict(callsign=f['callsign'],aircraft_type=f.get('aircraft_type'),origin=icao,
                    origin_name=airport['name'],destination=f.get('ades'),tobt_s=tobt,ctot_s=ctot,
                    requested_ctot_s=f.get('origin_requested_ctot_s') if pending else f.get('initial_requested_ctot_s',f.get('ctot_s')),gate=f.get('flow_gate') or f.get('approach_transfer_fix'),
                    requested_tobt_s=f.get('origin_requested_tobt_s',max(0,f.get('origin_requested_ctot_s',0)-f.get('origin_taxi_s',0))) if pending else f.get('ready_offblock_time_s'),
                    cto_s=f.get('cto_s',f.get('transfer_time_s')),rta_s=f.get('flow_actions',{}).get('rta_target_s'),
                    procedure=f.get('procedure'),route=f.get('centre_route'),state=state,
                    actions=f.get('flow_actions') or (dict(gdp_delay_s=f.get('atfm_level',0)*60) if f.get('atfm_measure')==1 else {}),regional_surface_model=pending))
            if icao=='VVTS' and f.get('direction')=='arrival':
                td=None
                if f.get('simulated_slot_utc') and manifest:
                    td=datetime.fromisoformat(f['simulated_slot_utc']).timestamp()-datetime.fromisoformat(manifest['local_start']).timestamp()
                arrivals.append(dict(callsign=f['callsign'],origin=f.get('adep'),touchdown_s=td,
                    state='ARRIVED' if now>=f.get('completed_s',float('inf')) else 'TAXI_IN' if td is not None and now>=td else 'INBOUND'))
        rows.sort(key=lambda r:(r['ctot_s'] if r['ctot_s'] is not None else -1,r['callsign']))
        counts={s:sum(r['state']==s for r in rows) for s in ('STAND','TAXI','AIRBORNE','COMPLETE')}
        airports.append(dict(icao=icao,**airport,departures=rows,arrivals=arrivals,counts=counts,
            waiting=counts['STAND']+counts['TAXI'],total=len(rows)))
    nodes,_=airway_network()
    by_callsign={f['callsign']:f for f in flights}
    events=[]
    for event in (manifest.get('flow_audit') or {}).get('events',[]):
        f=by_callsign[event['callsign']]
        events.append(dict(event,tobt_s=f.get('origin_tobt_s'),ctot_s=f.get('origin_ctot_s'),
            rta_s=f.get('flow_actions',{}).get('rta_target_s'),actions=f.get('flow_actions',{})))
    arrival_events=events[:]
    for f in flights:
        t=f.get('waypoint_times_s',{}).get('PTH')
        if t is not None:events=events+[dict(callsign=f['callsign'],gate='PTH',time_s=t,origin=f.get('adep'))]
    gates=[]
    for n in ('AC','BAOMY','PTH'):
        selected=[r for r in events if r['gate']==n]
        gates.append(dict(id=n,lat=nodes[n][0],lon=nodes[n][1],cluster='AC_BAOMY' if n!='PTH' else 'PTH_BAOMY',
            events=selected,next_15_min=sum(now<=r['time_s']<now+900 for r in selected)))
    return dict(active=active,case_id=manifest.get('case_id'),time_s=now,local_start=manifest.get('local_start'),
        programme=manifest.get('flow_programme'),airports=airports,gates=gates,arrival_events=arrival_events,
        audit=manifest.get('flow_audit'),fixed_order=True,
        note='Regional stands/taxi are timeline models. The VVTS apron uses the native surface simulation.')
