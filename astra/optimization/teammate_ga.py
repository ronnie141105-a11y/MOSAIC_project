"""MOSAIC adaptation of the teammate's atfm_genetic_algorithm_model.py.

Retains (measure, level) genes, tournament selection, one-point crossover,
categorical mutation, 10% elitism and reciprocal fitness. The supplied evaluator
owns the physical model, costs, legal actions and ALL constraint checks.
See docs/Teammate_GA_review.md for provenance and changes.
"""
from dataclasses import dataclass, replace
import math
import random
import time

from .formulation import OPTIONS

VERSION = 'teammate-ga-1'


@dataclass
class Individual:
    chromosome: list
    objective: float = math.inf

    @property
    def fitness(self):
        return 1 / (1 + self.objective)

    def clone(self):
        # Preserve evaluation as well as genes; genes are immutable tuples.
        return replace(self, chromosome=self.chromosome[:])


def tournament_selection(population, rng, k=3):
    return max(rng.sample(population, min(k, len(population))), key=lambda p: p.fitness)


def crossover(parent1, parent2, rng, rate=.8):
    if len(parent1.chromosome) != len(parent2.chromosome):
        raise ValueError('Parents must have the same chromosome length')
    a, b = parent1.chromosome, parent2.chromosome
    if len(a) < 2 or rng.random() >= rate:
        return parent1.clone(), parent2.clone()
    cut = rng.randrange(1, len(a))
    return Individual(a[:cut]+b[cut:]), Individual(b[:cut]+a[cut:])


def _random_gene(domain, rng):
    # As in the original: choose a measure, then one of its legal levels.
    measures = sorted({gene[0] for gene in domain})
    measure = rng.choice(measures)
    return rng.choice([gene for gene in domain if gene[0] == measure])


def mutate(individual, domains, rng, rate=.1):
    genes = [(_random_gene(domain, rng) if rng.random() < rate else gene)
             for gene, domain in zip(individual.chromosome, domains)]
    return Individual(genes)


class _Search:
    def __init__(self, evaluator, mode, max_evaluations):
        if mode not in ('ground', 'mixed'):
            raise ValueError('mode must be ground or mixed')
        if type(max_evaluations) is not int or not 1 <= max_evaluations <= 20000:
            raise ValueError('max_evaluations must be an integer from 1 to 20000')
        self.evaluator, self.mode, self.limit = evaluator, mode, max_evaluations
        options = getattr(evaluator, 'options', OPTIONS)
        self.domains = [tuple(options[c] for c in d if mode != 'ground' or options[c][0] != 2)
                        for d in evaluator.domains]
        if len(self.domains) != evaluator.n or any(not d or (0, 0) not in d for d in self.domains):
            raise ValueError('Each flight needs a nonempty action domain including no action')
        self.cache = {}
        self.best = None

    def score(self, individual):
        # encode rejects omitted flights, invalid levels and ineligible GDP.
        codes = tuple(self.evaluator.encode(individual.chromosome, self.mode))
        if codes not in self.cache:
            if len(self.cache) >= self.limit:
                individual.objective = math.inf
                return individual.objective
            value = float(self.evaluator.objective(list(codes)))
            if not math.isfinite(value) or value < 0:
                raise ValueError('Evaluator must return a finite, nonnegative objective')
            self.cache[codes] = value
        individual.objective = self.cache[codes]
        # Archive immediately: even the last child before a budget stop counts.
        if self.best is None or individual.objective < self.best.objective:
            self.best = individual.clone()
        return individual.objective

    def greedy(self, incumbent):
        current = incumbent.clone()
        self.score(current)
        for _ in range(2):
            improved = False
            for i, domain in enumerate(self.domains):
                local = current
                for gene in domain:
                    child = Individual(current.chromosome[:])
                    child.chromosome[i] = gene
                    if self.score(child) < local.objective:
                        local = child
                improved |= local.objective < current.objective
                current = local
                if len(self.cache) >= self.limit:
                    return self.best.clone()
            if not improved:
                break
        return self.best.clone()


def greedy_plan(evaluator, mode='mixed', max_evaluations=6000, incumbent=None):
    """Two deterministic coordinate passes; no GA operators or random samples."""
    start = time.perf_counter()
    search = _Search(evaluator, mode, max_evaluations)
    initial = Individual([tuple(g) for g in incumbent] if incumbent is not None else [(0, 0)]*evaluator.n)
    search.greedy(initial)
    return [list(g) for g in search.best.chromosome], dict(
        total_evaluations=len(search.cache), total_elapsed_s=time.perf_counter()-start,
        stop_reason='evaluation_budget' if len(search.cache) >= max_evaluations else 'two_coordinate_passes')


def optimize(evaluator, mode='mixed', seed=11, population=80, generations=150,
             max_evaluations=6000, incumbent=None, stagnation=30):
    """Return (plan, convergence, diagnostics), compatible with MOSAIC evaluators.

    Baseline and two greedy passes seed the GA; half the remaining population
    explores all legal actions and half mutates the incumbent. Every UNIQUE
    objective call, including initialization and greedy passes, uses the budget.
    The objective/penalty weights are supplied by the evaluator, never relaxed.
    """
    if type(seed) is not int:
        raise ValueError('seed must be an integer')
    for value, lo, hi, name in ((population, 4, 150, 'population'),
                               (generations, 0, 300, 'generations'),
                               (stagnation, 1, 100, 'stagnation')):
        if type(value) is not int or not lo <= value <= hi:
            raise ValueError(f'{name} must be an integer from {lo} to {hi}')
    start = time.perf_counter()
    rng = random.Random(seed)
    search = _Search(evaluator, mode, max_evaluations)
    zero = Individual([(0, 0)]*evaluator.n)
    initial = Individual([tuple(g) for g in incumbent]) if incumbent is not None else zero.clone()
    search.score(initial)
    search.score(zero)
    search.greedy(search.best)
    pop = [search.best.clone(), zero.clone()]
    while len(pop) < population:
        if len(pop) % 2:
            pop.append(Individual([_random_gene(d, rng) for d in search.domains]))
        else:
            pop.append(mutate(search.best, search.domains, rng, rate=.35))
    history, previous, stale, stop = [], math.inf, 0, 'generations'
    for generation in range(generations+1):
        for individual in pop:
            search.score(individual)
        pop.sort(key=lambda p: p.objective)
        best = search.best
        history.append(dict(generation=generation, objective=best.objective,
                            fitness=best.fitness, evaluations=len(search.cache)))
        stale = stale+1 if best.objective >= previous-1e-9 else 0
        previous = best.objective
        if best.objective == 0:
            stop = 'zero_cost_feasible'
            break
        if len(search.cache) >= max_evaluations:
            stop = 'evaluation_budget'
            break
        if stale >= stagnation:
            stop = 'stagnation'
            break
        if generation == generations:
            break
        nxt = [p.clone() for p in pop[:max(1, math.ceil(population*.1))]]
        # Include the archive if an improving child occurred at a budget edge.
        nxt[0] = best.clone()
        while len(nxt) < population:
            parents = [tournament_selection(pop, rng) for _ in range(2)]
            for child in crossover(*parents, rng):
                nxt.append(mutate(child, search.domains, rng))
                if len(nxt) == population:
                    break
        pop = nxt
    elapsed = time.perf_counter()-start
    return [list(g) for g in search.best.chromosome], history, dict(
        optimizer_version=VERSION, search_evaluations=len(search.cache),
        total_evaluations=len(search.cache), preparation_evaluations=0,
        total_budget=max_evaluations, search_elapsed_s=elapsed, total_elapsed_s=elapsed,
        stop_reason=stop, generations_completed=history[-1]['generation'])
