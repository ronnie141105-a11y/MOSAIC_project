"""Regressions found in the supplied optimizer plus actual evaluator integration."""
from itertools import product
import csv
from dataclasses import replace
import hashlib
from pathlib import Path
import random

import pytest

from astra.optimization.formulation import Evaluator
from astra.optimization.teammate_ga import Individual, crossover, greedy_plan, optimize
from tests.pytest.test_video_case_ga import miniature


class Toy:
    encode=Evaluator.encode
    decode=Evaluator.decode
    def __init__(self,n=2):
        self.n=n
        self.domains=[(0,1)]*n
        self.seen=[]
    def objective(self,codes):
        self.seen.append(tuple(codes))
        # A two-bit valley: greedy stays at 00; only 11 improves it.
        return 10 if sum(codes)==0 else 0 if sum(codes)==self.n else 20


def test_elite_clone_and_short_crossover():
    elite=Individual([(0,0)],objective=3)
    copy=elite.clone()
    assert copy.fitness==elite.fitness==.25
    copy.chromosome[0]=(1,5)
    assert elite.chromosome==[(0,0)]
    for n in (0,1):
        a,b=crossover(Individual([(0,0)]*n),Individual([(0,0)]*n),random.Random(1),rate=1)
        assert len(a.chromosome)==len(b.chromosome)==n
        assert a.chromosome is not b.chromosome


@pytest.mark.parametrize('n',[0,1,2])
def test_small_inputs_budget_final_archive_and_rng_isolation(n):
    evaluator=Toy(n)
    rng_state=random.getstate()
    plan,history,search=optimize(evaluator,seed=8,population=4,generations=3,max_evaluations=3)
    assert random.getstate()==rng_state
    assert len(plan)==n and search['total_evaluations']<=3
    assert len(evaluator.seen)==search['total_evaluations']
    assert history[-1]['objective']==min(10 if sum(c)==0 else 0 if sum(c)==n else 20 for c in evaluator.seen)
    assert all(a['objective']>=b['objective'] for a,b in zip(history,history[1:]))
    again=optimize(Toy(n),seed=8,population=4,generations=3,max_evaluations=3)
    assert plan==again[0] and history==again[1]


def test_improving_final_child_is_returned(monkeypatch):
    import astra.optimization.teammate_ga as module
    # Initial and greedy populations remain at 00/10/01. Only the final
    # generation's mutation supplies 11, the global minimum.
    monkeypatch.setattr(module,'_random_gene',lambda domain,rng:(0,0))
    calls=[]
    def mutate(individual,domains,rng,rate=.1):
        calls.append(rate)
        return Individual([(1,5)]*2 if rate==.1 else [(0,0)]*2)
    monkeypatch.setattr(module,'mutate',mutate)
    plan,history,_=optimize(Toy(),seed=1,population=4,generations=1,max_evaluations=50)
    assert plan==[[1,5],[1,5]] and history[-1]['generation']==1
    assert history[-1]['objective']==0 and .1 in calls


@pytest.mark.parametrize('plan',[[[0,0]],[[0,0],[9,0]],[[1,-5],[0,0]],[[True,5],[0,0]]])
def test_invalid_chromosomes_cannot_omit_flights_or_evade_cost(plan):
    with pytest.raises(ValueError):
        optimize(Toy(),incumbent=plan)


def test_real_constraints_and_exact_small_problem(tmp_path):
    evaluator=miniature(tmp_path)
    exact=min(evaluator.objective(c) for c in product(*evaluator.domains))
    plan,history,search=optimize(evaluator,seed=11,population=20,generations=50,max_evaluations=1000)
    assert evaluator.evaluate(plan)[0]['objective']==pytest.approx(exact)
    assert evaluator.evaluate(plan)[0]['feasible_sampled']
    assert search['total_evaluations']<=1000
    assert all(a['objective']>=b['objective'] for a,b in zip(history,history[1:]))


def test_airborne_gdp_restriction_is_respected(tmp_path):
    evaluator=miniature(tmp_path,eta=30)
    with pytest.raises(ValueError,match='unavailable'):
        optimize(evaluator,incumbent=[[1,5],[0,0]])
    plan,_,_=optimize(evaluator,seed=11,population=12,generations=5,max_evaluations=200)
    assert all(g[0]!=1 for g in plan)
    # A capacity-only zero penalty must NOT mask forced separation violations.
    metrics,_,_=evaluator.evaluate(plan)
    assert metrics['capacity_excess_flights']==0
    assert not metrics['feasible_sampled'] and metrics['arrival_conflict_pairs']>0


def test_greedy_is_deterministic_and_separate_from_ga():
    plan,search=greedy_plan(Toy())
    assert plan==[[0,0],[0,0]]
    assert search['total_evaluations']==3
    assert optimize(Toy(),seed=12,population=20,generations=2)[1][-1]['objective']==0


@pytest.mark.parametrize('case_id,total',[('nominal',55),('holiday_peak',80)])
def test_published_case_scores_fixed_departures_and_replay(case_id,total,tmp_path):
    from astra.dashboard.legacy_flask_app import create_app
    from astra.dashboard.store import CycleStore
    from astra.interface.state_reader import StateReader
    from astra.optimization.teammate_cases import ROOT,saved_folder,saved_result
    from astra.optimization.video_cases import VideoCaseEvaluator
    from astra.utils.config import ASTRAConfig
    result=saved_result(case_id)
    evaluator=VideoCaseEvaluator(case_id)
    assert result['input_sha256']==evaluator.input_sha256
    original_hash='ad511347d21ce21b4eff1cf728e8ace090771989f9fa449dd90bc12a3089acbb'
    assert hashlib.sha256((ROOT/'reference/teammate_ga/atfm_genetic_algorithm_model.py').read_bytes()).hexdigest()==original_hash
    for name,run in result['runs'].items():
        assert evaluator.evaluate(run['plan'])[0]==run['metrics']
        if name.startswith(('TEAM_','LEGACY_')):
            assert run['search']['total_evaluations']<=result['settings']['max_evaluations']
    fixed={f['callsign'] for f in evaluator.fixed_departures}
    signature=lambda rows:[(r['callsign'],r['time_utc'],r['lat'],r['lon'],r['altitude_ft']) for r in rows if r['callsign'] in fixed]
    for method in ('TEAM_GROUND','TEAM_MIXED'):
        folder=saved_folder(case_id)/method.lower()
        with (folder/'tracks.csv').open(encoding='utf-8-sig') as stream:
            assert signature(list(csv.DictReader(stream)))==signature(evaluator.track_rows)
    config=replace(ASTRAConfig(),airspace_profile='tsn_tma')
    reader=StateReader.for_mock(config,sim_step_s=20);reader.connect()
    client=create_app(CycleStore(),config,reader,scenarios_dir=str(tmp_path/'builder')).test_client()
    response=client.post('/api/case-scenarios/load',json=dict(case_id=case_id,method='TEAM_MIXED',run_id=result['run_id']))
    assert response.status_code==200,response.json
    state=response.json['replay']
    assert state['total']==total and state['optimizer_run_id']==result['run_id']
    assert state['optimization_metrics']==result['runs'][result['best_methods']['TEAM_MIXED']]['metrics']
    assert state['optimization_validation_5s']==result['post_validation']['checks']['TEAM_MIXED']['metrics']
    response=client.post('/api/case-scenarios/control',json=dict(action='seek',time_s=2400))
    assert response.status_code==200 and response.json['replay']['visible']>0
