"""Centre view of the same simulator used by Approach and Tower."""
from functools import lru_cache
import json
from pathlib import Path
from flask import Blueprint, jsonify, render_template, url_for, request

from astra.airspace import geo_asset
from astra.centre import centre_point
from astra.dashboard.centre_layers import ROUTE_STYLE,star_route,arrival_feeders,transfer_waypoints,arrival_limits


def build_centre_blueprint(reader, config, integration, pipeline=None, store=None):
    bp=Blueprint('centre',__name__)
    root=Path(__file__).parent/'geo'

    @bp.get('/centre')
    def page():
        return render_template('index.html',poll_interval_s=config.poll_interval_s,
            dashboard_host=config.dashboard_host,dashboard_port=config.dashboard_port,
            separation_horizontal_nm=config.separation_horizontal_nm,
            alert_min_complexity_score=config.dashboard_alert_min_complexity_score,
            airspace_profile='hcm_fir',control_view='centre',connected_views=True,
            handoff_boundary=dict(lat=centre_point()[0],lon=centre_point()[1],radius_nm=40),
            prediction_horizons=config.prediction_horizons_min,max_horizon=config.max_prediction_horizon_min,
            geo_manifest_url=url_for('centre.geo',asset='manifest.json'),arrival_transfer_limits=arrival_limits())

    @bp.get('/supervisor')
    @bp.get('/control-room')
    def control_room():return render_template('control_room.html')

    @bp.get('/api/centre/flow')
    def gate_flow_board():
        from astra.dashboard.gate_flow_views import flow_board
        return jsonify(flow_board(reader,integration))

    @bp.get('/api/system-tests')
    def system_test_catalog():
        from astra.studies.system_tests import catalog
        from astra.studies.operational_cases import catalog as study_catalog
        return jsonify(scenarios=study_catalog()+catalog())

    @bp.post('/api/system-tests/load')
    def load_system_test():
        from astra.studies.system_tests import CASES
        from astra.studies.workbook_cases import CASES as STUDY_CASES
        body=request.get_json(silent=True)
        if not isinstance(body,dict) or not isinstance(body.get('case_id'),str) or body['case_id'] not in (*CASES,*STUDY_CASES):
            return jsonify(ok=False,error='Choose a synthetic system-test scenario'),400
        replay=getattr(reader._connector,'case_replay',None)
        if replay is None:return jsonify(ok=False,error='Standalone VVTS simulator required'),409
        try:
            status=replay.load(body['case_id'],method=body.get('method','RECONSTRUCTED'),run_id=body.get('run_id'))
            return jsonify(ok=True,replay=status)
        except (ValueError,OSError) as exc:
            return jsonify(ok=False,error=str(exc)),400

    @lru_cache(maxsize=1)
    def airways():
        data=json.loads((root/'airways.json').read_text(encoding='utf-8'))
        data['features'] += geo_asset('tsn_tma','airways.json')['features']
        return data

    @bp.get('/centre/geo/<asset>')
    def geo(asset):
        if asset=='boundary.json':return jsonify(geo_asset('tsn_tma','boundary.json'))
        if asset=='airways.json':return jsonify(airways())
        if asset=='arrival_feeders.json':return jsonify(arrival_feeders())
        if asset=='transfer_waypoints.json':return jsonify(transfer_waypoints())
        if asset.startswith('procedure_') and asset.endswith('_route.json'):
            ident=asset[len('procedure_'):-len('_route.json')]
            from astra.airspace import load_profile
            proc=load_profile('tsn_tma')['procedure_data'].get(ident)
            if proc and proc['kind']=='star':return jsonify(star_route(ident))
        if asset!='manifest.json':
            try:return jsonify(geo_asset('tsn_tma',asset))
            except ValueError:return jsonify(error='Unknown Centre layer'),404
        data=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
        data['layers']=[layer for layer in data['layers'] if layer['id']!='airports' or (root/'airports.json').exists()]
        for layer in data['layers']:
            layer['file']=url_for('static',filename=layer['file'])
            if layer['id']=='airways':
                layer.update(file=url_for('centre.geo',asset='airways.json'),default_visible=True)
                layer['style'].update(ROUTE_STYLE)
            if layer['id']=='waypoints':layer['default_visible']=True
            if layer['id']=='firs':layer['style']['fill']=None
        data['layers'].append(dict(id='vvts_handoff',label='VVTS Approach · 40 NM handoff',
            kind='polygon',file=url_for('centre.geo',asset='boundary.json'),default_visible=True,
            z_index=6,style=dict(stroke='#f6c66b',fill=None,width=1.5,dash=[8,5])))
        terminal=geo_asset('tsn_tma','manifest.json')
        from astra.airspace import load_profile
        procedures=load_profile('tsn_tma')['procedure_data']
        for layer in terminal['layers']:
            if layer['id'] in ('airways','coastlines','country_borders','centre_firs','radar_range','firs','waypoints','navaids'):
                continue
            if layer['id'] in ('point_merge_arcs','point_merge_spokes','approach','approach_fixes'):continue
            if layer['id'].startswith('procedure_'):
                ident=layer['id'].split('_')[1]
                if procedures[ident]['kind']=='star':continue
            layer['file']=url_for('centre.geo',asset=layer['file'])
            if layer['kind']=='line' and layer['id']!='runways':layer['style'].update(ROUTE_STYLE)
            data['layers'].append(layer)
        data['layers'].append(dict(id='arrival_feeders',label='STAR arrivals to transfer',kind='line',
            file=url_for('centre.geo',asset='arrival_feeders.json'),default_visible=True,z_index=3,
            style=dict(ROUTE_STYLE)))
        return jsonify(data)

    @bp.post('/api/centre/demo')
    def demo():
        replay=getattr(reader._connector,'case_replay',None)
        if getattr(replay,'active',False):
            return jsonify(ok=False,error='Kết thúc phát lại case trước khi nạp demo Centre.'),409
        reader.reset_simulation()
        if pipeline:pipeline.reset()
        if store:store.clear_trails()
        integration.connected_fir=True
        integration.study_key='centre_approach_tower'
        integration.add_arrival(callsign='CTR101',aircraft_type='A321',origin='VVNB',star='BITIS2H',
            requested_fl=300,centre_start_nm=49,arrival_route='Saved L637 feeder')
        integration.add_arrival(callsign='CTR102',aircraft_type='A320',origin='VVDN',star='DALAP2H',
            requested_fl=300,centre_start_nm=190,arrival_route='Saved N500 feeder')
        stand=min(integration.graph.stands(),key=lambda n:n.id)
        integration.add_departure(callsign='DEP101',aircraft_type='A320',stand_id=stand.id,
            sid='XOBAV2D',requested_fl=300,destination='VVCR',depart_route='Saved W9 feeder')
        integration.clear_takeoff('DEP101')
        reader.set_speed_multiplier(30)
        reader.send_command('HOLD')
        return jsonify(ok=True,message='Đã nạp demo Centre / Approach / Tower. Bấm Phát để chạy cùng đồng hồ.')

    return bp
