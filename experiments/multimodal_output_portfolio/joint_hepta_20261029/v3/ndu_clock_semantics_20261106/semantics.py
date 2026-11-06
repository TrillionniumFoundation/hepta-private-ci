"""High-precision independent evaluators for finite timed reward trees.

Fixed local risk and time-zero trajectory risk are different contracts. A forced
wait split is valid only when its intermediate node adds no observation, action
choice, fee, duration or payoff. No original NDU objective is silently rewritten.
"""
from decimal import Decimal as D, localcontext
from functools import lru_cache
from itertools import product


def number(value):
    return D(str(value))


def ce(law, eta):
    """law contains Decimal probability/value pairs; ordinary Decimal arithmetic."""
    if eta <= 0 or not law or abs(sum(p for p, _ in law)-1) > D('1e-95'):
        raise ValueError('Positive eta and normalized nonempty probability law required')
    if any(p < 0 for p, _ in law):
        raise ValueError('Negative probability')
    anchor = min(x for _, x in law)
    return anchor-sum(p*(-eta*(x-anchor)).exp() for p, x in law).ln()/eta


def validate(nodes, root):
    if root not in nodes:
        raise ValueError('Missing root')
    active, done = set(), set()
    def visit(s):
        if s in active:
            raise ValueError('Finite acyclic trees required')
        if s in done:
            return
        if s not in nodes or not nodes[s]:
            raise ValueError('Missing legal action row')
        active.add(s)
        for law in nodes[s].values():
            if abs(sum(p for p, _, _, _ in law)-1) > D('1e-95'):
                raise ValueError('Probability mass lost')
            for p, reward, duration, child in law:
                if not p.is_finite() or p < 0 or not reward.is_finite() or type(duration) is not int or duration < 0:
                    raise ValueError('Malformed outcome')
                if child is not None:
                    visit(child)
        active.remove(s); done.add(s)
    visit(root)


def backward(nodes, root, gamma, eta, mode='transport'):
    """Deterministic Bellman policies; rewards are paid at each node's time.

    Children are indexed by elapsed time, so unequal durations do not silently
    share a risk parameter. All probabilities and durations are provided here.
    """
    validate(nodes, root)
    if mode not in ('fixed', 'transport') or not 0 < gamma <= 1 or eta <= 0:
        raise ValueError('Declared risk mode, discount and eta required')
    choices, qrows = {}, {}
    @lru_cache(None)
    def rec(s, elapsed):
        local_eta = eta*(gamma**elapsed) if mode == 'transport' else eta
        values = {}
        for action, law in nodes[s].items():
            outcomes = [(p, reward+(gamma**duration)*rec(child, elapsed+duration)
                         if child is not None else reward)
                        for p, reward, duration, child in law]
            values[action] = ce(outcomes, local_eta)
        action = max(sorted(values), key=values.get)
        choices[(s, elapsed)], qrows[(s, elapsed)] = action, values
        return values[action]
    value = rec(root, 0)
    return value, choices, qrows


def terminal_law(nodes, root, policy, gamma):
    """Enumerate physical terminal payoff/time independently of Bellman CE."""
    validate(nodes, root)
    result = []
    def visit(s, elapsed, probability, payoff):
        for p, reward, duration, child in nodes[s][policy[s]]:
            new_payoff = payoff+(gamma**elapsed)*reward
            if child is None:
                result.append((probability*p, new_payoff, elapsed+duration))
            else:
                visit(child, elapsed+duration, probability*p, new_payoff)
    visit(root, 0, D(1), D(0))
    return result


def exhaustive(nodes, root, gamma, eta):
    """Independent strong baseline for these trees: all deterministic policies.

    The small audit graphs have unique time per state. This enumerator is not a
    general merged-state history planner; such inputs must expand state by time.
    """
    states = list(nodes)
    results = []
    for actions in product(*(sorted(nodes[s]) for s in states)):
        policy = dict(zip(states, actions))
        law = terminal_law(nodes, root, policy, gamma)
        value = ce([(p, payoff) for p, payoff, _ in law], eta)
        results.append((value, policy, law))
    return max(results, key=lambda row: row[0]), results


def pair(p=D('.5'), duration=1, safe=D('.16'), launch=D('.01')):
    terminals = {'zero': {'STOP': [(D(1), D(0), 0, None)]},
                 'one': {'STOP': [(D(1), D(1), 0, None)]}}
    common = [(D(1)-p, D(0), 0, 'zero'), (p, D(0), 0, 'one')]
    coarse = {'root': {'STOP': [(D(1), safe, 0, None)],
                       'probe': [(D(1)-p, -launch, duration, 'zero'),
                                 (p, -launch, duration, 'one')]}, **terminals}
    refined = {'root': {'STOP': [(D(1), safe, 0, None)],
                        'probe': [(D(1), -launch, duration, 'resolve')]},
               'resolve': {'forced': common}, **terminals}
    return coarse, refined


def duration_tree():
    """Two duration-conditioned continuation laws; duration is observed legally."""
    return {
        'root': {'STOP': [(D(1), D('.12'), 0, None)],
                 'probe': [(D('.4'), D('-.01'), 1, 'fast'),
                           (D('.6'), D('-.01'), 2, 'slow')]},
        'fast': {'forced': [(D('.2'), D(0), 0, 'zero'), (D('.8'), D(0), 0, 'one_fast')]},
        'slow': {'forced': [(D('.8'), D(0), 0, 'zero_late'), (D('.2'), D(0), 0, 'one_slow')]},
        'zero': {'STOP': [(D(1), D(0), 0, None)]},
        'zero_late': {'STOP': [(D(1), D(0), 0, None)]},
        'one_fast': {'STOP': [(D(1), D(1), 0, None)]},
        'one_slow': {'STOP': [(D(1), D(1), 0, None)]},
    }
