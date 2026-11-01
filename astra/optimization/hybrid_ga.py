"""Budgeted, sequence-aware GA with native execution feedback.

The fast archive drives exploration; a separate native incumbent chooses the
returned plan. Native checks have an explicit, separately reported budget.
"""
import math
import random
import time


VERSION='fixed-order-flow-ga-4'


def sequence_move(e,codes,rng):
    """Compatibility shim: sequence changes are no longer permitted."""
    return tuple(codes)


def optimize(e,mode,seed,population=60,generations=120,max_evaluations=6000,
             incumbent=None,native=None,native_budget=4,coarse_incumbent=None):
    if mode not in ('ground','mixed'):raise ValueError('Unknown hybrid mode')
    if type(seed) is not int:raise ValueError('Seed must be an integer')
    for value,lo,hi in ((population,4,150),(generations,1,300),(max_evaluations,1,20000),(native_budget,1,8)):
        if type(value) is not int or not lo<=value<=hi:raise ValueError('Invalid hybrid search budget')
    started=time.perf_counter();rng=random.Random(seed)
    domains=[tuple(c for c in d if mode=='mixed' or e.options[c][0] in (0,1)) for d in e.domains]
    active=[i for i,d in enumerate(domains) if len(d)>1]
    groups={}
    if mode=='mixed':
        for i,f in enumerate(e.metadata):
            if f['direction']=='arrival' and len(domains[i])>1:groups.setdefault(f['route_family'],[]).append(i)
    cache={};archive={};native_seen=set();native_history=[];native_best=None
    execution_samples=[];estimate_cache={}
    history=[];restarts=0;stale=0;last_best=math.inf;native_elapsed=0.0
    def score(codes):
        codes=tuple(codes)
        if codes not in cache:
            if len(cache)>=max_evaluations:return math.inf
            cache[codes]=float(e.objective(codes))
            archive[codes]=cache[codes]
        return cache[codes]
    def estimate(codes):
        """Local error correction, without relaxing any safety constraint.

        Optimistic extrapolation decays away from measured control vectors;
        each selected extrapolation still needs a complete native execution.
        """
        codes=tuple(codes);value=score(codes)
        key=(len(execution_samples),codes)
        if key not in estimate_cache:
            nearest=None
            for sample,correction in execution_samples:
                distance=sum((abs(e.options[a][1]-e.options[b][1])/5 if
                    e.metadata[i]['direction']=='departure' else (0 if a==b else 2))
                    for i,(a,b) in enumerate(zip(codes,sample)))
                if nearest is None or distance<nearest[0]:nearest=(distance,correction)
            # Preserve the common measured offset (for example the 20 s
            # occupancy-grid error). Only the local residual decays; otherwise
            # distant, untested plans would look artificially free of it.
            floor=min((correction for _,correction in execution_samples),default=0)
            bias=floor+(nearest[1]-floor)*math.exp(-nearest[0]/4) if nearest else 0
            estimate_cache[key]=value+bias
        return estimate_cache[key]
    def local(codes):
        best=tuple(codes);value=estimate(best)
        indices=active[:];rng.shuffle(indices)
        for i in indices:
            code=best[i];measure,level=e.options[code]
            trial_codes={0}
            if measure in (4,5):
                trial_codes.update(c for c in domains[i] if e.options[c][0]==measure and abs(e.options[c][1]-level)<=(5 if measure==4 else 40))
            elif measure==1 or e.metadata[i]['direction']=='departure':
                if (1,0) in e.options:
                    ready=e.options.index((1,0))
                    if ready in domains[i]:trial_codes.add(ready)
                step=e.s.get('ground_action_step_min',1)
                for delta in (-2*step,-step,step,2*step):
                    gene=(1,level+delta)
                    if gene in e.options:
                        c=e.options.index(gene)
                        if c in domains[i]:trial_codes.add(c)
            else:
                trial_codes.update(c for c in domains[i] if e.options[c][0]==2 and abs(e.options[c][1]-level)<=3)
            if getattr(e,'flow',False):
                trial_codes.update(c for c in domains[i] if e.options[c] in ((4,-1),(4,1),(4,2),(1,5),(5,180),(5,220),(5,260)))
            for c in sorted(trial_codes):
                candidate=list(best);candidate[i]=c;candidate=tuple(candidate)
                v=estimate(candidate)
                if v<value:best,value=candidate,v
                if len(cache)>=max_evaluations:return best
        return best
    def mutate(codes,wide=False):
        child=list(codes)
        if not active:return tuple(child)
        if groups and rng.random()<.3:
            group=rng.choice(list(groups.values()))
            level=rng.choice([0,*e.s['speed_levels_pct']])
            shared_gene=(2,level) if level else (0,0)
            if getattr(e,'flow',False) and mode=='mixed' and rng.random()<.5:
                shared_gene=(4,rng.choice([-2,-1,1,2,3,5,8]))
            for i in group:
                code=e.options.index(shared_gene)
                if code in domains[i]:child[i]=code
            return tuple(child)
        count=rng.randint(1,min(len(active),5 if wide else 2))
        for i in rng.sample(active,count):
            measure,level=e.options[child[i]]
            if e.metadata[i]['direction']=='departure' and not wide and rng.random()<.8:
                target=max(0,level+rng.choice([-5,-2,-1,1,2,5]))
                child[i]=min(domains[i],key=lambda c:(abs(e.options[c][1]-target),e.events[i,c],e.options[c][0]!=1))
            else:child[i]=rng.choice(domains[i])
        return tuple(child)
    def checkpoint(generation,force=False):
        nonlocal native_best,native_elapsed
        if native is None or len(native_history)>=native_budget:return
        candidates=sorted(archive,key=lambda c:(estimate(c),c))
        candidate=next((c for c in candidates if c not in native_seen),None)
        if candidate is None:return
        native_seen.add(candidate);start=time.perf_counter()
        result=native(e.decode(candidate),generation)
        native_elapsed+=time.perf_counter()-start
        value=result['metrics']['objective']
        execution_samples.append((candidate,max(0,value-archive[candidate])))
        if native_best is None or value<native_best[0]:native_best=(value,candidate,result)
        native_history.append(dict(generation=generation,candidate_objective=value,
            best_objective=native_best[0],withdrawn_speed_proposals=result['metrics'].get('native_withdrawn_speed_proposals',0),
            projected_objective=archive[candidate]))
        # Repaired speed controls become a legal seed for the following search.
        repaired=result.get('executed_plan')
        if repaired is not None:
            repaired=tuple(e.encode(repaired,mode));score(repaired)
    base=tuple(e.encode(incumbent or [[0,0]]*e.n,mode));zero=(0,)*e.n
    score(base);score(zero);base=local(base)
    coarse=tuple(e.encode(coarse_incumbent,mode)) if coarse_incumbent is not None else None
    if coarse is not None:score(coarse)
    # FCFS remains a measured fallback for every seed, including mixed runs.
    if native is not None:
        start=time.perf_counter()
        result=native(e.decode(tuple(e.encode(incumbent or [[0,0]]*e.n,mode))),-1)
        native_elapsed+=time.perf_counter()-start
        candidate=tuple(e.encode(incumbent or [[0,0]]*e.n,mode));native_seen.add(candidate)
        native_best=(result['metrics']['objective'],candidate,result)
        execution_samples.append((candidate,max(0,native_best[0]-score(candidate))))
        native_history.append(dict(generation=-1,candidate_objective=native_best[0],best_objective=native_best[0],
            projected_objective=score(candidate),withdrawn_speed_proposals=result['metrics'].get('native_withdrawn_speed_proposals',0)))
    if coarse is not None and coarse not in native_seen and native is not None and native_budget>1:
        start=time.perf_counter()
        result=native(e.decode(coarse),-1);native_seen.add(coarse)
        native_elapsed+=time.perf_counter()-start
        value=result['metrics']['objective'];execution_samples.append((coarse,max(0,value-score(coarse))))
        if value<native_best[0]:native_best=(value,coarse,result)
        native_history.append(dict(generation=-1,candidate_objective=value,best_objective=native_best[0],
            projected_objective=score(coarse),withdrawn_speed_proposals=result['metrics'].get('native_withdrawn_speed_proposals',0)))
    base=local(min(archive,key=lambda c:(estimate(c),c)))
    pop=[base,zero]
    pop.extend(mutate(base,wide=i%3==0) for i in range(population-2))
    mid_count=max(0,min(2,native_budget-len(native_history)-1))
    midpoints={max(1,round(generations*i/(mid_count+1))) for i in range(1,mid_count+1)}
    stop='generations'
    for generation in range(generations+1):
        for c in pop:score(c)
        ranked=sorted(archive,key=lambda c:(estimate(c),c));best=ranked[0]
        if generation%10==0 and score(best)>0:local(best);ranked=sorted(archive,key=lambda c:(estimate(c),c));best=ranked[0]
        value=min(archive.values())
        history.append(dict(generation=generation,objective=value,fitness=1/(1+value),evaluations=len(cache)))
        stale=stale+1 if value>=last_best-1e-9 else 0;last_best=value
        if native is not None and generation in midpoints:
            checkpoint(generation)
            ranked=sorted(archive,key=lambda c:(estimate(c),c));best=ranked[0]
        if value==0:stop='zero_cost_feasible';break
        if len(cache)>=max_evaluations:stop='evaluation_budget';break
        if generation==generations:break
        elite=ranked[:max(2,population//10)]
        if stale>=10:
            restarts+=1;stale=0
            pop=elite+[mutate(rng.choice(elite),wide=True) for _ in range(population-len(elite))]
            continue
        parents=ranked[:population]
        def tournament():return min(rng.sample(parents,min(3,len(parents))),key=estimate)
        pop=elite[:];seen=set(pop);attempts=0
        while len(pop)<population and attempts<population*15:
            attempts+=1;a,b=tournament(),tournament()
            child=list(a)
            # Route cohorts stay together during crossover, so a coordinated
            # arrival slowdown is not split into incompatible neighbours.
            for indices in groups.values():
                if rng.random()<.5:
                    for i in indices:child[i]=b[i]
            for i,f in enumerate(e.metadata):
                if f['direction']=='departure' and rng.random()<.5:child[i]=b[i]
            candidate=mutate(child,wide=attempts>population*5)
            if candidate not in seen:pop.append(candidate);seen.add(candidate)
        pop.extend([best]*(population-len(pop)))
    checkpoint(history[-1]['generation'],force=True)
    projected=min(archive,key=lambda c:(archive[c],c))
    selected=native_best[1] if native_best is not None else projected
    diagnostics=dict(optimizer_version=VERSION,search_evaluations=len(cache),total_evaluations=len(cache),
        preparation_evaluations=0,total_budget=max_evaluations,stop_reason=stop,
        generations_completed=history[-1]['generation'],restarts=restarts,
        projected_incumbent_objective=archive[projected],projected_incumbent_plan=e.decode(projected),
        native_history=native_history,native_checks=len(native_history),native_check_budget=native_budget,
        execution_error_samples=len(execution_samples),coarse_warm_start=coarse is not None,
        selection_basis='native_execution' if native else 'search_projection',
        search_elapsed_s=time.perf_counter()-started-native_elapsed,total_elapsed_s=time.perf_counter()-started)
    return e.decode(selected),history,diagnostics
