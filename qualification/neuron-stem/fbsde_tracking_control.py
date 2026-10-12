"""Finite NDU verification on LEARNED swap beliefs, not a language certificate.

An event is a categorical distribution over unordered actor pairs. Independent
errors across events are a declared modelling approximation, NOT established
because a common gate was trained. Exact source operations are unavailable to
this planner; a separate callback reveals only the requested event after choice.
"""
from functools import lru_cache
from itertools import combinations
import math
import time

from four_gate_common import digest, require

TEMPERATURES = (.25, .5, 1., 2., 4.)
ARMS = ('greedy_no_checks', 'posterior_no_checks', 'confidence_verify',
        'myopic_verify', 'ndu_two_step', 'verify_all', 'exact_reverse')


def pair_law(scores, temperature):
    require(type(scores) is list and 3 <= len(scores) <= 7 and
            all(type(x) in (float, int) and math.isfinite(x) for x in scores),
            'finite participant logits')
    require(type(temperature) in (int, float) and math.isfinite(temperature) and
            .25 <= temperature <= 4., 'temperature domain')
    pairs = tuple(combinations(range(len(scores)), 2))
    logits = [(scores[a]+scores[b])/temperature for a, b in pairs]
    require(all(math.isfinite(x) for x in logits), 'pair logit overflow')
    maximum = max(logits)
    weights = [math.exp(x-maximum) for x in logits]
    return pairs, tuple(x/math.fsum(weights) for x in weights)


def fit_temperature(rows):
    """Simulator-only held-out operation scoring; not a coverage/risk guarantee."""
    require(type(rows) is list and 1 <= len(rows) <= 4096, 'calibration inventory')
    losses = []
    for temperature in TEMPERATURES:
        total = 0.
        for row in rows:
            require(set(row) == {'scores', 'pair'}, 'calibration fields')
            pairs, probabilities = pair_law(row['scores'], temperature)
            target = tuple(sorted(row['pair']))
            require(target in pairs, 'calibration pair')
            logits = [(row['scores'][a]+row['scores'][b])/temperature for a,b in pairs]
            peak = max(range(len(logits)), key=lambda i: logits[i])
            # Preserve tiny positive NLL instead of rounding a near-one p to 1.
            total += logits[peak]-logits[pairs.index(target)]+math.log1p(
                math.fsum(math.exp(x-logits[peak]) for i,x in enumerate(logits) if i != peak))
        losses.append({'temperature': temperature, 'mean_nll': total/len(rows)})
    chosen = min(losses, key=lambda r: (r['mean_nll'], r['temperature']))
    return {'selected': chosen['temperature'], 'losses': losses,
            'rows': len(rows), 'input_sha256': digest(rows), 'risk_certified': False}


class BeliefProblem:
    """Bounded immutable information model; contains no raw events or true pairs."""
    def __init__(self, actors, query, laws, binding):
        require(type(actors) is int and 3 <= actors <= 7 and type(query) is int and
                0 <= query < actors, 'actor/query domain')
        pairs = tuple(combinations(range(actors), 2))
        require(type(laws) in (list, tuple) and 1 <= len(laws) <= 16,
                'bounded event count')
        for row in laws:
            require(type(row) in (list, tuple) and len(row) == len(pairs) and
                    all(type(x) in (float, int) and math.isfinite(x) and 0 <= x <= 1 for x in row)
                    and abs(math.fsum(row)-1) < 1e-12, 'categorical event law')
        require(type(binding) is dict and set(binding) == {'source', 'model', 'calibration', 'scope', 'generation'}
                and all(type(binding[k]) is str and binding[k] for k in ('source','model','calibration','scope'))
                and type(binding['generation']) is int and binding['generation'] > 0, 'complete belief binding')
        self.actors, self.query, self.pairs = actors, query, pairs
        self.laws = tuple(tuple(row) for row in laws)
        self.binding = digest(binding)
        self.identity = digest([actors, query, self.laws, binding])

    def history(self, known):
        require(type(known) is tuple and len(known) <= len(self.laws) and
                all(type(r) is tuple and len(r) == 2 and type(r[0]) is int and type(r[1]) is int
                    and 0 <= r[0] < len(self.laws) and 0 <= r[1] < len(self.pairs) for r in known)
                and len({r[0] for r in known}) == len(known), 'known event/pair history')
        require(all(self.laws[i][j] > 0 for i,j in known), 'observation outside declared model support')
        return tuple(sorted(known))

    def marginal(self, known=()):
        """Backward holder distribution, not an argmax state with lost uncertainty."""
        known = dict(self.history(known))
        value = [float(i == self.query) for i in range(self.actors)]
        for i in reversed(range(len(self.laws))):
            if i in known:
                a, b = self.pairs[known[i]]
                value[a], value[b] = value[b], value[a]
                continue
            nxt = [0.]*self.actors
            for weight, (a, b) in zip(self.laws[i], self.pairs):
                if weight:
                    for j in range(self.actors):
                        nxt[j] += weight*value[b if j == a else a if j == b else j]
            value = nxt
        require(abs(math.fsum(value)-1) < 1e-10 and min(value) >= 0, 'holder probability conservation')
        return value


class PlanningBudgetError(ValueError):
    """A rejected computation exposes cost evidence, never a usable action."""
    def __init__(self, message, problem, nodes, started):
        super().__init__(message)
        self.evidence = {'problem_sha256': problem.identity, 'nodes': nodes,
                         'cpu_ns': time.process_time_ns()-started, 'returned': False}


def plan(problem, known=(), *, horizon=2, cost=.02, max_nodes=20000):
    """Exact bounded risk-neutral recursion IN this factorized learned model.

    U=max(0, max_j 2p_j-1, max_i E[U_child]-cost). For each action,
    f=-cost, Z_j=U_child_j-E[U_child], so U_child=U-f+Z and E[Z]=0.
    One horizon is TOTAL remaining checks; replanning cannot silently reset it.
    The upper bound 1-cost allows exact early stopping, not outcome pruning.
    """
    require(type(horizon) is int and 0 <= horizon <= 2 and type(max_nodes) is int and
            1 <= max_nodes <= 20000, 'bounded planning budget')
    require(type(cost) in (int, float) and math.isfinite(cost) and 0 <= cost <= 1, 'verification cost')
    root = problem.history(known)
    count = 0; maximum_residual = 0.
    started = time.process_time_ns()

    @lru_cache(maxsize=20000)
    def visit(history, depth):
        nonlocal count, maximum_residual
        count += 1
        if count > max_nodes:
            raise PlanningBudgetError('verification planner node budget exhausted', problem, count, started)
        if time.process_time_ns()-started > 100_000_000:
            raise PlanningBudgetError('verification planner CPU budget exhausted', problem, count, started)
        probabilities = problem.marginal(history)
        label = max(range(problem.actors), key=lambda j: (probabilities[j], -j))
        best = max(0., 2*probabilities[label]-1)
        action = 'abstain' if best == 0 else f'answer:{label}'
        available = [i for i in range(len(problem.laws)) if i not in dict(history)]
        bounded = depth == 0 or not available or best >= 1-cost-1e-12
        alternatives = []
        if not bounded:
            for i in available:
                children = [(p, visit(tuple(sorted(history+((i, j),))), depth-1)[0])
                            for j, p in enumerate(problem.laws[i]) if p > 0]
                mean = math.fsum(p*v for p, v in children)
                value = mean-cost
                residual = max(abs(v-value-cost-(v-mean)) for _, v in children)
                centered = abs(math.fsum(p*(v-mean) for p,v in children))
                maximum_residual = max(maximum_residual, residual, centered)
                require(maximum_residual < 1e-10, 'finite BSDE interface')
                alternatives.append({'event': i, 'value': value})
                if value > best+1e-12:
                    best, action = value, f'verify:{i}'
        return best, action, probabilities, alternatives, bounded

    value, action, probabilities, alternatives, bounded = visit(root, horizon)
    cpu = time.process_time_ns()-started
    if cpu > 100_000_000:
        raise PlanningBudgetError('verification planner CPU budget exhausted', problem, count, started)
    return {'action': action, 'value': value, 'probabilities': probabilities,
            'known': root, 'remaining_checks': horizon, 'alternatives': alternatives,
            'upper_bound_stop': bounded, 'nodes': count, 'cpu_ns': cpu,
            'max_bsde_residual': maximum_residual, 'problem_sha256': problem.identity,
            'posterior_is_model_dependent': True, 'semantic_certificate': False}
