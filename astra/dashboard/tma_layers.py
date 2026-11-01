"""Terminal radar palette and independent/grouped layer controls."""
def transfer_layer():
    """The same always-visible handoff fixes on Centre and Approach."""
    from astra.centre import centre_point
    lat,lon=centre_point()
    return dict(id='transfer_waypoints',label='Centre / Approach transfer fixes',kind='point',
        file='transfer_waypoints.json',label_field='name',default_visible=True,
        toggleable=False,z_index=8,
        style=dict(marker='triangle',fill='#8494a2',stroke='#8494a2',size=3,
                   label_priority=True,label_size=9,label_halo='#07111d',
                   label_radial_center=[lon,lat]))


def manifest(procedures):
    def layer(ident,label,kind,color,z=2,visible=True,fill=None,dash=None,group=None):
        result=dict(id=ident,label=label,kind=kind,file=ident+'.json',
            default_visible=visible,z_index=z,style=dict(stroke=color,fill=fill,
            width=1.2,dash=dash or [],marker='triangle',size=3))
        if kind=='point':result.update(label_field='name');result['style']['fill']=color
        if group:result.update(toggle_group=group,toggle_label=label)
        return result
    layers=[
        layer('coastlines','Coastlines','line','#456273',0),
        layer('country_borders','Country borders','line','#76878d',0,dash=[4,4]),
        layer('centre_firs','FIR boundaries','polygon','#608fab',0,dash=[8,5]),
        layer('radar_range','100 NM radar range','polygon','#3b5264',0,dash=[2,7]),
        layer('firs','40 NM TMA boundary','polygon','rgba(173,153,116,0.42)',1),
        layer('VVP4','VVP4','polygon','#9c879c',1,group='zones'),
        layer('VVR19','VVR19','polygon','#9c879c',1,group='zones'),
        layer('VVR36','VVR36','polygon','#9c879c',1,group='zones'),
        layer('airways','Area / Centre routes','line','#354452',2,dash=[3,4]),
        layer('point_merge_spokes','25R point-merge fans','line','rgba(201,177,247,0.43)',3,True,dash=[3,5],group='point_merge'),
        layer('point_merge_arcs','25R point-merge fans','line','#c9b1f7',4,True,group='point_merge'),
        layer('approach','ILS 25R route + fixes','line','#b9a5ff',3,False,group='ils_25r'),
        layer('waypoints','Area waypoints','point','#b4c6d5',4),
        layer('approach_fixes','ILS 25R route + fixes','point','#b9a5ff',5,False,group='ils_25r'),
        layer('navaids','Navaids','point','#e2ce91',4),
        layer('runways','25L departures / 25R arrivals','line','#e5edf5',6),
        transfer_layer(),
    ]
    for proc in sorted(procedures.values(),key=lambda p:(p['kind'],p['id'])):
        ident=proc['id']
        route_color = '#66c9ed' if proc['kind']=='sid' else '#f2bb72'
        fix_color = '#f3dc97' if proc['kind']=='sid' else '#c4b5fd'
        for suffix,kind,z in [('route','line',3),('fixes','point',5)]:
            item=layer(f'procedure_{ident}_{suffix}',ident,kind,fix_color if kind=='point' else route_color,z,False,group=f'procedure_{ident}')
            item['toggle_section']=proc['kind'].upper()
            layers.append(item)
    fixed={'centre_firs':False,'radar_range':True,'firs':True,'airways':True,'navaids':True,'runways':True}
    for item in layers:
        if item['id'] in fixed:
            item['toggleable']=False;item['default_visible']=fixed[item['id']]
        if item.get('toggle_group')=='zones':item['toggle_label']='Restricted / prohibited zones'

        if item['id']=='firs':item['file']='boundary.json';item['style']['width']=1.0
        if item['id'] in ('VVP4','VVR19','VVR36'):item['label_field']='name'
        if item['id']=='navaids':item['label_field']='ident';item['style'].update(marker='navaid',size=5)
        if item['id']=='runways':item['style']['width']=3
        if item['id']=='point_merge_spokes':item['style']['width']=0.9
        if item['id']=='point_merge_arcs':item['style']['width']=1.8
    return dict(layers=layers)
