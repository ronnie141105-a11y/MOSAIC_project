"""Local ATFM Lab: bounded background experiments and mock-only replay."""
import json
import os
from pathlib import Path
from threading import Lock,Thread
from flask import Blueprint,jsonify,render_template,request,Response
from astra.optimization.atfm import experiment,metric_rows
from astra.optimization.replay import ATFMReplay


def build_atfm_blueprint(reader,config,pipeline,store):
    bp=Blueprint('atfm',__name__);lock=Lock();state={'status':'idle','result':None,'error':None}
    replay=ATFMReplay(reader,pipeline,store)
    result_file=Path(os.environ.get('MOSAIC_ATFM_RESULTS',str(Path(__file__).resolve().parents[2]/'output'/'atfm_lab'/'results.json')))
    if result_file.exists():
        try:state.update(status='done',result=json.loads(result_file.read_text(encoding='utf-8')))
        except (OSError,ValueError):pass

    @bp.get('/atfm')
    def page():return render_template('atfm.html')

    @bp.get('/api/atfm/status')
    def status():
        with lock:payload=dict(status=state['status'],error=state['error'],has_result=state['result'] is not None)
        return jsonify(**payload,replay=replay.status())

    @bp.get('/api/atfm/results')
    def results():
        with lock:
            if state['result'] is None:return jsonify(error='Chưa có kết quả.'),404
            return jsonify(state['result'])

    @bp.post('/api/atfm/run')
    def run():
        body=request.get_json(silent=True)
        if body is None:body={}
        if not isinstance(body,dict):return jsonify(error='JSON object required'),400
        generations=body.get('generations',100);population=body.get('population',60)
        if type(generations) is not int or type(population) is not int or not 1<=generations<=200 or not 4<=population<=100:
            return jsonify(error='Generations 1–200; population 4–100.'),400
        with lock:
            if state['status']=='running':return jsonify(error='Một experiment đang chạy.'),409
            state.update(status='running',error=None)
        def work():
            try:
                result=experiment(population=population,generations=generations)
                result_file.parent.mkdir(parents=True,exist_ok=True)
                tmp=result_file.with_suffix('.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8');tmp.replace(result_file)
                with lock:state.update(result=result,status='done')
            except Exception as exc:
                with lock:state.update(status='error',error=str(exc))
        Thread(target=work,daemon=True,name='mosaic-atfm-experiment').start()
        return jsonify(status='running'),202

    @bp.post('/api/atfm/replay')
    def load():
        body=request.get_json(silent=True) or {}
        if not isinstance(body,dict) or not isinstance(body.get('method'),str):return jsonify(error='method required'),400
        with lock:
            result=state['result'];selected=result['runs'].get(body['method']) if result else None
        if selected is None:return jsonify(error='Unknown result method'),404
        replay.load(body['method'],selected['flights'])
        return jsonify(replay.status())

    @bp.post('/api/atfm/pause')
    def pause():
        reader.send_command('HOLD');return jsonify(replay.status())

    @bp.get('/api/atfm/export.csv')
    def export_csv():
        import csv,io
        with lock:result=state['result']
        if result is None:return jsonify(error='No results'),404
        rows=metric_rows(result)
        stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        return Response('\ufeff'+stream.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=atfm_metrics.csv'})

    bp.atfm_replay=replay
    return bp
