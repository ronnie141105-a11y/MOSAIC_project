"""Airport monitor and mock scenario controls."""
from flask import Blueprint, jsonify, render_template, request, send_from_directory
from pathlib import Path


def build_airport_blueprint(integration):
    bp = Blueprint('airport', __name__)

    @bp.before_request
    def protect_case_tracks():
        replay = getattr(integration.reader._connector, 'case_replay', None)
        if getattr(replay, 'active', False) and request.method in ('POST','PATCH','DELETE'):
            return jsonify(ok=False,error='End the loaded case before changing its saved traffic tracks.'),409

    @bp.get('/airport')
    def page():
        return render_template('airport.html')

    @bp.get('/airport/assets/<path:name>')
    def asset(name):
        if name not in ('tsn_labeled.svg',):
            return jsonify(ok=False, error='Unknown asset'), 404
        return send_from_directory(Path(__file__).parent, name)

    @bp.get('/airport/state')
    def state():
        payload = integration.state()
        replay = getattr(integration.reader._connector, 'case_replay', None)
        if replay:
            payload['case_replay'] = replay.status()
            if replay.active:payload=replay.tower_view(payload)
        return jsonify(ok=True, **payload)

    @bp.get('/api/operations/state')
    def operations_state():
        replay = getattr(integration.reader._connector, 'case_replay', None)
        case_status = replay.status() if replay else None
        with integration._lock:
            return jsonify(ok=True, available=not replay_active(), blocked_reason=replay_message,
                           case_replay=case_status,
                           **integration.flow.state())

    replay_message = 'The active replay follows saved baseline tracks. End replay or load an airport study scenario to use tactical weather and ATFM controls.'

    def replay_active():
        connector = integration.reader._connector
        return any(getattr(getattr(connector, name, None), 'active', False)
                   for name in ('atfm_replay', 'case_replay'))

    def operation_action(action):
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(ok=False, error='JSON object required.'), 400
        try:
            with integration._lock:
                if replay_active():
                    return jsonify(ok=False, error=replay_message), 409
                result = action(body)
            return jsonify(ok=True, **result)
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @bp.post('/api/operations/weather')
    def weather():
        return operation_action(integration.flow.set_weather)

    @bp.post('/api/operations/review')
    def review():
        return operation_action(integration.flow.review)

    @bp.post('/api/operations/apply')
    def apply():
        return operation_action(lambda body: integration.flow.apply(body.get('token')))

    @bp.post('/api/operations/cancel')
    def cancel():
        def cancel_program(body):
            integration.flow.cancel()
            return integration.flow.state()
        return operation_action(cancel_program)

    @bp.get('/airport/layout')
    def layout():
        graph = integration.graph
        return jsonify(ok=True,
            display_reference=dict(runway_bearing_deg=249.1,metres_per_unit=2.74,
                threshold={k:integration.profile['waypoint_data']['RW25R'][k] for k in ('lat','lon')},
                anchor=dict(x=graph.node('n125').x,y=graph.node('n125').y),
                source='VVTS AD 2.12, true bearing',
                source_url='https://aim.vatm.vn/images/stories/vnaic.vn/SanPhamDichVu/AIPVietNam/AIP/2025-08-07-AIRAC/html/eAIP/VV-AD-2.VVTS-en-GB.html'),
            nodes=[dict(id=n.id, name=n.name, type=n.type, x=n.x, y=n.y)
                   for n in graph.nodes.values()],
            paths=[dict(id=p.id, name=p.name, type=p.type, ids=p.node_ids)
                   for p in graph.paths])

    @bp.post('/airport/departures')
    def departure():
        try:
            return jsonify(ok=True, fpl=integration.add_departure(**(request.get_json(silent=True) or {})))
        except (TypeError, ValueError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @bp.post('/airport/arrivals')
    def arrival():
        try:
            return jsonify(ok=True, fpl=integration.add_arrival(**(request.get_json(silent=True) or {})))
        except (TypeError, ValueError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @bp.post('/airport/clearance')
    def clearance():
        body = request.get_json(silent=True) or {}
        try:
            if body.get('type') == 'takeoff':
                integration.clear_takeoff(body['callsign'])
            elif body.get('type') == 'crossing':
                integration.clear_crossing(body['callsign'])
            else:
                raise ValueError('Choose takeoff or crossing clearance.')
        except (KeyError, ValueError) as exc:
            return jsonify(ok=False, error=str(exc)), 400
        return jsonify(ok=True)

    @bp.get('/airport/point-merge/<callsign>')
    def point_merge_status(callsign):
        return jsonify(ok=True, **integration.point_merge_status(callsign))

    @bp.post('/airport/point-merge/clearance')
    def point_merge_clearance():
        body = request.get_json(silent=True) or {}
        try:
            decision = integration.clear_point_merge(body['callsign'])
        except (KeyError, ValueError) as exc:
            return jsonify(ok=False, error=str(exc)), 409
        return jsonify(ok=True, **decision)

    @bp.post('/airport/reroute')
    def reroute():
        body = request.get_json(silent=True) or {}
        try:
            route = integration.reroute_ground(body['callsign'], body['target_id'],
                                               queue=body.get('queue', False) is True)
        except (KeyError, ValueError) as exc:
            return jsonify(ok=False, error=str(exc)), 400
        return jsonify(ok=True, route=route)

    @bp.post('/airport/restore-route')
    def restore_route():
        body = request.get_json(silent=True) or {}
        try:
            route = integration.restore_planned_route(body['callsign'])
        except (KeyError, ValueError) as exc:
            return jsonify(ok=False, error=str(exc)), 400
        return jsonify(ok=True, route=route)

    return bp
