"""Concurrent airborne occupancy in the ACC polygons displayed by MOSAIC.

The saved map's lateral and vertical slabs are used, grouped by sector number.
The 40 NM Approach handoff cylinder takes precedence. Capacity values are
synthetic study assumptions, not declared operational ACC capacities.
"""
from functools import lru_cache
import json
import math
from pathlib import Path
import re
import numpy as np
from astra.centre import centre_point

SECTORS = (
    dict(id='APPROACH',label='VVTS Approach',capacity=6),
    dict(id='HCM-S1',label='HCM Sector 1',capacity=4),
    dict(id='HCM-S2',label='HCM Sector 2',capacity=3),
    dict(id='HCM-S5',label='HCM Sector 5',capacity=3),
    dict(id='HCM-S6',label='HCM Sector 6',capacity=3),
    dict(id='HCM-S7',label='HCM Sector 7',capacity=3),
)


@lru_cache(maxsize=1)
def slabs():
    path=Path(__file__).resolve().parents[1]/'dashboard/geo/sectors.json'
    features=json.loads(path.read_text(encoding='utf-8'))['features']
    result=[]
    for feature in features:
        props=feature['properties']
        number=re.search(r'\d+',props['id']).group()
        levels=re.findall(r'FL(\d+)',props['vertical_layer'])
        lower=0 if props['vertical_layer'].startswith('GND') else int(levels[0])*100
        upper=int(levels[-1])*100
        result.append(('HCM-S'+number,lower,upper,feature['geometry']['coordinates'][0]))
    return tuple(result)


def polygon_mask(lat,lon,ring):
    """Vectorized ray casting, using the map's lon/lat coordinate order."""
    inside=np.zeros(np.shape(lat),dtype=bool)
    x1,y1=ring[-1]
    for x2,y2 in ring:
        if y1!=y2:
            inside ^= ((y1>lat)!=(y2>lat)) & (lon<(x2-x1)*(lat-y1)/(y2-y1)+x1)
        x1,y1=x2,y2
    return inside


def sample_masks(values,valid,sectors=SECTORS):
    """Disjoint ownership masks for (options, lat/lon/alt/heading, time)."""
    clat,clon=np.radians(centre_point())
    lat,lon,alt=values[:,0],values[:,1],values[:,2]
    la,lo=np.radians(lat),np.radians(lon)
    h=np.sin((la-clat)/2)**2+np.cos(la)*np.cos(clat)*np.sin((lo-clon)/2)**2
    distance=6880.13*np.arcsin(np.sqrt(np.clip(h,0,1)))
    airborne=valid & (alt>0)
    approach=airborne & (distance<=40)
    memberships={'APPROACH':approach}
    assigned=approach.copy()
    for sector in SECTORS[1:]:
        mask=np.zeros_like(valid)
        for key,lower,upper,ring in slabs():
            if key==sector['id']:
                mask |= (alt>lower) & (alt<=upper) & polygon_mask(lat,lon,ring)
        # At shared boundaries the first numbered sector owns the sample;
        # a single aircraft can never be charged to two sectors.
        mask &= airborne & ~assigned
        memberships[sector['id']]=mask
        assigned |= mask
    return np.asarray([memberships[s['id']] for s in sectors])


def sector_id(lat,lon,altitude_ft=10000):
    values=np.asarray([[[lat],[lon],[altitude_ft],[0.]]])
    masks=sample_masks(values,np.ones((1,1),dtype=bool))
    return next((s['id'] for s,mask in zip(SECTORS,masks) if mask[0,0]),None)


def current_counts(aircraft):
    counts=np.zeros(len(SECTORS),dtype=int)
    if aircraft:
        values=np.asarray([[[ac[key] for ac in aircraft] for key in ('lat','lon','altitude_ft')]+[np.zeros(len(aircraft))]])
        counts=sample_masks(values,np.ones((1,len(aircraft)),dtype=bool))[:,0].sum(axis=1)
    return [dict(**s,count=int(count),excess=max(0,int(count)-s['capacity'])) for s,count in zip(SECTORS,counts)]


def occupancy_audit(paths,step_s=1):
    end=math.ceil(max(p[-1,0] for p in paths.values()))
    times=np.arange(0,end+step_s,step_s,dtype=float)
    counts=np.zeros((len(SECTORS),len(times)),dtype=np.int16)
    for path in paths.values():
        valid=(times>=path[0,0]) & (times<=path[-1,0])
        values=np.asarray([[np.interp(times,path[:,0],path[:,k]) for k in (1,2,3)] + [np.zeros(len(times))]])
        counts += sample_masks(values,valid[None,:])[:,0,:]
    result=[]
    for sector,count in zip(SECTORS,counts):
        excess=np.maximum(count-sector['capacity'],0)
        result.append(dict(**sector,peak=int(count.max()),excess_aircraft_seconds=int(excess.sum()*step_s),
            seconds_over_capacity=int((excess>0).sum()*step_s),
            first_exceedance_s=float(times[np.where(excess>0)[0][0]]) if (excess>0).any() else None))
    return dict(basis='Concurrent airborne aircraft in displayed ACC lateral/vertical slabs; 40 NM Approach takes precedence; excludes ground and other sectors',
        sample_s=step_s,sectors=result,total_excess_aircraft_seconds=sum(s['excess_aircraft_seconds'] for s in result))
