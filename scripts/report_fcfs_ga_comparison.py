"""Export the latest validated two-case comparison as CSV, Markdown and plots.

Run with the project venv after run_full_route_studies.py. Matplotlib is only
needed for this offline reporting command, never for the simulator or GA.
"""
from pathlib import Path
import csv
import json
import shutil
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from astra.optimization.full_route_cases import saved_result,export_comparison
from astra.studies.workbook_cases import CASES


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np

    out=Path('output/fcfs_ga_comparison');out.mkdir(parents=True,exist_ok=True)
    archive=Path('output/scenario_revision_20261031/previous_comparison')
    if not archive.exists():shutil.copytree(out,archive)
    results=[saved_result(case) for case in sorted(CASES)]
    comparison=export_comparison()
    (out/'comparison.csv').write_bytes(comparison.read_bytes())
    (out/'results_snapshot.json').write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
    trial_rows=[dict(case_id=r['case_id'],run_id=r['run_id'],method=t['method'],trial=t['run'],seed=t['seed'],
        **{k:v for k,v in t['metrics'].items() if not isinstance(v,dict)}) for r in results for t in r['native_trials']]
    with (out/'all_native_trials.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(trial_rows[0]));writer.writeheader();writer.writerows(trial_rows)
    benchmark_rows=[dict(case_id=r['case_id'],selected=r['fcfs_selected_resolution'],method=b['method'],**b['metrics']) for r in results for b in r['fcfs_benchmarks']]
    with (out/'fcfs_benchmarks.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(benchmark_rows[0]));writer.writeheader();writer.writerows(benchmark_rows)
    attribution=[]
    for r in results:
        for t in r['native_trials']:
            if not t['method'].startswith('TEAM_'):continue
            search=r['runs'][t['run']]['search']
            warm=min(h['candidate_objective'] for h in search['native_history'] if h['generation']<0)
            attribution.append(dict(case_id=r['case_id'],method=t['method'],seed=t['seed'],
                best_initial_native_objective=warm,final_native_objective=t['metrics']['objective'],
                improvement_after_initialization=warm-t['metrics']['objective']))
    with (out/'initialization_attribution.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(attribution[0]));writer.writeheader();writer.writerows(attribution)

    labels=['Reference','FCFS','GA ground','GA mixed']
    colors=['#a4adb6','#d59b32','#4585c4','#299d82']
    measures=[('total_delay_min','Event delay (aircraft-min)'),
              ('sector_excess_aircraft_minutes','Sector excess (aircraft-min)'),
              ('completion_time_s','Last flight completed (min)')]
    fig,axes=plt.subplots(2,3,figsize=(13,7.8),layout='constrained')
    for row,result in enumerate(results):
        for col,(key,title) in enumerate(measures):
            ax=axes[row,col];scale=60 if key=='completion_time_s' else 1
            means=[s['mean_'+key]/scale for s in result['native_summary']]
            deviations=[s['std_'+key]/scale for s in result['native_summary']]
            ax.bar(labels,means,yerr=deviations,color=colors,capsize=4,width=.65)
            for x,mean in enumerate(means):ax.annotate(f'{mean:.1f}',(x,mean),xytext=(0,7),textcoords='offset points',ha='center',fontsize=9)
            for x,s in enumerate(result['native_summary']):
                values=[t['metrics'][key]/scale for t in result['native_trials'] if t['method']==s['method']]
                ax.scatter(np.linspace(x-.1,x+.1,len(values)),values,color='#243547',s=11,zorder=3)
            ax.set_title(('Nominal: 20 aircraft' if row==0 else 'Overload: 60 aircraft')+'\n'+title,fontsize=11)
            ax.set_ylim(0,max(1,max(a+b for a,b in zip(means,deviations))*1.2))
            ax.spines[['top','right']].set_visible(False);ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True)
            ax.tick_params(axis='x',labelsize=9)
    fig.suptitle('FCFS vs GA — complete native execution, 1-second validation',fontsize=15)
    fig.supxlabel('GA bars: mean ± sample SD across ten fixed seeds 11, 22, …, 110; dots: individual executions. Reference already includes safety sequencing.',fontsize=10)
    fig.savefig(out/'comparison.png',dpi=180)
    fig.savefig(out/'comparison.pdf')
    plt.close(fig)

    lines=['# FCFS and GA: two-case ten-seed experiment','',
        'These are synthetic stand-to-stand simulations, retaining 11 arrivals + 9 departures in the nominal case and 36 arrivals + 24 departures in overload. All arrivals start airborne and moving. No holding circuits are introduced.','',
        '## Comparison design','',
        '- Reference: existing safety-sequenced scenario, without additional ATFM regulation.',
        '- FCFS: retain fixed requested readiness order after committed surface aircraft; assign the earliest available ground-delay action that adds no sampled safety violation or additional sector excess beyond committed traffic.',
        '- GA ground: optimize departure CTOT delays and the order of aircraft still parked. This is the main comparison with FCFS.',
        '- GA mixed: also allow 1/2/3/5/10/15% speed reduction on eligible Centre arrival legs, including coordinated changes to a route cohort. Its advantage includes a broader action set.',
        '- Both use the same initial states, routes, altitude profiles, sector capacities, native surface controller, 0/1/2/…/60 minute departure-delay domain and cost weights. Aircraft already taxiing or holding retain priority.',
        '- Hybrid GA: sequence swaps for parked departures, route-cohort crossover, coordinated arrival mutation, one-minute local refinement and diversity restarts. Population 60, up to 120 generations, at most 6,000 fast objective calls per method/seed including fine/coarse FCFS warm starts; ten fixed seeds 11, 22, …, 110.',
        '- Native feedback: up to four separately counted complete execution checkpoints per method/seed, including warm starts. A local execution-error estimate guides subsequent search. The final plan is chosen by measured native objective, retaining a native-tested FCFS fallback. Fast-call counts alone do not represent total computation.',
        '- Prediction: native one-second arrival trajectories and one-second arrival-pair checks; 20-second occupancy/mixed-pair screening. Every final seed is measured in complete one-second native execution. Safety metering can extend CTOT holds or withdraw speed proposals; all such changes count in the final results.',
        '- Native delay cost = ground-delay minutes + 2 × arrival-delay minutes. Objective = cost + 10,000 × sector excess aircraft-minutes once safety violations have been eliminated.',
        '- Capacity excess integrates max(occupancy − capacity, 0) over each sector and time. It is not the total aircraft count on the screen.','',
        '- Runway release: next arrival outside 6 NM at roll start, full previous-arrival runway evacuation, and more than 30 seconds from wheel-off to next touchdown. Mixed arrival/departure pairs use 5 NM or 1,000 ft when both are within 40 NM and at or below 10,000 ft; Centre and other pair types retain 10/20 NM. These are common simulation assumptions for every method.','',
        '## Executed results','',
        'GA entries are mean ± sample standard deviation over all saved seeds. FCFS and reference are deterministic. Event delay uses fixed departure requested ready-events and uncontrolled arrival touchdown times from identical initial states. FCFS is the better native objective of 1-minute and 5-minute grids.','',
        '| Case | Method | Event delay (aircraft-min) | Sector excess (aircraft-min) | Cost (units) | Runway events in first 3h | Safe runs |',
        '|---|---|---:|---:|---:|---:|---:|']
    method_names=dict(zip(('NO_CONTROL','FCFS','TEAM_GROUND','TEAM_MIXED'),labels))
    for r in results:
        case='Nominal (20)' if r['study_role']=='nominal' else 'Overload (60)'
        for s in r['native_summary']:
            def fmt(k):return f"{s['mean_'+k]:.2f} ± {s['std_'+k]:.2f}"
            lines.append(f"| {case} | {method_names[s['method']]} | {fmt('total_delay_min')} | {fmt('sector_excess_aircraft_minutes')} | {fmt('converted_cost')} | {s['mean_completed_in_original_window']:.1f}/{r['case_counts']['total']} | {s['safe_runs']}/{s['runs']} |")
    lines+=['','![Executed comparison](comparison.png)','','## Interpretation','']
    for r in results:
        summary={s['method']:s for s in r['native_summary']}
        fcfs=summary['FCFS'];label='Nominal' if r['study_role']=='nominal' else 'Overload'
        for method in ('TEAM_GROUND','TEAM_MIXED'):
            ga=summary[method]
            delta=fcfs['mean_sector_excess_aircraft_minutes']-ga['mean_sector_excess_aircraft_minutes']
            delay=ga['mean_total_delay_min']-fcfs['mean_total_delay_min']
            lines.append(f"- {label}, {method_names[method]} versus FCFS: {delta:.2f} fewer sector-excess aircraft-minutes; {delay:+.2f} event-delay aircraft-minutes (GA minus FCFS).")
        lines.append(f"- {label} FCFS exhausted the 60-minute proposal domain for {r['runs']['FCFS']['search']['domain_exhaustions']} departures; native safety metering still applies. Best native replays: {r['best_methods']['TEAM_GROUND']}, {r['best_methods']['TEAM_MIXED']}.")
        mixed=[t['metrics'] for t in r['native_trials'] if t['method']=='TEAM_MIXED']
        lines.append(f"- {label} mixed GA executed {sum(m['speed_flights'] for m in mixed)} arrival speed controls across all saved seeds; {sum(m['native_withdrawn_speed_proposals'] for m in mixed)} proposed speed controls were withdrawn by native spacing checks.")
        diagnostics=[v['search'] for n,v in r['runs'].items() if n.startswith('TEAM_')]
        lines.append(f"- {label}: {sum(s.get('native_checks',0) for s in diagnostics)} native checkpoints across all GA runs; {sum(s.get('restarts',0) for s in diagnostics)} diversity restarts.")
        lines.append(f"- {label}: primary FCFS is {r['fcfs_selected_resolution']}, selected by the lower native objective of the one-minute and five-minute grids.")
        for method in ('TEAM_GROUND','TEAM_MIXED'):
            rows=[a for a in attribution if a['case_id']==r['case_id'] and a['method']==method]
            lines.append(f"- {label}, {method_names[method]}: {sum(a['improvement_after_initialization']>1e-6 for a in rows)}/{len(rows)} seeds improved after initialization; mean objective improvement {sum(a['improvement_after_initialization'] for a in rows)/len(rows):.2f}. This includes local search and native feedback; it does not isolate individual genetic operators.")
    previous_path=Path('output/ga_expansion/previous_results.json')
    previous=json.loads(previous_path.read_text(encoding='utf-8')) if previous_path.exists() else []
    same_inputs=previous and {r['case_id']:r['input_sha256'] for r in previous}=={r['case_id']:r['input_sha256'] for r in results}
    if same_inputs:
        before={r['case_id']:r for r in previous}
        lines+=['','## Before and after the GA expansion','',
            'Scenario input hashes are unchanged. The new FCFS also receives one-minute actions, whereas the previous benchmark used five-minute actions. The new GA receives separate native execution checkpoints. This compares complete configurations, not an isolated change to a single genetic operator.','',
            '| Case | Configuration | Method | Event delay (aircraft-min) | Sector excess (aircraft-min) |',
            '|---|---|---|---:|---:|']
        upgrade=[]
        for r in results:
            old=before[r['case_id']]
            assert old['input_sha256']==r['input_sha256'],'Before/after scenario inputs differ'
            for configuration,source in [('Previous',old),('Expanded',r)]:
                for s in source['native_summary']:
                    if s['method']=='NO_CONTROL':continue
                    lines.append(f"| {r['study_role']} | {configuration} | {method_names[s['method']]} | {s['mean_total_delay_min']:.2f} ± {s['std_total_delay_min']:.2f} | {s['mean_sector_excess_aircraft_minutes']:.2f} |")
                    upgrade.append(dict(case_id=r['case_id'],configuration=configuration,method=s['method'],
                        mean_delay_min=s['mean_total_delay_min'],std_delay_min=s['std_total_delay_min'],
                        mean_sector_excess_aircraft_minutes=s['mean_sector_excess_aircraft_minutes']))
        with Path('output/ga_expansion/before_after.csv').open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(upgrade[0]));writer.writeheader();writer.writerows(upgrade)
    lines+=['',
        'Nominal is a no-unnecessary-intervention check. In the revised overload design, arrivals alone are capacity-feasible; excess is created by the overlay with departures. Residual capacity excess must be reported even when separation and runway protection pass. A lower delay alone does not mean a better solution if capacity excess increases. Ten seeds and two constructed cases do not establish statistical significance or general operational superiority.','',
        'All executed trials have zero spatial separation, runway-protection and arrival-transfer violation pairs. The simulator retains at least 120-second takeoff separation, full landing-runway evacuation, a 6 NM cutoff at takeoff-roll start and 30 seconds from wheel-off to next touchdown, at most four active surface departures (one on the runway), and zero airborne holding circuits. Capacity feasibility is a separate outcome.','',
        '## Files and reproduction','',
        '- [Comparison CSV](comparison.csv): executed means and sample SD for each method.',
        '- [Every executed trial](all_native_trials.csv): individual seed metrics and repaired-control counts.',
        '- [Complete result snapshot](results_snapshot.json): settings, input hashes, search evidence, native trials and limitations.',
        '- Each immutable scenario run folder contains native_trials/<trial>/execution_flights.csv with proposed/executed controls, CTOT/TOBT/off-block and per-flight delay. The fcfs/, team_ground/ and team_mixed/ folders retain loadable best replays; best replay selection is by native objective, while the table uses all seeds.','',
        '```powershell',
        '.\\.venv\\Scripts\\python.exe -m pip install -r requirements-study.txt  # optional figures',
        '.\\.venv\\Scripts\\python.exe scripts/run_full_route_studies.py --seeds 11 22 33 44 55 66 77 88 99 110 --population 60 --generations 120 --max-evaluations 6000',
        '.\\.venv\\Scripts\\python.exe scripts/report_fcfs_ga_comparison.py',
        '```','',
        'Open /case-scenarios for the comparison. Load Reference, FCFS, GA ground or GA mixed directly from Scenario Builder or Supervisor. Plans are tied to scenario input hashes; changing the case requires a new run.',
        'A trajectory-table cache was reused for the development overload run where recorded in settings. Reproduction without the cache builds the same deterministic tables; reported elapsed time is not a controlled runtime benchmark.','']
    for r in results:lines.append(f"- {r['case_id']}: `{r['run_id']}`; evaluator `{r['version']}`; elapsed {r['elapsed_s']:.1f}s.")
    (out/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(out.resolve())


if __name__=='__main__':main()
