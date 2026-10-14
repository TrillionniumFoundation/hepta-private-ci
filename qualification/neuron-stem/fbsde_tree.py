"""Finite exact forward-belief/backward-utility tree; never a clairvoyant policy.

Registered special case: one-step discrete BSDE, f=-acquisition_cost/dt,
martingale increment M=1{observed bit=1}-p. No continuous nonlinear/FBSDE
convergence or learned reasoning claim follows from this exact finite solver.
"""
from dataclasses import dataclass
from fractions import Fraction as F
from itertools import product
import time

from four_gate_common import require

WORLDS = ((0, 0), (0, 1), (1, 0), (1, 1))


@dataclass(frozen=True)
class Problem:
    probabilities: tuple = (F(9, 20), F(1, 20), F(3, 20), F(7, 20))
    inspect_costs: tuple = (F(1, 10), F(3, 20))
    correct: F = F(1)
    wrong: F = F(-3)
    stop: F = F(1, 5)

    def validate(self):
        require(len(self.probabilities) == 4 and all(type(p) is F and p > 0 for p in self.probabilities)
                and sum(self.probabilities) == 1, 'positive exact probability law required')
        require(len(self.inspect_costs) == 2 and all(type(c) is F and c >= 0 for c in self.inspect_costs),
                'nonnegative exact acquisition costs')
        require(all(type(v) is F for v in (self.correct, self.wrong, self.stop)), 'exact payoff profile')


def posterior(problem, history):
    require(type(history) is tuple and len(history) <= 2, 'bounded public history')
    seen = set()
    for coordinate, value in history:
        require(type(coordinate) is int and coordinate in (0, 1) and coordinate not in seen
                and type(value) is int and value in (0, 1), 'invalid/repeated revealed observation')
        seen.add(coordinate)
    weights = [p if all(w[i] == v for i, v in history) else F(0)
               for w, p in zip(WORLDS, problem.probabilities)]
    mass = sum(weights)
    require(mass > 0, 'unreachable information set')
    return tuple(p/mass for p in weights)


def legal(history):
    if len(history) == 2:
        return ('all',)
    return ('stop', 'false', 'true') + tuple('inspect_'+str(i) for i in (0, 1)
                                             if i not in dict(history))


def conjunction(history):
    require(len(history) == 2 and set(dict(history)) == {0, 1}, 'both obligations must finish')
    return bool(dict(history)[0] and dict(history)[1])


def terminal_value(problem, history, action):
    if action == 'stop':
        return problem.stop
    if action == 'all':
        conjunction(history)
        return problem.correct
    require(action in ('true', 'false'), 'not a terminal action')
    answer = action == 'true'
    return sum(p*(problem.correct if answer == bool(w[0] and w[1]) else problem.wrong)
               for p, w in zip(posterior(problem, history), WORLDS))


def sweep(problem):
    """Backward fields on public information sets; conditional laws are forward Bayes."""
    problem.validate()
    policies, fields, boundaries = {}, {}, []

    def visit(history):
        weights = posterior(problem, history)
        candidates = {}
        for action in legal(history):
            if not action.startswith('inspect_'):
                candidates[action] = terminal_value(problem, history, action)
                continue
            coordinate = int(action[-1])
            p = sum(weight for w, weight in zip(WORLDS, weights) if w[coordinate])
            u0, u1 = [visit(history+((coordinate, v),)) for v in (0, 1)]
            cost = problem.inspect_costs[coordinate]
            u = (1-p)*u0+p*u1-cost
            z = u1-u0
            # Exact one-step martingale representation, not max over chance nodes.
            residuals = [abs(child-u-cost-z*(F(v)-p)) for v, child in ((0, u0), (1, u1))]
            boundaries.append({'history': history, 'action': action, 'p': p, 'u': u,
                               'children': (u0, u1), 'z': z, 'variance': p*(1-p),
                               'residual': max(residuals), 'cost': cost})
            candidates[action] = u
        selected = max(candidates, key=lambda a: (candidates[a], -legal(history).index(a)))
        policies[history], fields[history] = selected, candidates[selected]
        return candidates[selected]

    value = visit(())
    return value, policies, fields, boundaries


def public_decision_histories():
    return ((), ((0, 0),), ((0, 1),), ((1, 0),), ((1, 1),))


def execute(problem, policy, world):
    """Environment reveals only the requested bit; policy receives history only."""
    history, cost, decisions = (), F(0), []
    for _ in range(3):
        action = 'all' if len(history) == 2 else policy[history]
        require(action in legal(history), 'inadmissible policy action')
        decisions.append((history, action))
        if action.startswith('inspect_'):
            coordinate = int(action[-1])
            history += ((coordinate, world[coordinate]),)
            cost += problem.inspect_costs[coordinate]
        else:
            if action == 'stop':
                return problem.stop-cost, cost, decisions, None
            answer = conjunction(history) if action == 'all' else action == 'true'
            reward = problem.correct if answer == bool(world[0] and world[1]) else problem.wrong
            return reward-cost, cost, decisions, answer
    raise ValueError('bounded policy failed to terminate')


def enumerate_policies(problem):
    """Independent whole-policy oracle: enumerate ALL 5*4**4 policies and worlds."""
    problem.validate()
    histories = public_decision_histories()
    best, winner, count = None, None, 0
    for choices in product(*(legal(h) for h in histories)):
        policy = dict(zip(histories, choices))
        value = sum(p*execute(problem, policy, w)[0] for w, p in zip(WORLDS, problem.probabilities))
        if best is None or value > best:
            best, winner = value, policy
        count += 1
    return best, winner, count


def check_nonanticipative(traces):
    chosen = {}
    for trace in traces:
        for history, action in trace:
            require(chosen.setdefault(history, action) == action,
                    'same public information set chose based on unrevealed future')
    return True


def joint_probability(formula, leaf_p):
    """Exact event probability for independent model-belief leaves; not true law proof.

    The semantic leaf probabilities are predictions, not ground truth. General
    correlations require their actual joint distribution, not this profile.
    """
    require(1 <= len(leaf_p) <= 8 and all(0 <= p <= 1 for p in leaf_p), 'bounded probabilities')
    result = 0.
    for world in product((False, True), repeat=len(leaf_p)):
        mass = 1.
        for bit, p in zip(world, leaf_p):
            mass *= p if bit else 1-p
        result += mass*bool(eval_formula(formula, world))
    return result


def eval_formula(formula, leaves):
    if type(formula) is int:
        require(0 <= formula < len(leaves), 'invalid leaf')
        return leaves[formula]
    require(type(formula) in (list, tuple) and len(formula) == 3 and formula[0] in ('and', 'or'),
            'registered Boolean formula only')
    a, b = eval_formula(formula[1], leaves), eval_formula(formula[2], leaves)
    return (a and b) if formula[0] == 'and' else (a or b)


def belief_bsde(formula, leaf_p):
    """Explicit scenario-tree local BSDE sweep with f=0 and no control optimization."""
    require(1 <= len(leaf_p) <= 8 and all(0 <= p <= 1 for p in leaf_p), 'bounded beliefs')
    fields, residuals, nodes = {}, [], 0
    def visit(prefix):
        nonlocal nodes
        nodes += 1
        if len(prefix) == len(leaf_p):
            value = float(bool(eval_formula(formula, prefix)))
        else:
            p = leaf_p[len(prefix)]
            a, b = visit(prefix+(False,)), visit(prefix+(True,))
            value = (1-p)*a+p*b
            z = b-a
            residuals.extend((abs(a-value+z*p), abs(b-value-z*(1-p))))
        fields[prefix] = value
        return value
    u = visit(())
    return u, max(residuals, default=0.), nodes


def polynomial_probability(formula, leaf_p):
    """Cheap exact comparator for read-once formulas using SAME semantic predictions."""
    used = set()
    def visit(f):
        if type(f) is int:
            require(f not in used and 0 <= f < len(leaf_p), 'repeated/dependent leaf unsupported')
            used.add(f)
            return leaf_p[f]
        require(len(f) == 3 and f[0] in ('and', 'or'), 'formula shape')
        a, b = visit(f[1]), visit(f[2])
        return a*b if f[0] == 'and' else a+b-a*b
    return visit(formula)


def experiment():
    rows = []
    priors = ((9, 1, 3, 7), (5, 5, 5, 5), (1, 1, 1, 17), (17, 1, 1, 1))
    for weights in priors:
        for ca, cb in ((1, 2), (2, 3), (5, 7), (8, 9)):
            p = Problem(tuple(F(w, sum(weights)) for w in weights), (F(ca, 20), F(cb, 20)))
            begin = time.process_time_ns()
            reference, _, count = enumerate_policies(p)
            enum_cpu = time.process_time_ns()-begin
            begin = time.process_time_ns()
            value, policy, fields, boundaries = sweep(p)
            sweep_cpu = time.process_time_ns()-begin
            traces = [execute(p, policy, world) for world in WORLDS]
            check_nonanticipative([v[2] for v in traces])
            require(reference == value and all(b['residual'] == 0 for b in boundaries),
                    'local/global tree mismatch')
            rows.append({'prior': [str(v) for v in p.probabilities], 'costs': [str(v) for v in p.inspect_costs],
                         'enumerated_policies': count, 'root_value': str(value), 'reference': str(reference),
                         'root_action': policy[()], 'max_interface_residual': '0',
                         'information_sets': len(fields), 'nonanticipative': True,
                         'modeled_expected_acquisition_cost': str(sum(v[1]*w for v, w in zip(traces, p.probabilities))),
                         'measured_enumeration_cpu_ns': enum_cpu, 'measured_sweep_cpu_ns': sweep_cpu,
                         'policy': [{'history': list(k), 'action': v} for k, v in policy.items()],
                         'local_edges': [{**b, 'p': str(b['p']), 'u': str(b['u']), 'z': str(b['z']),
                                          'children': list(map(str, b['children'])), 'variance': str(b['variance']),
                                          'residual': str(b['residual']), 'cost': str(b['cost'])} for b in boundaries]})
    cheating = [[((), 'true')], [((), 'false')]]
    try:
        check_nonanticipative(cheating)
        raise AssertionError('clairvoyant policy accepted')
    except ValueError:
        pass
    return {'schema': 'hepta.fbsde.finite-tree-study.v1', 'rows': rows,
            'anticipative_mutant_rejected': True, 'profile': 'discrete_finite_BSDE_with_Bayes_forward_state',
            'modeled_cost_is_not_measured_CPU': True, 'production_promotion_permitted': False,
            'continuous_fully_coupled_FBSDE_claimed': False}
