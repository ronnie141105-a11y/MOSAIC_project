"""User-specified nominal ground-speed bands for the synthetic flow studies.

These are simulation targets, not certified aircraft performance or IAS/TAS
conversion. Native terminal speed restrictions continue to apply separately.
"""
from bisect import bisect_right

SPEED_CURVE=((0,140),(5000,210),(10000,250),(14000,270),(16000,280),
             (20000,295),(25000,325),(28000,350),(30000,450),(41000,490))


def altitude_speed(altitude_ft):
    index=bisect_right([p[0] for p in SPEED_CURVE],altitude_ft)
    if index==0:return SPEED_CURVE[0][1]
    if index==len(SPEED_CURVE):return SPEED_CURVE[-1][1]
    (a,x),(b,y)=SPEED_CURVE[index-1:index+1]
    return x+(y-x)*(altitude_ft-a)/(b-a)
