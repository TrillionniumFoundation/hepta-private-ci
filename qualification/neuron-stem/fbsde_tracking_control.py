"""Finite NDU verification on LEARNED swap beliefs, not a language certificate.

An event is a categorical distribution over unordered actor pairs. Independent
errors across events are a declared modelling approximation, NOT established
because a common gate was trained. Exact source operations are unavailable to
this planner; a separate callback reveals only the requested event after choice.
"""
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

    def available_events(self, known=()):
        return [i for i in range(len(self.laws)) if i not in dict(self.history(known))]

    def outcome_law(self, event, known=()):
        """Conditional-law port; V1 is independent, other profiles need not be."""
        require(type(event) is int and 0 <= event < len(self.laws), 'observation event index')
        history = dict(self.history(known))
        if event in history:
            return tuple(float(j == history[event]) for j in range(len(self.pairs)))
        return self.laws[event]

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
    """Exact bounded risk-neutral recursion using the declared conditional-law port.

    U=max(0, max_j 2p_j-1, max_i E[U_child]-cost). For each action,
    f=-cost, Z_j=U_child_j-E[U_child], so U_child=U-f+Z and E[Z]=0.
    One horizon is TOTAL remaining checks; replanning cannot silently reset it.
    The upper bound 1-cost allows exact early stopping, not outcome pruning.
    """
    require(type(horizon) is int and 0 <= horizon <= 2, 'bounded planning budget')
    from fbsde_planning_workspace import PlanningWorkspace
    work = PlanningWorkspace(problem, known, cost=cost, max_nodes=max_nodes)
    started = work.started
    with work:
        result = work.solve(known, horizon=horizon)
    # Include construction and deterministic cache disposal in the original budget.
    result['cpu_ns'] = time.process_time_ns()-started
    if result['cpu_ns'] > 100_000_000:
        raise PlanningBudgetError('verification planner CPU budget exhausted', problem, result['nodes'], started)
    return result
