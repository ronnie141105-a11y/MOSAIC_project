"""Run the reviewed teammate optimizer without blocking the simulation clock."""
from threading import Lock, Thread

from flask import jsonify, request

from astra.optimization.teammate_cases import experiment, saved_result, validate_settings
from astra.studies.workbook_cases import CASES as WORKBOOK_CASES, ROOT as WORKBOOK_ROOT


def register_teammate_routes(bp,replay):
    lock=Lock()
    state=dict(status='idle',case_id=None,error=None,progress={})

    @bp.get('/api/case-scenarios/optimizer/status')
    def optimizer_status():
        with lock:
            return jsonify(dict(state))

    @bp.get('/api/case-scenarios/optimizer/results')
    def optimizer_results():
        try:
            case_id=request.args.get('case_id','nominal')
            if case_id in WORKBOOK_CASES:
                from astra.optimization.full_route_cases import saved_result as full_result
                result=full_result(case_id,WORKBOOK_ROOT)
            else:
                result=saved_result(case_id,replay.root)
        except (ValueError,OSError) as exc:
            return jsonify(error=str(exc)),404
        response=jsonify(result)
        if request.args.get('download')=='1':
            response.headers['Content-Disposition']=f'attachment; filename="MOSAIC_{result["case_id"]}_{result["run_id"]}.json"'
        return response

    @bp.post('/api/case-scenarios/optimizer/run')
    def optimizer_run():
        body=request.get_json(silent=True)
        if not isinstance(body,dict):
            return jsonify(error='JSON object required'),400
        kwargs=dict(case_id=body.get('case_id','nominal'),seeds=body.get('seeds',[11,22,33]),
                    population=body.get('population',80),generations=body.get('generations',150),
                    max_evaluations=body.get('max_evaluations',6000),
                    compare_legacy=body.get('compare_legacy',True),root=replay.root)
        try:
            full_route=kwargs['case_id'] in WORKBOOK_CASES if isinstance(kwargs['case_id'],str) else False
            if full_route and 'seeds' not in body:kwargs['seeds']=list(range(11,111,11))
            validate_settings('nominal' if full_route else kwargs['case_id'],kwargs['seeds'],kwargs['population'],
                              kwargs['generations'],kwargs['max_evaluations'])
            if type(kwargs['compare_legacy']) is not bool:
                raise ValueError('compare_legacy must be true or false')
        except (ValueError,TypeError) as exc:
            return jsonify(error=str(exc)),400
        with lock:
            if state['status']=='running':
                return jsonify(error='Một lượt tối ưu đang chạy.'),409
            state.update(status='running',case_id=kwargs['case_id'],error=None,
                         progress=dict(completed_seeds=0,total_seeds=len(kwargs['seeds']),phase='setup'))
        def progress(update):
            with lock:
                state['progress']=dict(update)
        def work():
            try:
                if full_route:
                    from astra.optimization.full_route_cases import experiment as full_experiment
                    full_kwargs={key:value for key,value in kwargs.items() if key not in ('root','compare_legacy')}
                    full_experiment(**full_kwargs,root=WORKBOOK_ROOT,progress=progress)
                else:
                    experiment(**kwargs,progress=progress)
                with lock:
                    state.update(status='done')
            except Exception as exc:
                with lock:
                    state.update(status='error',error=str(exc))
        Thread(target=work,daemon=True,name='mosaic-teammate-ga').start()
        return jsonify(status='running',case_id=kwargs['case_id']),202
