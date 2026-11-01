from types import SimpleNamespace
import random
import numpy as np
import pytest

from astra.optimization.hybrid_ga import optimize,sequence_move


class Valley:
    def __init__(self):
        self.n=3;self.options=((0,0),(1,1),(1,2))
        self.domains=[(0,1,2)]*3
        self.metadata=[dict(callsign=f'D{i}',direction='departure',origin_status_at_planning='PARKED') for i in range(3)]
        self.events=np.asarray([[i*120+c*60 for c in range(3)] for i in range(3)])
        self.s=dict(minimum_takeoff_gap_s=120)
        self.calls=[]
    def encode(self,plan,mode='mixed'):return [self.options.index(tuple(g)) for g in plan]
    def decode(self,codes):return [list(self.options[c]) for c in codes]
    def objective(self,codes):
        self.calls.append(tuple(codes))
        return 2 if all(c==2 for c in codes) else 10+sum(codes)


def test_hybrid_budget_reproducibility_archive_and_diversity_restart():
    a=Valley();before=random.getstate()
    plan,history,info=optimize(a,'ground',11,12,35,27)
    assert random.getstate()==before
    assert len(a.calls)==info['search_evaluations']<=27
    assert len(set(a.calls))==len(a.calls)
    assert history[-1]['objective']==min(2 if all(c==2 for c in cset) else 10+sum(cset) for cset in a.calls)
    assert all(a['objective']>=b['objective'] for a,b in zip(history,history[1:]))
    again=optimize(Valley(),'ground',11,12,35,27)
    assert plan==again[0] and history==again[1]


def test_native_execution_selects_measured_incumbent_not_best_projection():
    e=Valley();native_calls=[]
    def execute(plan,generation):
        codes=e.encode(plan);native_calls.append(tuple(codes))
        # More aggressive controls look attractive in projection, but incur
        # taxi metering in execution. Preserve the measured FCFS fallback.
        return dict(metrics=dict(objective=5+sum(codes)),executed_plan=plan)
    plan,history,info=optimize(e,'ground',11,12,35,27,native=execute,native_budget=3)
    assert plan==[[0,0]]*3
    assert 1<=len(native_calls)==info['native_checks']<=3
    assert all(a['best_objective']>=b['best_objective'] for a,b in zip(info['native_history'],info['native_history'][1:]))
    assert info['selection_basis']=='native_execution'


def test_sequence_operator_keeps_committed_aircraft_and_delay_limits():
    e=Valley();e.metadata[0]['origin_status_at_planning']='HOLDING'
    result=sequence_move(e,(0,0,0),random.Random(5))
    assert result[0]==0
    assert all(c in d for c,d in zip(result,e.domains))


def test_sequence_swap_is_disabled_even_for_ready_parked_departures():
    e=Valley();e.options=((0,0),*[(1,d) for d in range(9)])
    e.domains=[(0,),tuple(range(10)),tuple(range(10))]
    e.metadata[0]['origin_status_at_planning']='LINING_UP'
    e.events=np.asarray([[100]*10,[300,*range(200,681,60)],[600,*range(180,661,60)]])
    result=sequence_move(e,(0,0,0),random.Random(5))
    assert result==(0,0,0)


def test_coarse_native_warm_start_is_retained_when_finer_proxy_is_misleading():
    e=Valley();calls=[]
    def execute(plan,generation):
        codes=tuple(e.encode(plan));calls.append(codes)
        return dict(metrics=dict(objective=5 if codes==(2,2,2) else 80+sum(codes)),executed_plan=plan)
    plan,_,info=optimize(e,'ground',11,12,30,27,native=execute,native_budget=3,
        coarse_incumbent=[[1,2]]*3)
    assert plan==[[1,2]]*3
    assert calls[:2]==[(0,0,0),(2,2,2)]
    assert info['coarse_warm_start'] and info['execution_error_samples']==info['native_checks']<=3


def test_coordinated_arrival_controls_cross_a_single_aircraft_penalty_valley():
    e=Valley();e.n=2;e.options=((0,0),(2,1),(2,2),(2,3));e.domains=[(0,1,2,3)]*2
    e.metadata=[dict(callsign=f'A{i}',direction='arrival',route_family='W1') for i in range(2)]
    e.s.update(speed_levels_pct=[1,2,3])
    e.objective=lambda codes:2 if tuple(codes)==(1,1) else 10 if tuple(codes)==(0,0) else 100
    plan,_,_=optimize(e,'mixed',11,12,30,16)
    assert plan==[[2,1],[2,1]]


@pytest.mark.parametrize('kwargs',[dict(mode='bad'),dict(native_budget=0),dict(population=1),dict(max_evaluations=0)])
def test_hybrid_rejects_invalid_controls(kwargs):
    params=dict(mode='ground',seed=11);params.update(kwargs)
    with pytest.raises(ValueError):optimize(Valley(),**params)
