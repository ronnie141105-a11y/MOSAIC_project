"""Chapter 3 study routes, sharing the existing mock replay adapter."""
import csv
import io
import json
import math
import os
from pathlib import Path
from threading import Lock, Thread

from flask import Response, jsonify, render_template, request
from astra.optimization.atfm import metric_rows
from astra.optimization.formulation import CASES, DEFAULT_SEEDS, VERSION, experiment


def register_formulation_routes(bp, replay):
    lock = Lock()
    root = Path(os.environ.get('MOSAIC_FORMULATION_DATA_DIR', str(Path(__file__).resolve().parents[2]/'output'/'atfm_formulation')))
    result_file = Path(os.environ.get('MOSAIC_FORMULATION_RESULTS', str(root/'existing'/'results.json')))
    state = dict(status='idle', result=None, error=None)
    if result_file.exists():
        try:
            saved = json.loads(result_file.read_text(encoding='utf-8'))
            if saved.get('formulation_version') == VERSION:
                state.update(status='done', result=saved)
        except (OSError, ValueError):
            pass

    @bp.get('/atfm-formulation')
    def formulation_page():
        return render_template('atfm_formulation.html')

    @bp.get('/api/atfm/formulation/status')
    def formulation_status():
        with lock:
            payload = dict(status=state['status'], error=state['error'], has_result=state['result'] is not None)
        return jsonify(**payload, replay=replay.status())

    @bp.get('/api/atfm/formulation/results')
    def formulation_results():
        with lock:
            if state['result'] is None:
                return jsonify(error='Chưa có kết quả.'), 404
            return jsonify(state['result'])

    @bp.post('/api/atfm/formulation/run')
    def formulation_run():
        body = request.get_json(silent=True)
        if body is None:
            body = {}
        if not isinstance(body, dict):
            return jsonify(error='JSON object required'), 400
        case = body.get('case', 'existing')
        if case not in CASES:
            return jsonify(error='Unknown synthetic case'), 400
        kwargs = dict(case=case, seeds=DEFAULT_SEEDS)
        for field, default, lower, upper in (('population', 60, 4, 150), ('generations', 150, 1, 300),
                                             ('max_evaluations', 6000, 50, 20000), ('penalty_power', 1, 1, 2)):
            value = body.get(field, default)
            if type(value) is not int or not lower <= value <= upper:
                return jsonify(error=f'{field}: integer {lower}–{upper} required'), 400
            kwargs[field] = value
        value = body.get('penalty_lambda', 1000)
        if type(value) not in (int, float) or not math.isfinite(value) or not 1 <= value <= 100000:
            return jsonify(error='penalty_lambda: finite number 1–100000 required'), 400
        kwargs['penalty_lambda'] = value
        with lock:
            if state['status'] == 'running':
                return jsonify(error='Một experiment đang chạy.'), 409
            state.update(status='running', error=None)
        def work():
            try:
                result = experiment(**kwargs)
                target = result_file if os.environ.get('MOSAIC_FORMULATION_RESULTS') else root/case/'results.json'
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_suffix('.tmp')
                tmp.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
                tmp.replace(target)
                with lock:
                    state.update(status='done', result=result)
            except Exception as exc:
                with lock:
                    state.update(status='error', error=str(exc))
        Thread(target=work, daemon=True, name='mosaic-chapter3').start()
        return jsonify(status='running'), 202

    @bp.post('/api/atfm/formulation/load')
    def formulation_load():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or body.get('case') not in CASES:
            return jsonify(error='Unknown synthetic case'), 400
        try:
            result = json.loads((root/body['case']/'results.json').read_text(encoding='utf-8'))
            if result.get('formulation_version') != VERSION or result.get('scenario', {}).get('case') != body['case']:
                return jsonify(error='Saved case uses a different formulation or scenario'), 400
        except (OSError, ValueError):
            return jsonify(error='Chưa có kết quả đã lưu cho ca này.'), 404
        with lock:
            if state['status'] == 'running':
                return jsonify(error='Một experiment đang chạy.'), 409
            state.update(result=result, status='done', error=None)
        return jsonify(status='done')

    @bp.post('/api/atfm/formulation/replay')
    def formulation_replay():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get('method'), str):
            return jsonify(error='method required'), 400
        with lock:
            selected = state['result']['runs'].get(body['method']) if state['result'] else None
        if selected is None:
            return jsonify(error='Unknown method'), 404
        replay.load(body['method'], selected['flights'])
        return jsonify(**replay.status(), metrics=selected['metrics'])

    @bp.get('/api/atfm/formulation/export.csv')
    def formulation_csv():
        with lock:
            result = state['result']
        if result is None:
            return jsonify(error='No results'), 404
        rows = metric_rows(result)
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        return Response('\ufeff'+stream.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition': 'attachment; filename=chapter3_metrics.csv'})

    @bp.get('/api/atfm/formulation/export.json')
    def formulation_json():
        with lock:
            result = state['result']
        if result is None:
            return jsonify(error='No results'), 404
        return Response(json.dumps(result, ensure_ascii=False, indent=2), mimetype='application/json',
                        headers={'Content-Disposition': 'attachment; filename=chapter3_results.json'})
