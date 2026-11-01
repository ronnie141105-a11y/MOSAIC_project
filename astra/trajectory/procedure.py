"""Generic fixed-route, piecewise-linear vertical profile for terminal studies.

The same event-based propagator drives the mock and the predictor. It consumes
remaining legs and stops at the explicitly modelled handoff or touchdown point.
Targets describe a nominal simulation path, not a certified performance model.
"""
from copy import deepcopy
from dataclasses import dataclass, replace
import math

from astra.interface.traffic_state import AircraftState
from astra.utils.geodesy import bearing_deg, haversine_distance_nm, move_position
from astra.trajectory.weather import procedure_speed, weather_active


@dataclass
class ProcedureStep:
    aircraft: AircraftState
    remaining_route: list
    profile: dict
    completed: bool
    elapsed_s: float


def validate_procedure_profile(route, profile):
    if not route or profile.get('flight_type') != 'PROCEDURE':
        raise ValueError('A procedure profile requires a nonempty route and flight_type=PROCEDURE')
    legs=profile.get('legs', [])
    if len(legs)!=len(route):
        raise ValueError('Procedure legs must align one-to-one with remaining route coordinates')
    if profile.get('direction') not in ('inbound','outbound'):
        raise ValueError('Procedure direction must be inbound or outbound')
    for lat,lon in route:
        if not (math.isfinite(lat) and math.isfinite(lon) and -90<=lat<=90 and -180<=lon<=180):
            raise ValueError('Invalid procedure coordinates')
    for leg in legs:
        a=leg.get('target_altitude_ft')
        if a is None or not math.isfinite(a) or a<0:
            raise ValueError('Invalid procedure target altitude')


def advance_procedure(ac, route, profile, dt_s):
    """Advance through as many legs as dt permits; return fresh objects.

    Nominal ground speed is the scenario input. Shared TMA weather adjusts
    that no-wind speed proxy. Numeric IAS caps remain conservative GS caps,
    not an IAS/TAS conversion. Altitude varies continuously toward its target.
    """
    if not math.isfinite(dt_s) or dt_s<0:
        raise ValueError('dt_s must be finite and nonnegative')
    route=list(route or [])
    if profile.get('study_altitude_speed'):
        # Generated study legs are immutable. Copy the evolving containers,
        # not every route/leg dictionary on every one-second replay tick.
        p=dict(profile);p['legs']=list(profile['legs'])
        if profile.get('sequencing_pattern'):p['sequencing_pattern']=dict(profile['sequencing_pattern'])
        if 'study_waypoint_times' in profile:p['study_waypoint_times']=dict(profile['study_waypoint_times'])
    else:p=deepcopy(profile)
    legs=p['legs']
    if route:
        p['weather_endpoint'] = list(route[-1])
    if len(route)!=len(legs):raise ValueError('Procedure route/profile mismatch')
    state=ac;remaining=dt_s;elapsed=0.0
    while route:
        lat,lon=route[0];leg=legs[0]
        distance=haversine_distance_nm(state.lat,state.lon,lat,lon)
        target=leg['target_altitude_ft']
        if distance<1e-8:
            # A zero-distance leg cannot justify teleporting altitude.
            if abs(state.altitude_ft-target)>1.0:
                raise ValueError('Zero-length procedure leg has a different altitude target')
            if leg.get('record_event'):
                p.setdefault('study_waypoint_times',{})[leg['fix']]=ac.timestamp_s+elapsed
            if leg.get('fix')==p.get('approach_transfer_fix'):
                p['approach_transfer_complete']=True
                p['approach_transfer_time_s']=ac.timestamp_s+elapsed
            route.pop(0);legs.pop(0)
            pattern=p.get('sequencing_pattern')
            if leg.get('sequence_end') and pattern and pattern['remaining_laps']>0:
                route[:0]=list(map(tuple,pattern['route']))
                legs[:0]=deepcopy(pattern['legs'])
                pattern['remaining_laps']-=1
            continue
        if remaining<=0:break
        nominal=leg.get('nominal_speed_kt') or state.ground_speed_kt
        if p.get('study_altitude_speed') and leg.get('phase') in ('centre','cruise','centre_hold'):
            from astra.trajectory.study_performance import altitude_speed
            nominal=altitude_speed(state.altitude_ft)*leg.get('study_speed_factor',1.0)
            if p.get('flow_acceleration_kt_s'):
                ceiling=280 if state.altitude_ft<=10000 else 320 if state.altitude_ft<=20000 else 350 if state.altitude_ft<=25000 else 500
                nominal=min(ceiling,nominal)
        speed,metered = procedure_speed(nominal,leg,p,state.lat,state.lon,lat,lon,ac.timestamp_s+elapsed)
        if p.get('flow_acceleration_kt_s') and leg.get('phase') in ('centre','cruise'):
            change=p['flow_acceleration_kt_s']*min(remaining,5)
            speed=max(state.ground_speed_kt-change,min(state.ground_speed_kt+change,speed))
        if speed<=0:break
        seconds=distance/speed*3600
        used=min(remaining,seconds)
        until_expiry = p['atfm_until_s'] - ac.timestamp_s - elapsed if metered else math.inf
        weather = p.get('tma_weather')
        if weather_active(weather, ac.timestamp_s + elapsed) and weather.get('until_s') is not None:
            until_expiry = min(until_expiry, weather['until_s'] - ac.timestamp_s - elapsed)
        used=min(used,until_expiry);fraction=used/seconds
        heading=bearing_deg(state.lat,state.lon,lat,lon)
        newlat,newlon=(lat,lon) if used>=seconds else move_position(state.lat,state.lon,heading,speed*used/3600)
        required_rate=(target-state.altitude_ft)/seconds*60
        descent_limit=min(3500.0,max(500.0,p.get('study_max_descent_fpm',2000.0)))
        vertical_rate=max(-descent_limit,min(2000.0,required_rate))
        altitude=state.altitude_ft+vertical_rate*used/60
        if vertical_rate >= 0:
            altitude=min(altitude,target)
        else:
            altitude=max(altitude,target)
        state=replace(state,lat=newlat,lon=newlon,heading_deg=heading,
                      altitude_ft=altitude,
                      vertical_speed_fpm=vertical_rate,ground_speed_kt=speed)
        remaining-=used;elapsed+=used
        if used>=seconds:
            route.pop(0);legs.pop(0)
            if leg.get('fix')==p.get('approach_transfer_fix'):
                p['approach_transfer_complete']=True
                p['approach_transfer_time_s']=ac.timestamp_s+elapsed
            if leg.get('record_event'):
                p.setdefault('study_waypoint_times',{})[leg['fix']]=ac.timestamp_s+elapsed
            pattern=p.get('sequencing_pattern')
            if leg.get('sequence_end') and pattern and pattern['remaining_laps']>0:
                route[:0]=list(map(tuple,pattern['route']))
                legs[:0]=deepcopy(pattern['legs'])
                pattern['remaining_laps']-=1
        elif used >= until_expiry:
            continue
        else:break
    completed=not route
    if completed:state=replace(state,ground_speed_kt=0,vertical_speed_fpm=0)
    state=replace(state,timestamp_s=ac.timestamp_s+dt_s)
    return ProcedureStep(state,route,p,completed,elapsed)
