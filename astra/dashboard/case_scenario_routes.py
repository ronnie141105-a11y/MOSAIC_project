"""Controls for reconstructed AirNav video study scenarios."""
from pathlib import Path
from flask import Blueprint, jsonify, request, render_template, send_file
from astra.studies.case_replay import CaseStudyReplay


def build_case_scenario_blueprint(reader, pipeline=None, store=None, root=None):
    bp = Blueprint('case_scenarios', __name__)
    replay = CaseStudyReplay(reader, pipeline, store, **({'root':root} if root else {}))
    bp.case_replay = replay

    @bp.get('/case-scenarios')
    def page():
        return render_template('case_scenarios.html')

    @bp.get('/case-scenarios/model-guide')
    def model_guide():
        return send_file(Path(__file__).resolve().parents[2]/'docs/Gate_flow_ATFM.md',as_attachment=True)

    @bp.get('/case-scenarios/handout/<asset>')
    def handout(asset):
        project=Path(__file__).resolve().parents[2]
        assets={
            'summary':'thesis_summary/thesis_summary.md',
            'notes':'thesis_summary/presentation_notes.md',
            'figure':'thesis_summary/comparison.png',
            'figure-pdf':'thesis_summary/comparison.pdf',
            'data':'thesis_summary/results.csv',
            'technical':'fcfs_ga_comparison/report.md',
        }
        if asset not in assets:return jsonify(error='Unknown study handout'),404
        # Reports from the free-resequencing model must never accompany the
        # fixed-FIFO studies as though they were current evidence.
        import json
        from astra.optimization.full_route_cases import VERSION, saved_result
        evidence=project/'output/thesis_summary/source_runs.json'
        try:
            sources=json.loads(evidence.read_text(encoding='utf-8'))
            current=all(sources[c]['version']==VERSION and
                sources[c]['run_id']==saved_result(c)['run_id'] for c in ('workbook_low_20','workbook_peak_50'))
        except (OSError,ValueError,KeyError):current=False
        if not current:return jsonify(error='These handouts describe the previous model. Use the current results JSON; new thesis figures need regeneration.'),409
        path=project/'output'/assets[asset]
        if not path.is_file():return jsonify(error='Generate the study handouts first'),404
        return send_file(path,as_attachment=True,download_name=path.name)

    @bp.get('/api/case-scenarios')
    def catalog():
        return jsonify(cases=replay.catalog(), replay=replay.status())

    @bp.post('/api/case-scenarios/load')
    def load():
        try:
            body=request.get_json(silent=True)
            if not isinstance(body,dict): raise ValueError('JSON object required')
            return jsonify(ok=True, replay=replay.load(body.get('case_id'),body.get('method','RECONSTRUCTED'),body.get('enroute',False),body.get('run_id')))
        except (ValueError, TypeError, OSError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @bp.post('/api/case-scenarios/control')
    def control():
        try:
            body=request.get_json(silent=True)
            if not isinstance(body,dict): raise ValueError('JSON object required')
            action=body.get('action')
            if action=='stop':
                reader.reset_simulation()
                if pipeline: pipeline.reset()
                if store: store.clear_trails()
            elif not replay.active:
                raise ValueError('Load a case first')
            elif action=='seek':
                replay.seek(body.get('time_s'))
            elif action in ('play','pause'):
                reader.send_command('OP' if action=='play' else 'HOLD')
            elif action=='speed':
                speed=float(body.get('multiplier'))
                if speed not in (1,5,10,30,60): raise ValueError('Choose 1, 5, 10, 30 or 60 times speed')
                reader.set_speed_multiplier(speed)
            else: raise ValueError('Unknown replay action')
            return jsonify(ok=True, replay=replay.status())
        except (ValueError,TypeError) as exc:
            return jsonify(ok=False,error=str(exc)),400
    from astra.dashboard.teammate_ga_routes import register_teammate_routes
    register_teammate_routes(bp,replay)
    return bp
