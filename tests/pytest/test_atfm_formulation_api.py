import json

from flask import Flask
import pytest

from astra.dashboard import formulation_routes as routes
from astra.optimization.formulation import experiment, DEFAULT_SEEDS, make_scenario


class Replay:
    def status(self):
        return dict(active=False)
    def load(self, method, flights):
        self.method, self.flights = method, flights


class ImmediateThread:
    def __init__(self, target, **kwargs):
        self.target = target
    def start(self):
        self.target()


@pytest.fixture
def client(tmp_path, monkeypatch):
    from flask import Blueprint
    monkeypatch.setenv('MOSAIC_FORMULATION_RESULTS', str(tmp_path/'results.json'))
    monkeypatch.setenv('MOSAIC_FORMULATION_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(routes, 'Thread', ImmediateThread)
    replay = Replay()
    bp = Blueprint('formula_test', __name__)
    routes.register_formulation_routes(bp, replay)
    app = Flask(__name__)
    app.register_blueprint(bp)
    return app.test_client(), replay


@pytest.mark.parametrize('field,value', [('case',[]), ('case','bad'), ('population',True),
    ('population',151), ('generations',301), ('max_evaluations',49), ('max_evaluations',None),
    ('penalty_lambda',float('nan')), ('penalty_lambda',0), ('penalty_lambda',True), ('penalty_power',3)])
def test_invalid_payload_never_reaches_search(client, monkeypatch, field, value):
    monkeypatch.setattr(routes, 'experiment', lambda **kwargs: pytest.fail('invalid request reached solver'))
    c, _ = client
    assert c.post('/api/atfm/formulation/run', json={field:value}).status_code == 400
    assert c.get('/api/atfm/formulation/status').json['status'] == 'idle'


def test_dispatch_persistence_exports_and_shared_replay(client, monkeypatch, tmp_path):
    calls = []
    scenario = make_scenario('nominal')
    scenario['flights'] = scenario['flights'][:2]
    result = experiment(seeds=(11,), population=4, generations=1, max_evaluations=50,
                        scenario_input=scenario, validate_pipeline=False)
    monkeypatch.setattr(routes, 'experiment', lambda **kwargs: calls.append(kwargs) or result)
    c, replay = client
    assert c.get('/api/atfm/formulation/export.csv').status_code == 404
    assert c.post('/api/atfm/formulation/run', json={'case':'nominal'}).status_code == 202
    assert calls == [dict(case='nominal', seeds=DEFAULT_SEEDS, population=60, generations=150,
                          max_evaluations=6000, penalty_lambda=1000, penalty_power=1)]
    assert c.get('/api/atfm/formulation/status').json['status'] == 'done'
    assert c.get('/api/atfm/formulation/export.csv').status_code == 200
    assert 'separation_conflict_pairs' in c.get('/api/atfm/formulation/export.csv').get_data(as_text=True)
    assert c.get('/api/atfm/formulation/export.json').json['summary'] == result['summary']
    saved = json.loads((tmp_path/'results.json').read_text(encoding='utf-8'))
    assert saved['formulation_version'] == result['formulation_version']
    assert c.post('/api/atfm/formulation/replay',json=[]).status_code == 400
    assert c.post('/api/atfm/formulation/replay',json={'method':'missing'}).status_code == 404
    assert c.post('/api/atfm/formulation/replay',json={'method':'GA_MIXED_11'}).status_code == 200
    assert replay.method == 'GA_MIXED_11'
    assert replay.flights == result['runs']['GA_MIXED_11']['flights']
    (tmp_path/'nominal').mkdir()
    (tmp_path/'nominal'/'results.json').write_text(json.dumps(result), encoding='utf-8')
    assert c.post('/api/atfm/formulation/load',json={'case':'../../elsewhere'}).status_code == 400
    assert c.post('/api/atfm/formulation/load',json={'case':'holiday_peak'}).status_code == 404
    assert c.post('/api/atfm/formulation/load',json={'case':'nominal'}).status_code == 200
