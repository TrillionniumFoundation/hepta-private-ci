"""Finite NDU/BSDE acquisition on learned joint observations, not future labels.

Three views: initial prefix, paid suffix, paid full text. The kernel retains their
JOINT distribution with labels; multiplying marginal view likelihoods is invalid.
All public histories include view 0. Runtime policies receive only those histories.
The scalar entropic special case is not a continuous fully coupled FBSDE solver.
"""
from dataclasses import dataclass
from functools import lru_cache
from itertools import product
import math

from four_gate_common import digest, integer, require


def history_key(history, symbols):
    require(type(history) is tuple and 1 <= len(history) <= 3, 'bounded public history')
    require(all(type(p) is tuple and len(p) == 2 and type(p[0]) is int and
                p[0] in (0, 1, 2) and type(p[1]) is int and 0 <= p[1] < symbols
                for p in history), 'view/symbol identity')
    require(history[0][0] == 0 and len({p[0] for p in history}) == len(history),
            'initial view required; repeated evidence forbidden')
    return tuple(sorted(history))


def certainty_equivalent(values, weights, rho):
    require(len(values) == len(weights) > 0 and all(math.isfinite(x) for x in values),
            'finite bounded values')
    require(type(rho) in (float, int) and math.isfinite(rho) and 0 <= rho <= 2,
            'registered risk parameter')
    require(all(type(p) in (float, int) and math.isfinite(p) and p >= 0 for p in weights)
            and abs(sum(weights)-1) < 1e-10, 'conditional probability law')
    if rho == 0:
        return sum(v*p for v, p in zip(values, weights))
    anchor = min(values)
    return anchor-math.log(sum(p*math.exp(-rho*(v-anchor)) for v, p in zip(values, weights)))/rho


@dataclass(frozen=True)
class Objective:
    costs: tuple = (.02, .04)
    correct: float = 1.
    wrong: float = -1.
    abstain: float = 0.
    rho: float = 0.

    def validate(self):
        require(type(self.costs) is tuple and len(self.costs) == 2 and
                all(type(c) in (int, float) and math.isfinite(c) and 0 <= c <= 1 for c in self.costs),
                'nonnegative finite acquisition charges')
        require(all(type(x) in (float, int) and math.isfinite(x) and abs(x) <= 10
                    for x in (self.correct, self.wrong, self.abstain)), 'bounded external payoffs')
        require(self.wrong <= self.abstain <= self.correct, 'payoff ordering')
        certainty_equivalent([0.], [1.], self.rho)


class JointKernel:
    """Immutable empirical finite law fitted on a separate pre-test kernel split."""
    def __init__(self, counts, classes, symbols, binding):
        integer(classes, 'classes', 2, 8); integer(symbols, 'symbols', 2, 8)
        require(type(counts) is tuple and len(counts) == classes*symbols**3 and
                all(type(c) in (int, float) and math.isfinite(c) and c > 0 for c in counts),
                'complete positive smoothed joint law')
        self.classes, self.symbols = classes, symbols
        self.counts, self.binding = counts, digest(binding)
        self.identity = digest({'counts': counts, 'classes': classes, 'symbols': symbols,
                                'binding': self.binding})
        # Each original model world contributes once per visible-information subset.
        summaries = {}
        for index, (label, a, b, c) in enumerate(product(range(classes), range(symbols),
                                                       range(symbols), range(symbols))):
            for h in (((0, a),), ((0, a), (1, b)), ((0, a), (2, c)),
                      ((0, a), (1, b), (2, c))):
                mass, labels, observations = summaries.setdefault(h,
                    [0., [0.]*classes, [[0.]*symbols for _ in range(3)]])
                w = counts[index]
                summaries[h][0] += w; labels[label] += w
                for view, symbol in enumerate((a, b, c)): observations[view][symbol] += w
        self.summaries = {h: (mass, tuple(x/mass for x in labels),
                              tuple(tuple(x/mass for x in v) for v in observations))
                          for h, (mass, labels, observations) in summaries.items()}

    @classmethod
    def fit(cls, rows, classes, binding, alpha=.01):
        require(type(rows) is list and 1 <= len(rows) <= 4096, 'kernel training row count')
        require(type(alpha) in (int, float) and math.isfinite(alpha) and 0 < alpha <= 1,
                'fixed positive smoothing')
        integer(classes, 'classes', 2, 8)
        counts = [float(alpha)]*(classes**4)
        for row in rows:
            require(type(row) is tuple and len(row) == 4 and
                    all(type(x) is int and 0 <= x < classes for x in row), 'kernel label/symbol tuple')
            index = 0
            for value in row: index = index*classes+value
            counts[index] += 1
        return cls(tuple(counts), classes, classes, binding)

    def distribution(self, history):
        return self.summaries[history_key(history, self.symbols)]

    def legal_reads(self, history):
        h = history_key(history, self.symbols)
        return tuple(v for v in (1, 2) if v not in dict(h))


def terminal(kernel, history, objective):
    _, belief, _ = kernel.distribution(history)
    candidates = [('abstain', objective.abstain)]
    for label, p in enumerate(belief):
        candidates.append((f'answer:{label}', certainty_equivalent(
            [objective.correct, objective.wrong], [p, 1-p], objective.rho)))
    # Declared stable tie rule prefers abstention, then the lower label.
    return max(candidates, key=lambda pair: pair[1])


def solve(kernel, initial, objective, *, one_step=False):
    """Exact finite backward sweep; state transitions are forward conditional Bayes.

    M=e_observed-p, Z_j=child_j-E(child), and
    f=CE_rho(child)-E(child)-cost. Thus child=Y-f+Z_j and E(Z)=0.
    With rho>0 this is a nonlinear conditional generator, not just f=0.
    """
    objective.validate(); initial = history_key(initial, kernel.symbols)
    actions, values, edges = {}, {}, []
    @lru_cache(maxsize=1024)
    def visit(h):
        best_action, best_value = terminal(kernel, h, objective)
        _, _, laws = kernel.distribution(h)
        for view in kernel.legal_reads(h):
            child_h = [history_key(h+((view, s),), kernel.symbols) for s in range(kernel.symbols)]
            children = [terminal(kernel, c, objective)[1] if one_step else visit(c) for c in child_h]
            law = laws[view]; mean = sum(p*y for p, y in zip(law, children))
            value = certainty_equivalent(children, law, objective.rho)-objective.costs[view-1]
            generator = value-mean; z = [y-mean for y in children]
            residual = max(abs(y-value+generator-dz) for y, dz in zip(children, z))
            require(residual < 1e-10 and abs(sum(p*v for p, v in zip(law, z))) < 1e-10,
                    'finite BSDE/martingale interface mismatch')
            edges.append({'history': h, 'view': view, 'law': law, 'children': children,
                          'value': value, 'generator': generator, 'z': z, 'residual': residual})
            if value > best_value+1e-12:
                best_action, best_value = f'read:{view}', value
        actions[h], values[h] = best_action, best_value
        return best_value
    value = visit(initial)
    return {'value': value, 'action': actions[initial], 'actions': actions,
            'values': values, 'edges': edges, 'kernel_sha256': kernel.identity,
            'objective_sha256': digest(objective.__dict__)}


def exhaustive_reference(kernel, initial, objective):
    """Independent whole-policy enumeration from original masses, not solve().

    The best terminal answer is analytically enumerated at each information set.
    Enumerate stop and every contingent stop/second-view map (2**symbols) after
    either first view; reduce the total terminal outcomes in one flat CE.
    Fixed-rho CE is cash additive/time consistent, so this is a separate oracle.
    """
    objective.validate(); initial = history_key(initial, kernel.symbols)
    require(len(initial) == 1, 'whole-policy oracle starts at initial information')
    worlds = [(y, (a, b, c), kernel.counts[i]) for i, (y, a, b, c) in enumerate(
        product(range(kernel.classes), range(kernel.symbols), range(kernel.symbols), range(kernel.symbols)))
              if a == initial[0][1]]
    @lru_cache(maxsize=1024)
    def end(h):
        subset = [(y, mass) for y, symbols, mass in worlds if all(symbols[v] == s for v, s in h)]
        denom = sum(m for _, m in subset)
        options = [('abstain', [objective.abstain]*len(subset))]
        options += [(f'answer:{label}', [objective.correct if label == y else objective.wrong
                                        for y, _ in subset]) for label in range(kernel.classes)]
        return max(((a, certainty_equivalent(v, [m/denom for _, m in subset], objective.rho))
                    for a, v in options), key=lambda x: x[1])
    best_action, best_value = end(initial); evaluated = 1
    denom = sum(m for _, _, m in worlds)
    for first in (1, 2):
        second = 3-first
        for continuation in product((False, True), repeat=kernel.symbols):
            rewards, weights = [], []
            for y, symbols, mass in worlds:
                h = history_key(initial+((first, symbols[first]),), kernel.symbols)
                cost = objective.costs[first-1]
                if continuation[symbols[first]]:
                    h = history_key(h+((second, symbols[second]),), kernel.symbols)
                    cost += objective.costs[second-1]
                action, _ = end(h)
                reward = (objective.abstain if action == 'abstain' else
                          objective.correct if action == f'answer:{y}' else objective.wrong)
                rewards.append(reward-cost); weights.append(mass/denom)
            value = certainty_equivalent(rewards, weights, objective.rho); evaluated += 1
            if value > best_value+1e-12: best_action, best_value = f'read:{first}', value
    return {'action': best_action, 'value': best_value, 'policies_evaluated': evaluated}


class ViewPort:
    """Bounded evaluator-process information port; not a security sandbox or owner."""
    def __init__(self, callback, symbols):
        self._callback, self.symbols, self._history, self.events = callback, symbols, (), []

    def read(self, view):
        require(type(view) is int and view in (0, 1, 2) and view not in dict(self._history),
                'invalid/repeated view')
        require(view == 0 if not self._history else view != 0, 'initial view must be first')
        symbol, receipt = self._callback(view)
        integer(symbol, 'observed symbol', 0, self.symbols-1)
        self._history += ((view, symbol),)
        self.events.append({'view': view, 'symbol': symbol, 'receipt': receipt})
        return history_key(self._history, self.symbols)
