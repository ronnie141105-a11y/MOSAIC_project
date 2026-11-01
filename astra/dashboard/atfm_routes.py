"""Local ATFM Lab: bounded background experiments and mock-only replay."""
import json
import math
import os
from pathlib import Path
from threading import Lock,Thread
from flask import Blueprint,jsonify,render_template,request,Response
from astra.optimization.atfm import experiment,metric_rows
from astra.optimization.uncertainty import uncertainty_experiment
from astra.optimization.replay import ATFMReplay


def build_atfm_blueprint(reader,config,pipeline,store):
    bp=Blueprint('atfm',__name__);lock=Lock();state={'status':'idle','result':None,'error':None,'mode':None}
    replay=ATFMReplay(reader,pipeline,store)
    if reader is not None:
        reader._connector.atfm_replay = replay
    result_file=Path(os.environ.get('MOSAIC_ATFM_RESULTS',str(Path(__file__).resolve().parents[2]/'output'/'atfm_lab'/'results.json')))
    if result_file.exists():
        try:state.update(status='done',result=json.loads(result_file.read_text(encoding='utf-8')))
        except (OSError,ValueError):pass

    @bp.get('/atfm')
    def page():return render_template('atfm.html')

    @bp.get('/api/atfm/status')
    def status():
        with lock:payload=dict(status=state['status'],error=state['error'],has_result=state['result'] is not None,mode=state['mode'])
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
        mode=body.get('mode','deterministic')
        if mode not in ('deterministic','uncertainty'):
            return jsonify(error='Mode must be deterministic or uncertainty.'),400
        generations=body.get('generations',60 if mode=='uncertainty' else 100)
        population=body.get('population',40 if mode=='uncertainty' else 60)
        if type(generations) is not int or type(population) is not int or not 1<=generations<=200 or not 4<=population<=100:
            return jsonify(error='Generations 1–200; population 4–100.'),400
        kwargs=dict(population=population,generations=generations)
        budget=body.get('max_evaluations',6000 if mode=='uncertainty' else None)
        if budget is not None:
            if type(budget) is not int or not 50<=budget<=20000:
                return jsonify(error='Evaluation budget must be an integer from 50 to 20000.'),400
            kwargs['max_evaluations']=budget
        elif mode=='uncertainty':
            return jsonify(error='Uncertainty mode requires an evaluation budget from 50 to 20000.'),400
        if mode=='uncertainty':
            for field,default,upper in [('risk_weight',.25,1),('eta_jitter_min',2,10)]:
                value=body.get(field,default)
                if type(value) not in (int,float) or not 0<=value<=upper or not math.isfinite(value):
                    return jsonify(error=f'{field} must be a finite number from 0 to {upper}.'),400
                kwargs[field]=value
            drop=body.get('capacity_drop',1)
            if type(drop) is not int or not 0<=drop<=2:
                return jsonify(error='capacity_drop must be an integer from 0 to 2.'),400
            kwargs['capacity_drop']=drop
        with lock:
            if state['status']=='running':return jsonify(error='Một experiment đang chạy.'),409
            state.update(status='running',error=None,mode=mode)
        def work():
            try:
                result=(uncertainty_experiment if mode=='uncertainty' else experiment)(**kwargs)
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
        if not rows:return jsonify(error='No result metrics'),404
        stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        return Response('\ufeff'+stream.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=atfm_metrics.csv'})

    @bp.get('/api/atfm/uncertainty.csv')
    def export_uncertainty_csv():
        import csv,io
        with lock:result=state['result']
        rows=result.get('uncertainty_summary',[]) if result else []
        if not rows:return jsonify(error='No uncertainty results'),404
        stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        return Response('\ufeff'+stream.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=uncertainty_summary.csv'})

    @bp.get('/api/atfm/uncertainty-realizations.json')
    def export_uncertainty_realizations():
        with lock:result=state['result']
        if not result or not result.get('uncertainty'):return jsonify(error='No uncertainty results'),404
        return Response(json.dumps(result['uncertainty'],ensure_ascii=False,indent=2),mimetype='application/json',
                        headers={'Content-Disposition':'attachment; filename=uncertainty_realizations.json'})

    bp.atfm_replay=replay
    from .formulation_routes import register_formulation_routes
    register_formulation_routes(bp,replay)
    return bp
