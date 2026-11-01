"""Study map overlays from the team's notes; not trajectory constraints."""
from astra.utils.geodesy import move_position
import math


def provisional_vvr19():
    """Clip the 75 km arc with the three offset lines in a local km plane.

    The area-chart TSH and Bien Hoa symbols are proxies for unavailable ARPs /
    runway reference coordinates. Do not export as surveyed zone geometry.
    """
    from astra.airspace import load_profile
    data=load_profile('tsn_tma');pts=data['waypoint_data'];c=data['center']
    def xy(lat,lon):
        return ((lon-c['lon'])*111.195*math.cos(math.radians(c['lat'])),(lat-c['lat'])*111.195)
    def point(n):return xy(pts[n]['lat'],pts[n]['lon'])
    def clip(ring,a,b,offset,side):
        dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
        def distance(p):return side*(dx*(p[1]-a[1])-dy*(p[0]-a[0]))/length-offset
        result=[]
        for p,q in zip(ring,ring[1:]+ring[:1]):
            dp,dq=distance(p),distance(q)
            if dp>=0:result.append(p)
            if (dp>=0)!=(dq>=0):
                t=dp/(dp-dq);result.append((p[0]+t*(q[0]-p[0]),p[1]+t*(q[1]-p[1])))
        return result
    ring=[xy(*move_position(c['lat'],c['lon'],bearing,75/1.852)) for bearing in range(360)]
    # AC–ENRIN is the supplied local W1 alignment, used as the AC–BU proxy.
    ring=clip(ring,point('AC'),point('ENRIN'),15,1)
    # Local R468 segment toward SAPEN gives the TSH–PNH alignment.
    ring=clip(ring,point('TSH'),point('SAPEN'),15,-1)
    # East/west runway assumption supplied by user; approximate chart-symbol latitude.
    south_y=xy(10.976,106.818)[1]-5
    ring=clip(ring,(0,south_y),(1,south_y),0,1)
    coords=[[c['lon']+x/(111.195*math.cos(math.radians(c['lat']))),c['lat']+y/111.195] for x,y in ring]
    if len(coords)<3:raise ValueError('VVR19 reference half-planes do not intersect')
    coords.append(coords[0])
    return coords


def zone_asset(ident):
    properties = dict(name=ident, source='Team revision notes', use='display_only')
    if ident == 'VVP4':
        ring = [[106+38/60+20/3600,10+47/60+50/3600],
                [106+44/60+40/3600,10+49/60+20/3600],
                [106+42/60+22/3600,10+45/60+12/3600],
                [106+38/60+35/3600,10+43/60+45/3600]]
        ring.append(ring[0])
        properties.update(kind='prohibited',geometry_status='coordinates supplied by team')
    elif ident == 'VVR19':
        ring=provisional_vvr19()
        properties.update(name='VVR19',kind='restricted',geometry_status='provisional study approximation',
            assumptions=['TSH is the proxy for TSN ARP; northern radius 75 km.',
                'Local W1 AC–ENRIN alignment proxies AC–BU; offset 15 km west.',
                'Local R468 TSH–SAPEN alignment proxies TSH–PNH; offset 15 km north.',
                'Bien Hoa runway assumed east/west (270 degrees) through approximate chart-symbol latitude 10.976 N; offset 5 km south.'],
            source='Team zone definition and supplied area chart; user-authorized runway assumption')
    elif ident == 'VVR36':
        lat,lon = 10+32/60+25/3600,106+25/60
        ring=[]
        for bearing in range(0,361,2):
            y,x=move_position(lat,lon,bearing,15/1.852)
            ring.append([x,y])
        properties.update(kind='restricted',radius_km=15,center=[lon,lat],
                          geometry_status='coordinates supplied by team')
    else:
        raise ValueError('Zone geometry unavailable')
    return dict(type='FeatureCollection',features=[dict(type='Feature',properties=properties,
                geometry=dict(type='Polygon',coordinates=[ring]))])
