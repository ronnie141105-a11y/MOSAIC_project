"""Optional synthetic FIR context around immutable terminal case tracks."""
from dataclasses import replace
from datetime import datetime, timezone
from astra.centre import outward_route, with_boundary, distance_nm
from astra.interface.airnav_replay import RecordedPoint
from astra.utils.geodesy import bearing_deg, haversine_distance_nm, move_position


def _context(anchor, flight, inbound):
    from astra.airspace import load_profile
    profile=load_profile('tsn_tma')
    procedure=profile['procedure_data'][flight['procedure']]
    fix=procedure['legs'][0 if inbound else -1]['fix']
    route,labels,connector=outward_route((anchor.lat,anchor.lon),fix,220,'inbound' if inbound else 'outbound')
    route=with_boundary(route)
    if inbound:route.reverse()
    coords=[p[1:] for p in route]
    base=distance_nm(anchor.lat,anchor.lon)
    level=max(30000,anchor.state.altitude_ft)
    factor=1-flight.get('atfm_level',0)/100 if flight.get('atfm_measure')==2 and inbound else 1.0
    def altitude(lat,lon):return min(level,anchor.state.altitude_ft+max(0,distance_nm(lat,lon)-base)*220)
    def speed(lat,lon):return (250+min(180,max(0,distance_nm(lat,lon)-40)*3))*factor
    samples=[];elapsed=0.0
    lat,lon=coords[0]
    samples.append((elapsed,lat,lon,altitude(lat,lon),speed(lat,lon),anchor.state.heading_deg,0.0))
    for end in coords[1:]:
        remaining=haversine_distance_nm(lat,lon,*end)
        while remaining>1e-7:
            heading=bearing_deg(lat,lon,*end)
            gs=speed(lat,lon)
            dt=min(20,remaining/gs*3600)
            newlat,newlon=end if dt*gs/3600 >= remaining-1e-7 else move_position(lat,lon,heading,gs*dt/3600)
            alt=altitude(newlat,newlon)
            vs=(alt-samples[-1][3])*60/dt
            elapsed+=dt
            samples.append((elapsed,newlat,newlon,alt,gs,heading,vs))
            lat,lon=newlat,newlon
            remaining=haversine_distance_nm(lat,lon,*end)
    start=anchor.epoch_s-elapsed if inbound else anchor.epoch_s
    points=[]
    for t,lat,lon,alt,gs,heading,vs in samples:
        epoch=start+t
        state=replace(anchor.state,lat=lat,lon=lon,altitude_ft=alt,ground_speed_kt=gs,
            heading_deg=heading,vertical_speed_fpm=vs,timestamp_s=epoch)
        points.append(RecordedPoint(epoch,datetime.fromtimestamp(epoch,timezone.utc).isoformat(),lat,lon,state,
            {k:'synthetic_fir_extension' for k in anchor.field_sources},False))
    flight.update(centre_route=' / '.join(labels),centre_join_connector_assumed=connector,
        fir_context_basis='Synthetic saved-airway extension. Existing terminal tracks and GA scores are unchanged.')
    return points[:-1] if inbound else points[1:]


def extend_dataset(dataset, metadata):
    added=0
    for flight in metadata.values():
        callsign=flight['callsign'];points=dataset.points[callsign]
        usable=[p for p in points if p.state is not None]
        if not usable:continue
        inbound=flight['direction']=='arrival'
        anchor=usable[0 if inbound else -1]
        extension=_context(anchor,flight,inbound)
        dataset.points[callsign]=extension+points if inbound else points+extension
        added+=len(extension)
    dataset._times={cs:[p.epoch_s for p in points] for cs,points in dataset.points.items()}
    dataset.start_epoch_s=min(p[0].epoch_s for p in dataset.points.values())
    dataset.end_epoch_s=max(p[-1].epoch_s for p in dataset.points.values())
    dataset.quality['synthetic_fir_positions']=added
    return dataset
