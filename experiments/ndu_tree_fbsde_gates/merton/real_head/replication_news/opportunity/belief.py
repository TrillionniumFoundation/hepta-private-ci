"""Finite empirical opportunity model. Optima are model-relative, not task guarantees."""
from __future__ import annotations

import math
from functools import lru_cache
from fractions import Fraction

STEPS = (0, 8, 32, 128)
BATCHES = (8, 8, 16)
MODES = ('neutral', 'fixed', 'ndu')
TOL = 1e-12


def validate(curves, scenario, mode):
    if mode not in MODES or not 1 <= len(curves) <= 8:
        raise ValueError('unknown mode or invalid finite prior')
    for row in curves:
        if len(row) != 4 or any(type(v) is not int or not 0 <= v <= 16 for v in row):
            raise ValueError('each curve needs four integer correct counts out of16')
    if set(scenario) != {'name', 'horizon', 'step_fee', 'calibration_fee', 'budget'}:
        raise ValueError('unknown scenario field')
    if type(scenario['budget']) is not int or not 0 <= scenario['budget'] <= 128:
        raise ValueError('invalid hard optimizer budget')
    if type(scenario['horizon']) is not int or not 1 <= scenario['horizon'] <= 64:
        raise ValueError('invalid hypothetical reuse horizon')
    for name in ('step_fee', 'calibration_fee'):
        if not isinstance(scenario[name], str) or Fraction(scenario[name]) < 0:
            raise ValueError('nonnegative rational tariff required')


def check_history(history):
    if not isinstance(history, tuple) or len(history) > 3:
        raise ValueError('invalid public history')
    if any(type(k) is not int or not 0 <= k <= n for k, n in zip(history, BATCHES)):
        raise ValueError('invalid observed calibration count')


def preference(history, mode):
    check_history(history)
    p = Fraction(0) if mode == 'neutral' else Fraction(1, 4)
    if mode == 'ndu':
        for k, n in zip(history, BATCHES):
            p = min(Fraction(1, 2), max(Fraction(0), p + (1-2*Fraction(k, n))/8))
    return p


def aggregate(mass, values, alpha):
    if len(mass) != len(values) or not mass or any(p <= 0 for p in mass):
        raise ValueError('invalid supported law')
    if not all(math.isfinite(v) for v in (*mass, *values, alpha)):
        raise ValueError('nonfinite value')
    if abs(math.fsum(mass)-1) > 1e-10 or not 0 <= alpha <= .5:
        raise ValueError('invalid probability normalization or preference')
    return (1-alpha)*math.fsum(p*v for p, v in zip(mass, values)) + alpha*min(values)


class Planner:
    """Enumerates future count observations, with no actual future model execution.

    Four empirical latent curve types induce correlated checkpoint expectations.
    Conditional count emissions assume IID items in disjoint calibration slices.
    Folds overlap in training and are NOT four independent source families.
    """
    def __init__(self, curves, scenario, mode='neutral', pruning=True):
        validate(curves, scenario, mode)
        if type(pruning) is not bool:
            raise ValueError('strict pruning flag required')
        self.pruning = pruning
        self.curves = tuple(tuple(c) for c in curves)
        self.scenario, self.mode = dict(scenario), mode
        self.rates = tuple(tuple((v+1)/18 for v in row) for row in curves)
        self.emission = tuple(tuple(tuple(math.comb(n, k)*row[j+1]**k*(1-row[j+1])**(n-k)
                                        for k in range(n+1)) for row in self.rates)
                              for j, n in enumerate(BATCHES))
        self.posterior = lru_cache(None)(self._posterior)
        self.solve = lru_cache(None)(self._solve)

    def _posterior(self, history):
        check_history(history)
        mass = [math.prod(self.emission[j][f][k] for j, k in enumerate(history))
                for f in range(len(self.rates))]
        total = math.fsum(mass)
        if not total > 0:
            raise ValueError('unsupported posterior')
        return tuple(v/total for v in mass)

    def _solve(self, history):
        check_history(history)
        j = len(history)
        if STEPS[j] > self.scenario['budget']:
            raise ValueError('history could not have been afforded')
        mass = self.posterior(history)
        alpha = float(preference(history, self.mode))
        h = self.scenario['horizon']
        candidates = [h*aggregate(mass, tuple(row[i] for row in self.rates), alpha)
                      for i in range(j+1)]
        best = max(range(j+1), key=lambda i: (candidates[i], -i))
        stop = candidates[best]
        result = {'action': 'stop', 'selected_steps': STEPS[best], 'stop_value': stop,
                  'continue_value': None, 'value': stop, 'to_step': None,
                  'alpha': str(preference(history, self.mode)), 'posterior': list(mass),
                  'reason': 'horizon_complete', 'pruned': False, 'continue_value_upper_bound': None}
        if j == 3:
            return result
        if STEPS[j+1] > self.scenario['budget']:
            result['reason'] = 'hard_budget'
            return result
        fee = float(Fraction(self.scenario['step_fee']))*(STEPS[j+1]-STEPS[j])
        fee += float(Fraction(self.scenario['calibration_fee']))
        # rho never exceeds its largest supported value. Every continuation
        # must pay fee first and all later costs are nonnegative. This bound
        # is model-relative and requires no unexecuted observation or fit.
        upper = h*max(max(row) for row in self.rates)-fee
        if self.pruning and upper <= stop + TOL:
            result.update(reason='admissible_model_bound', pruned=True,
                          continue_value_upper_bound=upper)
            return result
        n = BATCHES[j]
        prob = tuple(math.fsum(mass[f]*self.emission[j][f][k] for f in range(len(mass)))
                     for k in range(n+1))
        # Numerical normalization is explicit and leaves every supported branch.
        total = math.fsum(prob)
        prob = tuple(p/total for p in prob)
        child = tuple(self.solve(history+(k,))['value'] for k in range(n+1))
        cont = aggregate(prob, child, alpha)-fee
        result['continue_value'] = cont
        result['reason'] = 'nonpositive_model_net'
        if cont > stop + TOL:
            result.update(action='continue', value=cont, to_step=STEPS[j+1],
                          reason='positive_model_net_not_guarantee')
        return result

    def decision(self, history):
        value = dict(self.solve(tuple(history)))
        value['evaluated_model_nodes'] = self.solve.cache_info().currsize
        return value
