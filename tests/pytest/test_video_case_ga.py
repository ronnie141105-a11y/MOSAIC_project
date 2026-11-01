"""Check the categorical adapter against actual inputs and small enumeration."""
import csv
from datetime import timedelta
from itertools import product
import json

import pytest

from astra.optimization.formulation import optimize
from astra.optimization.video_cases import VideoCaseEvaluator
from astra.studies.case_replay import DEFAULT_ROOT
from astra.studies.vvts_cases import utc


def miniature(tmp_path,eta=50):
    folder=tmp_path/'nominal';folder.mkdir()
    start=utc('2026-10-08T02:00:00Z')
    stamp=lambda minute:(start+timedelta(minutes=minute)).isoformat()
    flights=[dict(callsign=cs,direction='arrival',aircraft_type='A320',planned_event_utc=stamp(eta),simulated_slot_utc=stamp(eta)) for cs in ('A01','A02')]
    flights.append(dict(callsign='D01',direction='departure',aircraft_type='A320',planned_event_utc=stamp(80),simulated_slot_utc=stamp(80)))
    (folder/'manifest.json').write_text(json.dumps(dict(local_start=start.isoformat(),flights=flights)))
    (folder/'flights.csv').write_text('callsign\nA01\nA02\nD01\n')
    rows=[]
    for cs in ('A01','A02'):
        for i in range(31):
            rows.append(dict(callsign=cs,time_utc=stamp(eta-10+i/3),lat=10.85,lon=106.32+i*.02,altitude_ft=9000,heading_deg=90))
    rows.extend(dict(callsign='D01',time_utc=stamp(80+i),lat=12,lon=108,altitude_ft=20000,heading_deg=0) for i in range(2))
    with (folder/'tracks.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return VideoCaseEvaluator('nominal',root=tmp_path)


def test_ga_matches_enumeration_on_two_flight_conflict(tmp_path):
    evaluator=miniature(tmp_path)
    exact=min(product(*evaluator.domains),key=evaluator.objective)
    plan,history,search=optimize(evaluator,'mixed',seed=11,population=20,generations=50,max_evaluations=1000)
    metrics,_,_=evaluator.evaluate(plan)
    assert metrics['objective']==pytest.approx(evaluator.objective(exact))
    assert metrics['feasible_sampled']
    assert search['total_evaluations']<=1000
    assert all(a['objective']>=b['objective'] for a,b in zip(history,history[1:]))


def test_airborne_restriction_proves_unavoidable_pair(tmp_path):
    evaluator=miniature(tmp_path,eta=30)
    assert all(not f['ground_eligible'] for f in evaluator.flights)
    with pytest.raises(ValueError,match='unavailable'):
        evaluator.evaluate([[1,20],[0,0]])
    assert evaluator.unavoidable_pairs('mixed')==[['A01','A02']]
    for codes in product(*evaluator.domains):
        assert not evaluator.evaluate(evaluator.decode(codes))[0]['feasible_sampled']


@pytest.mark.parametrize('case_id,n,dep',[('nominal',23,32),('holiday_peak',37,43)])
def test_actual_case_inputs_and_saved_run_consistency(case_id,n,dep):
    evaluator=VideoCaseEvaluator(case_id)
    assert evaluator.n==n and len(evaluator.fixed_departures)==dep
    result=json.loads((DEFAULT_ROOT.parents[2]/'output/video_case_ga/2026-10-13'/case_id/'results.json').read_text(encoding='utf-8'))
    assert result['input_sha256']==evaluator.input_sha256
    for name,run in result['runs'].items():
        metrics,_,audit=evaluator.evaluate(run['plan'])
        assert metrics==run['metrics']
        assert metrics['feasible_sampled']==(not audit['arrival_pairs'] and not audit['arrival_departure_pairs'] and not metrics['capacity_excess_flights'])
        if name!='NO_CONTROL':assert run['search']['total_evaluations']<=6000
    original=[row for row in evaluator.track_rows if row['callsign'] in {f['callsign'] for f in evaluator.fixed_departures}]
    for variant in ('no_control','ga_ground','ga_mixed'):
        with (DEFAULT_ROOT/case_id/'variants'/variant/'tracks.csv').open(encoding='utf-8-sig') as stream:
            saved=[row for row in csv.DictReader(stream) if row['callsign'] in {f['callsign'] for f in evaluator.fixed_departures}]
        assert [(r['callsign'],r['time_utc'],r['lat'],r['lon']) for r in original]==[(r['callsign'],r['time_utc'],r['lat'],r['lon']) for r in saved]
