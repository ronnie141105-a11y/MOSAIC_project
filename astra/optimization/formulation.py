"""Chapter 3 categorical ATFM formulation, evaluated before admission/queueing.

Costs and flight paths are explicit research assumptions. Continuous separation
checks cover the synthetic TMA paths, not upstream or real operational routes.
"""
from copy import deepcopy
from itertools import product
import math
import random
import statistics
import time

import numpy as np

from . import atfm

VERSION = 'chapter3-categorical-v1'
OPTIONS = ((0, 0), (1, 5), (1, 10), (1, 15), (1, 20),
           (2, 5), (2, 10), (2, 15))
DEFAULT_SEEDS = tuple(11 * i for i in range(1, 11))
CASES = ('existing', 'nominal', 'holiday_peak')


def _number(value, name, minimum=0):
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
        raise ValueError(f'{name} must be finite and >= {minimum}')
    return value


def make_scenario(case='existing'):
    if case not in CASES:
        raise ValueError('Unknown synthetic case')
    s = atfm.scenario()
    s.update(name='VVTS_CHAPTER3_' + case.upper(), case=case,
             formulation_version=VERSION, capacity_interval_min=15,
             hourly_capacity=42, ground_levels_min=[5, 10, 15, 20],
             speed_levels_pct=[5, 10, 15], penalty_lambda=1000,
             penalty_power=1, cost_rates={'ground_per_min': 1, 'speed_per_min': 2},
             penalty_weights={'capacity': 1, 'occupancy': 1,
                              'separation': 1, 'new_conflict': 1},
             horizontal_min_nm=5, vertical_min_ft=1000,
             max_ground_delay_min=20, max_speed_reduction_pct=15)
    if case != 'existing':
        s.update(capacity_interval_min=60, entry_capacity_15min=None,
                 capacity_per_interval=[42, 42], tail_capacity=42,
                 occupancy_limit=None)
    else:
        s.update(capacity_per_interval=s['entry_capacity_15min'][:],
                 tail_capacity=s['tail_capacity_15min'])
    if case == 'holiday_peak':
        for f in s['flights']:
            lead = f['travel_to_entry_min']
            f['eta_min'] = round(f['eta_min'] * .55, 4)
            if f['ground_eligible']:
                f['reference_takeoff_min'] = f['eta_min'] - lead
            f['travel_to_entry_min'] = f['eta_min'] - f['reference_takeoff_min']
    s['note'] = ('Synthetic variations of the existing 54-arrival scenario. '
                 '42 flights/60 min is the user-confirmed study capacity, not '
                 'verified VVTS declared capacity. Costs and paths are assumed.')
    return s


def path_vertices(flight):
    """Explicit local east/north NM and altitude-ft vertices for replay/checks."""
    angle = {'G_N': 0, 'G_E': 90, 'G_W': 270}[flight['gate']]
    vertices = []
    for a, radius, altitude in ((angle, 40, 11000), (angle+75, 25, None),
                                 (angle+35, 15, None), (angle+50, 5, 2000)):
        rad = math.radians(a)
        vertices.append([radius*math.sin(rad), radius*math.cos(rad), altitude])
    lengths = [math.hypot(b[0]-a[0], b[1]-a[1]) for a, b in zip(vertices, vertices[1:])]
    distance = sum(lengths)
    offsets = [0]
    for length in lengths:
        offsets.append(offsets[-1]+flight['dwell_min']*length/distance)
    for vertex, offset in zip(vertices, offsets):
        vertex[2] = 11000 - 9000*offset/flight['dwell_min']
    return np.asarray(vertices), np.asarray(offsets)


def _conflict_table(a, b, delays_a, delays_b, horizontal, vertical):
    """Analytic CPA restricted to the interval satisfying vertical separation.

    All option pairs are broadcast at once. Checks each overlapping pair of
    linear legs; no sampling can miss a brief conflict between frames.
    """
    pa, ta = path_vertices(a)
    pb, tb = path_vertices(b)
    starts_a = a['eta_min'] + np.asarray(delays_a)[:, None]
    starts_b = b['eta_min'] + np.asarray(delays_b)[None, :]
    conflicts = np.zeros((len(delays_a), len(delays_b)), dtype=bool)
    for ia in range(3):
        va = (pa[ia+1]-pa[ia])/(ta[ia+1]-ta[ia])
        for ib in range(3):
            vb = (pb[ib+1]-pb[ib])/(tb[ib+1]-tb[ib])
            sa, sb = starts_a+ta[ia], starts_b+tb[ib]
            lo = np.maximum(sa, sb)
            hi = np.minimum(starts_a+ta[ia+1], starts_b+tb[ib+1])
            rel = (pa[ia]+(lo-sa)[..., None]*va - pb[ib]-(lo-sb)[..., None]*vb)
            v = va-vb
            lower = np.zeros_like(lo)
            upper = hi-lo
            if abs(v[2]) < 1e-12:
                vertical_ok = np.abs(rel[..., 2]) < vertical
            else:
                roots = ((-vertical-rel[..., 2])/v[2], (vertical-rel[..., 2])/v[2])
                lower = np.maximum(lower, np.minimum(*roots))
                upper = np.minimum(upper, np.maximum(*roots))
                vertical_ok = upper > lower + 1e-10
            speed2 = v[0]**2+v[1]**2
            closest = -(rel[..., 0]*v[0]+rel[..., 1]*v[1])/speed2 if speed2 > 1e-12 else lower
            closest = np.maximum(lower, np.minimum(upper, closest))
            distance2 = (rel[..., 0]+v[0]*closest)**2+(rel[..., 1]+v[1]*closest)**2
            conflicts |= (hi > lo+1e-10) & vertical_ok & (distance2 < horizontal**2-1e-10)
    return conflicts


class Evaluator:
    """Immutable input copy, per-flight domains, and precomputed path conflicts."""
    def __init__(self, scenario):
        self.s = deepcopy(scenario)
        s = self.s
        self.flights = s['flights']
        if not self.flights or len(self.flights) > 200:
            raise ValueError('Provide 1–200 flights')
        ids = [f['id'] for f in self.flights]
        if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('Flight IDs must be unique nonempty strings')
        for field in ('capacity_interval_min', 'hourly_capacity', 'tail_capacity'):
            if type(s[field]) is not int or s[field] < 1:
                raise ValueError(f'{field} must be a positive integer')
        if not s['capacity_per_interval'] or any(type(c) is not int or c < 1 for c in s['capacity_per_interval']):
            raise ValueError('Interval capacities must be positive integers')
        occupancy = s.get('occupancy_limit')
        if occupancy is not None and (type(occupancy) is not int or occupancy < 1):
            raise ValueError('Occupancy limit must be positive or null')
        for field in ('penalty_lambda', 'horizontal_min_nm', 'vertical_min_ft',
                      'upstream_segment_min', 'nominal_ground_speed_kt'):
            _number(s[field], field, 1e-12)
        for field in ('max_ground_delay_min', 'max_speed_reduction_pct'):
            _number(s[field], field)
        if s['max_speed_reduction_pct'] >= 100:
            raise ValueError('Speed reduction must be below 100 percent')
        if type(s['penalty_power']) is not int or s['penalty_power'] not in (1, 2):
            raise ValueError('Penalty power must be 1 or 2')
        for key in ('ground_per_min', 'speed_per_min'):
            _number(s['cost_rates'][key], key)
        for key in ('capacity', 'occupancy', 'separation', 'new_conflict'):
            _number(s['penalty_weights'][key], key)
        _number(s['decision_min'], 'Decision time', -float('inf'))
        if s.get('ground_levels_min') != [5, 10, 15, 20] or s.get('speed_levels_pct') != [5, 10, 15]:
            raise ValueError('This formulation uses GDP 5/10/15/20 min and speed 5/10/15 percent')
        self.n = len(self.flights)
        self.domains = []
        self.delays = np.zeros((self.n, len(OPTIONS)))
        self.costs = np.zeros_like(self.delays)
        override = s.get('cost_table', {})
        if not isinstance(override, dict) or any(k not in {f'{m}:{l}' for m, l in OPTIONS} for k in override):
            raise ValueError('Invalid cost table key; use m:l')
        if override.get('0:0', 0) != 0:
            raise ValueError('No-action cost must be zero')
        self.cost_table = []
        for i, f in enumerate(self.flights):
            for field in ('eta_min', 'reference_takeoff_min'):
                _number(f[field], field, -float('inf'))
            for field in ('travel_to_entry_min', 'dwell_min'):
                _number(f[field], field, 1e-12)
            if f['eta_min'] < 0 or type(f['ground_eligible']) is not bool:
                raise ValueError('Arrival ETA must be >= 0 and eligibility boolean')
            if f['ground_eligible'] != (f['reference_takeoff_min'] >= s['decision_min']):
                raise ValueError('Ground eligibility inconsistent with decision time')
            if not math.isclose(f['eta_min'], f['reference_takeoff_min']+f['travel_to_entry_min'], abs_tol=1e-6):
                raise ValueError('ETA inconsistent with departure and travel time')
            if f['gate'] not in ('G_N', 'G_E', 'G_W'):
                raise ValueError('Unknown synthetic gate')
            segment = _number(f.get('upstream_segment_min', s['upstream_segment_min']), 'Segment', 1e-12)
            speed = _number(f.get('nominal_ground_speed_kt', s['nominal_ground_speed_kt']), 'Speed', 1e-12)
            ground_max = _number(f.get('max_ground_delay_min', s['max_ground_delay_min']), 'GDP bound')
            speed_max = _number(f.get('max_speed_reduction_pct', s['max_speed_reduction_pct']), 'Speed bound')
            if speed_max >= 100:
                raise ValueError('Speed reduction must be below 100 percent')
            domain = []
            for j, (m, level) in enumerate(OPTIONS):
                delay = level if m == 1 else segment*level/(100-level) if m == 2 else 0
                allowed = m == 0 or (m == 1 and f['ground_eligible'] and level <= ground_max)
                allowed |= m == 2 and level <= speed_max and f['eta_min']-segment >= s['decision_min']
                if allowed:
                    domain.append(j)
                cost = delay*s['cost_rates']['ground_per_min' if m == 1 else 'speed_per_min'] if m else 0
                cost = _number(override.get(f'{m}:{level}', cost), 'Cost')
                self.delays[i, j], self.costs[i, j] = delay, cost
                self.cost_table.append(dict(flight_id=f['id'], m=m, level=level, delay_min=delay,
                                            converted_cost=cost, allowed=bool(allowed), nominal_speed_kt=speed))
            self.domains.append(tuple(domain))
        self.indices = np.arange(self.n)
        self.etas = np.asarray([f['eta_min'] for f in self.flights])
        self.dwell = np.asarray([f['dwell_min'] for f in self.flights])
        self.pair_i, self.pair_j = np.triu_indices(self.n, 1)
        self.pair_tables = np.asarray([
            _conflict_table(self.flights[i], self.flights[j], self.delays[i], self.delays[j],
                            s['horizontal_min_nm'], s['vertical_min_ft'])
            for i, j in zip(self.pair_i, self.pair_j)], dtype=bool).reshape(-1, 8, 8)
        self.baseline_pairs = self.pair_tables[:, 0, 0]

    def encode(self, plan, mode='mixed'):
        if mode not in ('mixed', 'ground') or not isinstance(plan, (list, tuple)) or len(plan) != self.n:
            raise ValueError('One [m, l] gene per flight is required')
        codes = []
        for i, gene in enumerate(plan):
            if not isinstance(gene, (list, tuple)) or len(gene) != 2 or any(type(x) is not int for x in gene):
                raise ValueError('Genes must be two integers [m, l]')
            try:
                code = OPTIONS.index(tuple(gene))
            except ValueError as exc:
                raise ValueError('Unknown measure or level') from exc
            if code not in self.domains[i] or (mode == 'ground' and gene[0] == 2):
                raise ValueError('Measure unavailable for this flight')
            codes.append(code)
        return codes

    def decode(self, codes):
        return [list(OPTIONS[c]) for c in codes]

    def _state(self, codes):
        delays = self.delays[self.indices, codes]
        entries = self.etas+delays
        exits = entries+self.dwell
        s = self.s
        bins, counts = np.unique(np.floor(entries/s['capacity_interval_min']).astype(int), return_counts=True)
        caps = s['capacity_per_interval']
        violations = [max(0, int(count)-(caps[b] if b < len(caps) else s['tail_capacity']))
                      for b, count in zip(bins, counts)]
        # Avoid double-counting when the interval resource already is 42/hour.
        _, hourly_counts = np.unique(np.floor(entries/60).astype(int), return_counts=True)
        hourly = [max(0, int(count)-s['hourly_capacity']) for count in hourly_counts]
        same = s['capacity_interval_min'] == 60 and all(c == s['hourly_capacity'] for c in caps) and s['tail_capacity'] == s['hourly_capacity']
        power = s['penalty_power']
        cap_penalty = sum(v**power for v in violations) + (0 if same else sum(v**power for v in hourly))
        times = np.concatenate((entries, exits))
        deltas = np.concatenate((np.ones(self.n, dtype=int), -np.ones(self.n, dtype=int)))
        unique_times, index = np.unique(times, return_inverse=True)
        occupancy = np.cumsum(np.bincount(index, weights=deltas))
        occupancy_excess = np.maximum(0, occupancy[:-1]-(s['occupancy_limit'] or self.n))
        # Occupancy penalty is integrated excess aircraft-minutes, independent of frame rate.
        occupancy_penalty = float(np.sum(occupancy_excess**power*np.diff(unique_times)))
        conflicts = self.pair_tables[np.arange(len(self.pair_i)), np.asarray(codes)[self.pair_i], np.asarray(codes)[self.pair_j]]
        new = conflicts & ~self.baseline_pairs
        weights = s['penalty_weights']
        penalty = (weights['capacity']*cap_penalty + weights['occupancy']*occupancy_penalty
                   + weights['separation']*int(conflicts.sum()) + weights['new_conflict']*int(new.sum()))
        cost = float(self.costs[self.indices, codes].sum())
        return dict(entries=entries, exits=exits, delays=delays, bins=bins, counts=counts,
                    violations=violations, hourly=hourly, cap_penalty=cap_penalty,
                    occupancy_penalty=occupancy_penalty, peak=int(max(occupancy, default=0)),
                    conflicts=conflicts, new=new, cost=cost, penalty=penalty,
                    objective=cost+s['penalty_lambda']*penalty)

    def objective(self, codes):
        return self._state(codes)['objective']

    def domain_diagnostics(self, mode='mixed'):
        """Necessary feasibility bounds, independent of whether GA succeeds.

        A positive bound proves infeasibility in this discrete action domain.
        A zero bound says nothing about global feasibility.
        """
        domains = [tuple(c for c in d if mode != 'ground' or c < 5) for d in self.domains]
        forced_pairs = []
        for k, (i, j) in enumerate(zip(self.pair_i, self.pair_j)):
            if self.pair_tables[k][np.ix_(domains[i], domains[j])].all():
                forced_pairs.append([self.flights[i]['id'], self.flights[j]['id']])
        def bound(interval, capacities, tail):
            possibilities = [set(np.floor((self.etas[i]+self.delays[i, list(d)])/interval).astype(int))
                             for i, d in enumerate(domains)]
            maximum = max(max(b) for b in possibilities)
            if maximum > 1000:
                raise ValueError('Scenario exceeds 1000 capacity bins')
            best = dict(excess_lower_bound=0)
            for start in range(maximum+1):
                for end in range(start, maximum+1):
                    forced = sum(min(b) >= start and max(b) <= end for b in possibilities)
                    capacity = sum(capacities[b] if b < len(capacities) else tail for b in range(start, end+1))
                    excess = int(max(0, forced-capacity))
                    if excess > best['excess_lower_bound']:
                        best = dict(excess_lower_bound=excess, interval_start_min=start*interval,
                                    interval_end_min=(end+1)*interval, forced_flights=int(forced), capacity=capacity)
            return best
        resource = bound(self.s['capacity_interval_min'], self.s['capacity_per_interval'], self.s['tail_capacity'])
        hourly = bound(60, [self.s['hourly_capacity']], self.s['hourly_capacity'])
        impossible = bool(forced_pairs or resource['excess_lower_bound'] or hourly['excess_lower_bound'])
        return dict(mode=mode, unavoidable_conflict_pairs=forced_pairs,
                    capacity_bound=resource, hourly_bound=hourly, proven_infeasible=impossible,
                    interpretation='Positive bound proves infeasibility within the listed discrete measures; zero does not prove feasibility')

    def evaluate(self, plan):
        codes = self.encode(plan)
        state = self._state(codes)
        rows = []
        for i, (f, code) in enumerate(zip(self.flights, codes)):
            m, level = OPTIONS[code]
            delay = float(state['delays'][i])
            speed = f.get('nominal_ground_speed_kt', self.s['nominal_ground_speed_kt'])
            vertices, offsets = path_vertices(f)
            rows.append(dict(**f, measure=m, level=level, level_unit='percent' if m == 2 else 'minutes',
                ground_delay_min=delay if m == 1 else 0, speed_delay_min=delay if m == 2 else 0,
                speed_reduction_pct=level if m == 2 else 0,
                upstream_ground_speed_kt=speed*(1-level/100) if m == 2 else speed,
                request_min=float(state['entries'][i]), entry_min=float(state['entries'][i]),
                exit_min=float(state['exits'][i]), airborne_delay_min=0,
                total_delay_min=delay, converted_cost=float(self.costs[i, code]),
                trajectory_local_nm_ft=vertices.tolist(), trajectory_offsets_min=offsets.tolist()))
        delays = sorted(state['delays'])
        pairs = lambda mask: [[self.flights[i]['id'], self.flights[j]['id']]
                              for i, j, selected in zip(self.pair_i, self.pair_j, mask) if selected]
        feasible = not (sum(state['violations']) or sum(state['hourly']) or
                        state['occupancy_penalty'] or state['conflicts'].any())
        metrics = dict(objective=state['objective'], fitness=1/(1+state['objective']),
            converted_cost=state['cost'], penalty=state['penalty'],
            capacity_penalty=state['cap_penalty'], occupancy_penalty=state['occupancy_penalty'],
            capacity_excess_flights=sum(state['violations']), hourly_excess_flights=sum(state['hourly']),
            separation_conflict_pairs=int(state['conflicts'].sum()), new_conflict_pairs=int(state['new'].sum()),
            feasible_in_synthetic_tma=bool(feasible), peak_occupancy=state['peak'],
            ground_delay_min=sum(r['ground_delay_min'] for r in rows),
            speed_delay_min=sum(r['speed_delay_min'] for r in rows), airborne_holding_min=0,
            total_delay_min=float(sum(delays)), max_delay_min=float(max(delays)),
            p95_delay_min=float(delays[math.ceil(.95*self.n)-1]), completed=self.n,
            final_exit_min=float(max(state['exits'])),
            no_action_flights=sum(c == 0 for c in codes), ground_flights=sum(1 <= c <= 4 for c in codes),
            speed_flights=sum(c >= 5 for c in codes))
        caps = self.s['capacity_per_interval']
        audit = dict(capacity_bins=[dict(bin=int(b), count=int(c),
                     capacity=caps[b] if b < len(caps) else self.s['tail_capacity'], excess=int(v))
                     for b, c, v in zip(state['bins'], state['counts'], state['violations'])],
                     conflict_pairs=pairs(state['conflicts']), new_conflict_pairs=pairs(state['new']),
                     separation_scope='Continuous piecewise-linear synthetic TMA paths only; upstream excluded')
        return metrics, rows, audit


def optimize(evaluator, mode='mixed', seed=11, population=60, generations=150,
             max_evaluations=6000, incumbent=None, stagnation=40):
    if mode not in ('ground', 'mixed') or type(seed) is not int:
        raise ValueError('Invalid mode or seed')
    for value, lo, hi, label in ((population, 4, 150, 'population'), (generations, 0, 300, 'generations'),
                                (max_evaluations, 1, 20000, 'evaluations'), (stagnation, 1, 100, 'stagnation')):
        if type(value) is not int or not lo <= value <= hi:
            raise ValueError(f'{label} must be an integer from {lo} to {hi}')
    start = time.perf_counter()
    rng = random.Random(seed)
    domains = [tuple(c for c in domain if mode != 'ground' or c < 5) for domain in evaluator.domains]
    cache = {}
    def score(codes):
        key = tuple(codes)
        if key not in cache:
            if len(cache) >= max_evaluations:
                return float('inf')
            cache[key] = evaluator.objective(codes)
        return cache[key]
    best = evaluator.encode(incumbent, mode) if incumbent is not None else [0]*evaluator.n
    score(best)
    zero = [0]*evaluator.n
    if score(zero) < score(best):
        best = zero
    # Count every heuristic evaluation against the same search allowance.
    greedy = best[:]
    for _ in range(2):
        improved = False
        for i in range(evaluator.n):
            local = greedy
            for c in domains[i]:
                candidate = greedy[:]
                candidate[i] = c
                if score(candidate) < score(local):
                    local = candidate
            improved |= local != greedy
            greedy = local
            if len(cache) >= max_evaluations:
                break
        if not improved or len(cache) >= max_evaluations:
            break
    if score(greedy) < score(best):
        best = greedy
    def mutate(codes, rate=.1):
        out = codes[:]
        for i, domain in enumerate(domains):
            if rng.random() >= rate:
                continue
            # Both mutation types: switch measure or change its level.
            m = OPTIONS[out[i]][0]
            same = [c for c in domain if OPTIONS[c][0] == m and c != out[i]]
            other = [c for c in domain if OPTIONS[c][0] != m]
            choices = (same if rng.random() < .5 else other) or list(domain)
            out[i] = rng.choice(choices)
        return out
    pop = [best[:], zero]+[mutate(best, .35) for _ in range(population-2)]
    history = []
    stale = 0
    previous = float('inf')
    stop = 'generations'
    for generation in range(generations+1):
        ranked = sorted(pop, key=score)
        if score(ranked[0]) < score(best):
            best = ranked[0][:]
        value = score(best)
        history.append(dict(generation=generation, objective=value, fitness=1/(1+value), evaluations=len(cache)))
        stale = stale+1 if value >= previous-1e-9 else 0
        previous = value
        if len(cache) >= max_evaluations:
            stop = 'evaluation_budget'
            break
        if value == 0:
            stop = 'zero_cost_feasible'
            break
        if stale >= stagnation:
            stop = 'stagnation'
            break
        if generation == generations:
            break
        elites = max(1, math.ceil(population*.1))
        nxt = [p[:] for p in ranked[:elites]]
        def parent():
            return min(rng.sample(ranked, 3), key=score)
        while len(nxt) < population:
            a, b = parent(), parent()
            cut = rng.randrange(1, evaluator.n) if evaluator.n > 1 else 1
            child = a[:cut]+b[cut:] if rng.random() < .8 else a[:]
            nxt.append(mutate(child))
        pop = nxt
    return evaluator.decode(best), history, dict(search_evaluations=len(cache), total_evaluations=len(cache),
        preparation_evaluations=0, total_budget=max_evaluations, search_elapsed_s=time.perf_counter()-start,
        total_elapsed_s=time.perf_counter()-start, stop_reason=stop, generations_completed=history[-1]['generation'])


def exact_optimize(evaluator, mode='mixed', limit=100000):
    domains = [tuple(c for c in d if mode != 'ground' or c < 5) for d in evaluator.domains]
    combinations = math.prod(map(len, domains))
    if combinations > limit:
        raise ValueError('Enumeration limit exceeded')
    best = min(product(*domains), key=evaluator.objective)
    return evaluator.decode(best), evaluator.objective(best), combinations


def summarize(runs):
    summary = []
    for prefix in ('GA_GROUND', 'GA_MIXED'):
        selected = [r for name, r in runs.items() if name.startswith(prefix+'_')]
        if not selected:
            continue
        row = dict(method=prefix, seeds=len(selected),
                   feasible_runs=sum(r['metrics']['feasible_in_synthetic_tma'] for r in selected))
        for key in ('objective', 'converted_cost', 'penalty', 'total_delay_min',
                    'capacity_excess_flights', 'hourly_excess_flights', 'separation_conflict_pairs', 'new_conflict_pairs'):
            values = [r['metrics'][key] for r in selected]
            row['mean_'+key] = statistics.mean(values)
            row['std_'+key] = statistics.stdev(values) if len(values) > 1 else 0
        summary.append(row)
    return summary


def experiment(case='existing', seeds=DEFAULT_SEEDS, population=60, generations=150,
               max_evaluations=6000, penalty_lambda=1000, penalty_power=1, scenario_input=None,
               validate_pipeline=True):
    start = time.perf_counter()
    seeds = tuple(seeds)
    if not seeds or len(set(seeds)) != len(seeds) or any(type(seed) is not int for seed in seeds):
        raise ValueError('Unique integer seeds required')
    if type(max_evaluations) is not int or not 2 <= max_evaluations <= 20000:
        raise ValueError('Total budget must be 2–20000')
    s = deepcopy(scenario_input) if scenario_input is not None else make_scenario(case)
    s.update(penalty_lambda=penalty_lambda, penalty_power=penalty_power)
    e = Evaluator(s)
    runs = {}
    def record(name, plan, history=None, search=None):
        metrics, flights, audit = e.evaluate(plan)
        runs[name] = dict(plan=plan, metrics=metrics, flights=flights, audit=audit,
                          history=history or [], search=search or {}, evaluations=(search or {}).get('search_evaluations', 0))
    record('NO_CONTROL', e.decode([0]*e.n))
    for seed in seeds:
        ground, _, prep = optimize(e, 'ground', seed, population, generations, max_evaluations//2)
        remaining = max_evaluations-prep['total_evaluations']
        for mode, label in (('ground', 'GA_GROUND'), ('mixed', 'GA_MIXED')):
            plan, history, search = optimize(e, mode, seed+1000, population, generations, remaining, ground)
            search.update(preparation_evaluations=prep['total_evaluations'],
                          total_evaluations=prep['total_evaluations']+search['search_evaluations'],
                          total_budget=max_evaluations,
                          total_elapsed_s=prep['search_elapsed_s']+search['search_elapsed_s'],
                          incumbent_plan=ground, refinement_seed=seed+1000)
            record(f'{label}_{seed}', plan, history, search)
    best_methods = {prefix: min((name for name in runs if name.startswith(prefix+'_')),
                               key=lambda name: runs[name]['metrics']['objective'])
                    for prefix in ('GA_GROUND', 'GA_MIXED')}
    validations = {}
    if validate_pipeline:
        from .formulation_validation import validate_runs
        validations = validate_runs(runs, ['NO_CONTROL', *best_methods.values()])
    sensitivity = [dict(method=name, penalty_lambda=value,
                        rescored_objective=r['metrics']['converted_cost']+value*r['metrics']['penalty'])
                   for value in (100, 1000, 10000) for name, r in runs.items()]
    return dict(scenario=e.s, formulation_version=VERSION, runs=runs, summary=summarize(runs),
                domain_diagnostics={mode: e.domain_diagnostics(mode) for mode in ('ground', 'mixed')},
                best_methods=best_methods, pipeline_validation=validations, cost_table=e.cost_table,
                stress=[], sensitivity=sensitivity, exact_checks=[],
                settings=dict(seeds=list(seeds), population=population, generations=generations,
                              max_evaluations=max_evaluations, crossover_probability=.8, mutation_probability=.1,
                              elitism_fraction=.1, tournament_k=3, stagnation_generations=40,
                              budget_basis='Unique objective evaluations including greedy preparation and shared ground incumbent',
                              optimizer_version=VERSION), elapsed_s=time.perf_counter()-start,
                limitations=[
                    'Synthetic traffic, paths and cost table; no FPL or calibrated real traffic optimization.',
                    'User confirmed 42 flights/60 min; this is a study parameter, not independently verified airport capacity.',
                    'P = weighted capacity excess + occupancy excess aircraft-minutes + conflict pairs + new conflict pairs.',
                    'New conflict pairs relative to uncontrolled TMA paths are a hotspot penalty proxy; DBSCAN/complexity checked after search.',
                    'Separation is analytic on synthetic TMA paths only; upstream control, wind, IAS/Mach and fuel are excluded.',
                    'No queue auto-repairs a plan. Positive residual violations remain visible and the solution is marked infeasible.',
                    'Pipeline validation is a diagnostic on the same assumed paths, not independent operational validation.',
                    'Section 2.4 and its five metrics were not supplied; reported KPIs are provisional.'])
