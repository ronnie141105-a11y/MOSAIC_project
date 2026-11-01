"""Validate jobs before dispatch and preserve published runs after failures."""
import json
from types import SimpleNamespace

from flask import Blueprint, Flask
import pytest

from astra.dashboard import teammate_ga_routes as routes
from astra.optimization.teammate_cases import VERSION, saved_folder


class ImmediateThread:
    def __init__(self,target,**kwargs):
        self.target=target
    def start(self):
        self.target()


@pytest.fixture
def client(tmp_path,monkeypatch):
    bp=Blueprint('test_team_ga',__name__)
    monkeypatch.setattr(routes,'Thread',ImmediateThread)
    routes.register_teammate_routes(bp,SimpleNamespace(root=tmp_path))
    app=Flask(__name__);app.register_blueprint(bp)
    return app.test_client(),tmp_path


@pytest.mark.parametrize('body',[[],None,{'case_id':'../nominal'}, {'seeds':[]},
    {'seeds':[11,11]}, {'seeds':[True]}, {'seeds':[{}]}, {'population':True},
    {'population':151}, {'generations':0}, {'max_evaluations':49}, {'compare_legacy':1}])
def test_invalid_request_does_not_dispatch(client,monkeypatch,body):
    c,_=client
    monkeypatch.setattr(routes,'experiment',lambda **kwargs:pytest.fail('invalid request dispatched'))
    assert c.post('/api/case-scenarios/optimizer/run',json=body).status_code==400
    assert c.get('/api/case-scenarios/optimizer/status').json['status']=='idle'


def test_dispatch_saved_results_and_errors_preserve_previous_run(client,monkeypatch):
    c,root=client
    run_id='20261020T120000Z-1234abcd'
    folder=root/'nominal/variants/team_ga'/run_id
    calls=[]
    def work(**kwargs):
        calls.append(kwargs)
        kwargs['progress'](dict(completed_seeds=1,total_seeds=1))
        folder.mkdir(parents=True)
        (folder/'results.json').write_text(json.dumps(dict(version=VERSION,case_id='nominal',run_id=run_id)))
        (folder.parent/'latest.json').write_text(json.dumps(dict(run_id=run_id)))
    monkeypatch.setattr(routes,'experiment',work)
    assert c.get('/api/case-scenarios/optimizer/results?case_id=nominal').status_code==404
    assert c.post('/api/case-scenarios/optimizer/run',json={'seeds':[11]}).status_code==202
    assert calls[0]['seeds']==[11] and calls[0]['compare_legacy'] is True
    assert calls[0]['root']==root
    status=c.get('/api/case-scenarios/optimizer/status').json
    assert status['status']=='done' and status['progress']['completed_seeds']==1
    response=c.get('/api/case-scenarios/optimizer/results?case_id=nominal&download=1')
    assert response.status_code==200 and response.json['run_id']==run_id
    assert 'attachment' in response.headers['Content-Disposition']
    def fail(**kwargs):
        raise ValueError('test failure')
    monkeypatch.setattr(routes,'experiment',fail)
    c.post('/api/case-scenarios/optimizer/run',json={'seeds':[11]})
    assert c.get('/api/case-scenarios/optimizer/status').json['status']=='error'
    assert c.get('/api/case-scenarios/optimizer/results?case_id=nominal').json['run_id']==run_id


def test_second_job_is_rejected_while_running(client,monkeypatch):
    class WaitingThread:
        def __init__(self,**kwargs):
            pass
        def start(self):
            pass
    monkeypatch.setattr(routes,'Thread',WaitingThread)
    c,_=client
    assert c.post('/api/case-scenarios/optimizer/run',json={'seeds':[11]}).status_code==202
    assert c.post('/api/case-scenarios/optimizer/run',json={'seeds':[22]}).status_code==409


def test_saved_pointer_cannot_escape_case_folder(tmp_path):
    folder=tmp_path/'nominal/variants/team_ga';folder.mkdir(parents=True)
    (folder/'latest.json').write_text(json.dumps(dict(run_id='../../outside')))
    with pytest.raises(ValueError,match='identifier'):
        saved_folder('nominal',tmp_path)
