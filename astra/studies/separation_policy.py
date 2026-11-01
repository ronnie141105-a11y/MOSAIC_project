"""Declared synthetic terminal exception for arrival/departure pairs only."""
import numpy as np
from astra.centre import centre_point

TERMINAL_MIXED_HORIZONTAL_NM=5
TERMINAL_RADIUS_NM=40
TERMINAL_ALTITUDE_FT=10000


def low_terminal(lat,lon,altitude):
    lat,lon=np.radians(lat),np.radians(lon)
    a,b=np.radians(centre_point())
    h=np.sin((lat-a)/2)**2+np.cos(lat)*np.cos(a)*np.sin((lon-b)/2)**2
    return (6880.13*np.arcsin(np.sqrt(np.clip(h,0,1)))<=TERMINAL_RADIUS_NM)&(np.asarray(altitude)<=TERMINAL_ALTITUDE_FT)
