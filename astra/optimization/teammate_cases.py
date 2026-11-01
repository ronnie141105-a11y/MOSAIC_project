"""Reproducible evaluation and immutable replay publication for the teammate GA."""
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import statistics
import time
from uuid import uuid4

from .formulation import optimize as legacy_optimize
from .teammate_ga import VERSION, greedy_plan, optimize
from .video_cases import SEEDS, VideoCaseEvaluator
from astra.studies.case_replay import CASE_IDS, DEFAULT_ROOT

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = re.compile(r'\d{8}T\d{6}Z-[0-9a-f]{8}')
METHODS = ('TEAM_GROUND', 'TEAM_MIXED')


def saved_folder(case_id, root=DEFAULT_ROOT, run_id=None):
    if case_id not in CASE_IDS:
        raise ValueError('Unknown case scenario')
    base = Path(root)/case_id/'variants'/'team_ga'
    if run_id is None:
        pointer = json.loads((base/'latest.json').read_text(encoding='utf-8'))
        run_id = pointer.get('run_id')
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise ValueError('Invalid saved GA run identifier')
    return base/run_id


def saved_result(case_id, root=DEFAULT_ROOT):
    result = json.loads((saved_folder(case_id, root)/'results.json').read_text(encoding='utf-8'))
    if result.get('version') != VERSION or result.get('case_id') != case_id:
        raise ValueError('Saved GA result uses another case or optimizer version')
    return result


def validate_settings(case_id, seeds, population, generations, max_evaluations):
    if case_id not in CASE_IDS:
        raise ValueError('Choose nominal or holiday_peak')
    if not isinstance(seeds, (tuple, list)) or not 1 <= len(seeds) <= 10:
        raise ValueError('Provide 1 to 10 unique integer seeds')
    if any(type(s) is not int or not 0 <= s <= 2**31-1 for s in seeds) or len(set(seeds)) != len(seeds):
        raise ValueError('Seeds must be unique integers from 0 to 2147483647')
    for value, lo, hi, field in ((population,4,150,'population'),(generations,1,300,'generations'),
                               (max_evaluations,50,20000,'max_evaluations')):
        if type(value) is not int or not lo <= value <= hi:
            raise ValueError(f'{field} must be an integer from {lo} to {hi}')


def export_tables(folder, result):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    def table(name, rows):
        if not rows:
            return
        with (folder/name).open('w',newline='',encoding='utf-8-sig') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
    table('summary.csv',result['summary'])
    table('metrics.csv',[dict(method=name,**r['metrics']) for name,r in result['runs'].items()])
    table('convergence.csv',[dict(method=name,**h) for name,r in result['runs'].items() for h in r['history']])
    for method, name in result['best_methods'].items():
        table(method+'_flights.csv',result['runs'][name]['flights'])


def experiment(case_id, seeds=SEEDS, population=80, generations=150, max_evaluations=6000,
               root=DEFAULT_ROOT, compare_legacy=True, publish=True, progress=None):
    validate_settings(case_id,seeds,population,generations,max_evaluations)
    started = time.perf_counter()
    evaluator = VideoCaseEvaluator(case_id,root)
    runs = {}
    def record(name, plan, history=None, search=None):
        metrics,flights,audit=evaluator.evaluate(plan)
        runs[name]=dict(plan=plan,metrics=metrics,flights=flights,audit=audit,
                        history=history or [],search=search or {})
    record('NO_CONTROL',[[0,0]]*evaluator.n)
    # All engines/modes receive the SAME deterministic GDP incumbent and budget.
    ground, prep = greedy_plan(evaluator,'ground',max_evaluations//2)
    record('GREEDY_GROUND',ground,search=prep)
    remaining=max_evaluations-prep['total_evaluations']
    mixed, mixed_search=greedy_plan(evaluator,'mixed',remaining,ground)
    mixed_search.update(total_evaluations=prep['total_evaluations']+mixed_search['total_evaluations'],
                        total_elapsed_s=prep['total_elapsed_s']+mixed_search['total_elapsed_s'])
    record('GREEDY_MIXED',mixed,search=mixed_search)
    engines=[('TEAM',optimize)] + ([('LEGACY',legacy_optimize)] if compare_legacy else [])
    for index,seed in enumerate(seeds):
        for engine, solver in engines:
            for mode, label in (('ground','GROUND'),('mixed','MIXED')):
                plan,history,search=solver(evaluator,mode,seed,population,generations,remaining,ground)
                search.update(preparation_evaluations=prep['total_evaluations'],
                    total_evaluations=prep['total_evaluations']+search['search_evaluations'],
                    total_budget=max_evaluations,
                    total_elapsed_s=prep['total_elapsed_s']+search['search_elapsed_s'])
                record(f'{engine}_{label}_{seed}',plan,history,search)
        if progress:
            progress(dict(completed_seeds=index+1,total_seeds=len(seeds),seed=seed))
    summary=[]
    for engine,_ in engines:
        for mode in ('GROUND','MIXED'):
            method=engine+'_'+mode
            selected=[r for name,r in runs.items() if name.startswith(method+'_')]
            row=dict(method=method,seeds=len(selected),feasible_runs=sum(r['metrics']['feasible_sampled'] for r in selected))
            for key in ('objective','converted_cost','penalty','total_delay_min','arrival_conflict_pairs',
                        'arrival_departure_conflict_pairs','capacity_excess_flights','new_conflict_pairs'):
                values=[r['metrics'][key] for r in selected]
                row['mean_'+key]=statistics.mean(values)
                row['std_'+key]=statistics.stdev(values) if len(values)>1 else 0
            row['mean_runtime_s']=statistics.mean(r['search']['total_elapsed_s'] for r in selected)
            summary.append(row)
    best={method:min((n for n in runs if n.startswith(method+'_')),key=lambda n:runs[n]['metrics']['objective'])
          for method in METHODS}
    # This finer check is independent of search ranking; never relabel a residual
    # violation as feasible. Re-score baseline too so comparisons share a grid.
    if progress:
        progress(dict(completed_seeds=len(seeds),total_seeds=len(seeds),phase='validation_5s'))
    fine=VideoCaseEvaluator(case_id,root,sample_s=5)
    checks={}
    for method,name in [('NO_CONTROL','NO_CONTROL'),('GREEDY_MIXED','GREEDY_MIXED'),*best.items()]:
        metrics,_,audit=fine.evaluate(runs[name]['plan'])
        checks[method]=dict(selected_run=name,metrics=metrics,audit=audit)
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]
    code_paths=('astra/optimization/teammate_ga.py','astra/optimization/teammate_cases.py',
                'astra/optimization/video_cases.py','astra/optimization/formulation.py',
                'reference/teammate_ga/atfm_genetic_algorithm_model.py')
    result=dict(version=VERSION,run_id=run_id,case_id=case_id,case_counts=evaluator.manifest['counts'],
        input_sha256=evaluator.input_sha256,
        code_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in code_paths},
        settings=dict(seeds=list(seeds),population=population,generations=generations,
            max_evaluations=max_evaluations,compare_legacy=compare_legacy,
            crossover_probability=.8,mutation_probability=.1,elitism_fraction=.1,
            tournament_k=3,team_stagnation=30,legacy_stagnation=40,
            budget_basis='Unique objective calls including shared GDP greedy preparation and initialization',
            objective='C + 1000 * (capacity excess + violating pairs + new violating pairs)',
            ground_cost_per_min=1,speed_cost_per_delay_min=2,capacity_combined_per_hour=42,
            capacity_bins='Fixed 60 minute bins relative to case start; includes delayed tail',
            planning_min=-60,origin_lead_assumption_min=95,upstream_segment_min=20,
            speed_delay_formula='20 * reduction_pct / (100 - reduction_pct)',
            ground_levels_min=[5,10,15,20],speed_levels_pct=[5,10,15],
            sample_s=20,arrival_spacing_nm=10,arrival_same_heading_spacing_nm=20,
            same_heading_tolerance_deg=25,arrival_departure_nm=5,arrival_departure_vertical_ft=1000,
            separation_scope='40 NM, 3000–16570 ft; arrival pairs use horizontal spacing regardless of altitude'),
        baseline=runs['NO_CONTROL']['metrics'],runs=runs,summary=summary,best_methods=best,
        domain_diagnostics={mode:dict(unavoidable_arrival_pairs=evaluator.unavoidable_pairs(mode))
                            for mode in ('ground','mixed')},
        post_validation=dict(sample_s=5,scope='Selected best TEAM plans, baseline and greedy mixed only',checks=checks),
        limitations=[
            'Video labels plus synthetic paths/times, including 23 synthetic nominal arrivals; not actual FPL/ADS-B.',
            'Only arrivals receive controls; local departures remain fixed. No GDP for already airborne arrivals.',
            'Costs and capacity are study assumptions; costs retain the existing MOSAIC scale for fair comparison.',
            'Capacity alone does not establish feasibility. Residual separation violations are retained.',
            'Sampled separation is not continuous or operational validation. The finer 5 s check may find additional pairs.',
            'Speed delay shifts terminal timestamps; it assumes an upstream 20 minute segment, not a physically simulated speed change.',
            'Centre/FIR extensions are visual context and are outside this terminal optimizer.',
            'Team and legacy GA share model, incumbent and evaluation budget; stochastic operators and stagnation limits differ.'
        ],elapsed_s=time.perf_counter()-started)
    if publish:
        folder=Path(root)/case_id/'variants'/'team_ga'/run_id
        for method,name in best.items():
            target=folder/method.lower()
            evaluator.export_variant(method,runs[name],folder=target)
            manifest=json.loads((target/'manifest.json').read_text(encoding='utf-8'))
            manifest.update(optimizer_version=VERSION,optimizer_run_id=run_id,
                            optimization_validation_5s=checks[method]['metrics'])
            (target/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        export_tables(folder,result)
        # Publish the pointer only after the complete result and both tracks exist.
        pointer=folder.parent/('latest-'+run_id+'.tmp')
        pointer.write_text(json.dumps(dict(run_id=run_id)),encoding='utf-8')
        pointer.replace(folder.parent/'latest.json')
    return result
