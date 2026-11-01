"""Shared synthetic TMA weather speed model for motion, ETAs and prediction.

Surface METAR wind is a uniform study proxy, not an altitude wind forecast.
Nominal procedure GS is treated as a no-wind speed proxy. Keep filed routes
and altitude targets; upstream weather derating and along-track wind change GS.
"""
import math
from astra.utils.geodesy import bearing_deg, haversine_distance_nm


TMA_SPEED_FACTORS = dict(clear=1.0, rain=.97, strong_wind=.95, heavy_rain=.9,
                         thunderstorm=.85, low_visibility=.95, severe=.8)


def weather_active(weather, timestamp_s):
    return bool(weather and weather.get('preset') != 'clear'
                and (weather.get('until_s') is None or timestamp_s < weather['until_s']))


def procedure_speed(nominal, leg, profile, lat, lon, target_lat, target_lon, timestamp_s,
                    include_atfm=True):
    cap = leg.get('max_ias_kt')
    speed = min(nominal, cap) if cap is not None else nominal
    weather = profile.get('tma_weather')
    if weather_active(weather, timestamp_s):
        center = weather['center']
        # A leg ending in the TMA receives the local weather proxy. This
        # keeps long-horizon prediction and live propagation consistent.
        if haversine_distance_nm(target_lat, target_lon, center['lat'], center['lon']) <= weather['radius_nm'] + .1:
            if leg['target_altitude_ft'] >= 3000 and speed >= 180:
                speed = max(180, speed * weather['speed_factor'])
            direction = weather.get('wind_direction_deg')
            if direction is not None:
                heading = bearing_deg(lat, lon, target_lat, target_lon)
                headwind = weather['wind_speed_kt'] * math.cos(math.radians(heading - direction))
                speed = max(min(nominal, 90), speed - headwind)
            if cap is not None:
                speed = min(speed, cap)
    endpoint = profile.get('weather_endpoint')
    metered = bool(endpoint and include_atfm and profile.get('direction') == 'inbound'
               and profile.get('atfm_until_s', -1) > timestamp_s
               and leg['target_altitude_ft'] >= 3000 and speed > 180
               and haversine_distance_nm(target_lat, target_lon, *endpoint) > 10)
    if metered:
        speed = max(180, speed * profile.get('atfm_speed_factor', 1.0))
    return speed, metered
