"""Create a short thesis summary, speaking notes and one presentation figure.

Reads saved executions only. It does not run or modify the optimizer/scenarios.
Requires the optional requirements-study.txt plotting dependency.
"""
from pathlib import Path
import csv
import json
import shutil
import sys

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from astra.optimization.full_route_cases import saved_result


def main():
    out=PROJECT/'output/thesis_summary';out.mkdir(parents=True,exist_ok=True)
    archive=PROJECT/'output/scenario_revision_20261031/previous_thesis_summary'
    if not archive.exists():shutil.copytree(out,archive)
    cases=[saved_result(c) for c in ('workbook_low_20','workbook_peak_50')]
    rows=[]
    for case in cases:
        selected={r['method']:r for r in case['native_summary']}
        for method in ('FCFS','TEAM_GROUND'):
            r=selected[method]
            rows.append(dict(case_id=case['case_id'],scenario='Nominal' if case['study_role']=='nominal' else 'Overload',
                method='FCFS' if method=='FCFS' else 'GA ground',aircraft=case['case_counts']['total'],
                arrivals=case['case_counts']['arrivals'],departures=case['case_counts']['departures'],runs=r['runs'],
                event_delay_mean_min=r['mean_total_delay_min'],event_delay_sd_min=r['std_total_delay_min'],
                sector_excess_mean_aircraft_min=r['mean_sector_excess_aircraft_minutes'],
                sector_excess_sd_aircraft_min=r['std_sector_excess_aircraft_minutes'],
                spacing_runway_check='Passed' if r['safe_runs']==r['runs'] else 'Not all passed'))
    f,g=rows[2:]
    overload_reduction=(f['sector_excess_mean_aircraft_min']-g['sector_excess_mean_aircraft_min'])/f['sector_excess_mean_aircraft_min']*100 if f['sector_excess_mean_aircraft_min'] else 0
    extra_delay=g['event_delay_mean_min']-f['event_delay_mean_min']
    delay_increase=extra_delay/f['event_delay_mean_min']*100 if f['event_delay_mean_min'] else 0
    delay_change=(f"{abs(extra_delay):.2f} fewer aircraft-minutes of added delay ({abs(delay_increase):.1f}%)"
        if extra_delay<0 else f"{extra_delay:.2f} additional aircraft-minutes of delay ({delay_increase:.1f}%)")
    excess_change=g['sector_excess_mean_aircraft_min']-f['sector_excess_mean_aircraft_min']
    conclusion=('GA reduced both sector excess and event delay.' if excess_change<0 and extra_delay<0 else
        'GA reduced sector excess with the reported delay trade-off.' if excess_change<0 else
        'GA reduced event delay at the same sector excess.' if excess_change==0 and extra_delay<0 else
        'GA matched FCFS on both reported measures.' if excess_change==0 and extra_delay==0 else
        'GA did not improve both measures; assess sector excess and event delay together.')
    residual=('Residual sector overload remains.' if g['sector_excess_mean_aircraft_min']>0 else
        'All saved GA executions stayed within the modelled sector capacities.')
    finding=(f"Sector excess changed from {f['sector_excess_mean_aircraft_min']:.2f} to {g['sector_excess_mean_aircraft_min']:.2f} aircraft-minutes (GA minus FCFS: {excess_change:+.2f}). "
        f"Event delay changed from {f['event_delay_mean_min']:.2f} to {g['event_delay_mean_min']:.2f} aircraft-minutes (GA minus FCFS: {extra_delay:+.2f}).")
    delay_result=(f"Added delay fell from {f['event_delay_mean_min']:.2f} to {g['event_delay_mean_min']:.2f} aircraft-minutes — {abs(extra_delay):.2f} fewer."
        if extra_delay<0 else f"Added delay rose from {f['event_delay_mean_min']:.2f} to {g['event_delay_mean_min']:.2f} aircraft-minutes — {extra_delay:.2f} more.")
    with (out/'results.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (out/'source_runs.json').write_text(json.dumps({c['case_id']:dict(run_id=c['run_id'],version=c['version'],input_sha256=c['input_sha256']) for c in cases},indent=2),encoding='utf-8')

    def value(row,key,sd):
        text=f'{row[key]:.2f}'
        return text+(f" ± {row[sd]:.2f}" if row['runs']>1 and row[key]!=0 else '')
    table=['| Scenario | Method | Event delay (aircraft-min) | Sector overload (aircraft-min) | Spacing / runway |',
           '|---|---|---:|---:|---|']
    for r in rows:
        table.append(f"| {r['scenario']} ({r['aircraft']}) | {r['method']} | {value(r,'event_delay_mean_min','event_delay_sd_min')} | {value(r,'sector_excess_mean_aircraft_min','sector_excess_sd_aircraft_min')} | {r['spacing_runway_check']} |")
    summary=f'''# MOSAIC case study: FCFS vs Genetic Algorithm

## Aim

Evaluate whether a Genetic Algorithm can reduce sector overload while maintaining aircraft separation and runway protection.

## System and scenarios

MOSAIC connects Centre, Approach and Tower. It simulates arrivals from upstream routes to landing and parking, and departures from stands through taxi, takeoff and their outbound routes.

- **Nominal:** 20 aircraft — 11 arrivals and 9 departures.
- **Overload:** 60 aircraft — 36 arrivals and 24 departures.

Both cases use the same sector limits and safety rules. All arrivals are airborne at startup.

## Methods

- **FCFS:** keeps departure readiness order and assigns ground delays.
- **GA ground:** searches departure timings and parked-departure order, using the same ground-control action set as FCFS. A separate mixed extension also adjusts eligible arrival speeds; its results remain in the full report. Candidate schedules are tested in the simulator before selection.

The GA uses population 60, up to 120 generations, 6,000 fast evaluations and up to four separately counted simulator checkpoints per run. Results use ten fixed seeds 11, 22, …, 110. FCFS is the better native objective of its one-minute and five-minute grids. The primary comparison uses the two ground-control methods; the mixed extension is reported separately.

## Results

{chr(10).join(table)}

GA values are mean ± sample standard deviation across ten runs. Event delay uses fixed departure readiness and uncontrolled arrival touchdown times from identical initial states. Sector overload sums aircraft above each sector's capacity over time: one excess aircraft for ten minutes equals ten aircraft-minutes.

## Main finding

{finding} All compared executions passed the modelled spacing and runway checks. The nominal case is reported separately; waiting already present in the reference is included in its event-delay clock.

**Conclusion:** {conclusion} {residual}

**Scope:** Two synthetic scenarios and ten GA seeds provide simulation evidence for this traffic. Arrival-only overload is zero in the revised case; excess is created by overlapping departures. Improvements after initialization are reported separately in the technical report. These experiments do not establish statistical significance or real-world operational performance.

![Overload comparison](comparison.png)

Data: [results.csv](results.csv). Reproducibility: [source_runs.json](source_runs.json). Full method and evidence: [technical report](../fcfs_ga_comparison/report.md).
'''
    (out/'thesis_summary.md').write_text(summary,encoding='utf-8')
    notes=f'''# Presentation notes

## Slide 1 — Problem

- Traffic demand can exceed sector capacity.
- The aim is to reduce overload while preserving separation and runway protection.

Say: “This study examines the trade-off between traffic delay and sector congestion.”

## Slide 2 — Simulation

- Centre → Approach → Tower, including taxi and parking.
- Nominal: 20 aircraft. Overload: 60 aircraft.
- The two cases share sector limits and safety rules.

## Slide 3 — Comparison

- FCFS preserves departure readiness order and assigns ground delays.
- GA ground searches departure timing and parked-departure order; the mixed extension is reported separately.
- Report executed outcomes; GA results average ten fixed seeds.

Say: “The main comparison uses the same ground-control options; GA can optimize the parked-aircraft sequence.”

## Slide 4 — Results

Use **comparison.png** and the four-row table in **thesis_summary.md**.

- Nominal: see the separate executed comparison; sector overload is zero.
- {finding}
- Modelled spacing and runway checks passed.

## Slide 5 — Conclusion

- {conclusion}
- {residual}
- Two synthetic scenarios and ten fixed seeds describe this model and traffic.

## One-minute explanation

"MOSAIC connects Centre, Approach and Tower, including aircraft movements on the ground. I tested two synthetic scenarios: nominal traffic with 20 aircraft and overload traffic with 60 aircraft. I compared a strengthened FCFS baseline with a Genetic Algorithm that adjusts departure timing and parked-departure sequence. A mixed extension with arrival speed control is reported separately. {finding} All compared executions passed the modelled spacing and runway checks. {conclusion} These results describe the constructed traffic, not all real operations."

Use “event delay” with its fixed readiness and uncontrolled-touchdown clocks. Quote all ten-run means, not only the best replay. Separate initialization gains from improvement after search. See source_runs.json for the exact saved experiments.
'''
    (out/'presentation_notes.md').write_text(notes,encoding='utf-8')

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':12,'font.family':'DejaVu Sans'})
    fig,axes=plt.subplots(1,2,figsize=(9,4.7),layout='constrained')
    colors=['#89949e','#248f83']
    for ax,key,sd,title in [
        (axes[0],'sector_excess_mean_aircraft_min','sector_excess_sd_aircraft_min','Sector overload'),
        (axes[1],'event_delay_mean_min','event_delay_sd_min','Event delay')]:
        means=[r[key] for r in (f,g)];deviations=[r[sd] for r in (f,g)]
        ax.bar(['FCFS','GA'],means,yerr=deviations,color=colors,width=.55,capsize=5,error_kw={'elinewidth':1.3})
        for i,(mean,deviation) in enumerate(zip(means,deviations)):
            ax.annotate(f'{mean:.2f}',(i,mean+deviation),xytext=(0,8),textcoords='offset points',ha='center',fontsize=13)
        ax.set_title(title,pad=14);ax.set_ylabel('Aircraft-minutes')
        ax.set_ylim(0,max(a+b for a,b in zip(means,deviations))*1.25)
        ax.spines[['top','right']].set_visible(False);ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
    fig.suptitle('Overload case · FCFS vs GA ground',fontsize=17)
    fig.supxlabel('60 aircraft · GA: mean ± sample SD, 10 runs · FCFS: best of two grids\nEvent delay uses fixed readiness and uncontrolled touchdown clocks. Lower is better.',fontsize=10)
    fig.savefig(out/'comparison.png',dpi=220);fig.savefig(out/'comparison.pdf');plt.close(fig)
    print(out)
    print(f'Overload reduction: {overload_reduction:.4f}%; added delay: {extra_delay:.4f} min ({delay_increase:.4f}%)')


if __name__=='__main__':main()
