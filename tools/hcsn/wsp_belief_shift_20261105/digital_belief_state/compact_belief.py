"""Sufficient-state Bellman prototype for the pinned static-label digital task.

The binary label is fixed and completed measurements are conditionally
independent under the supplied decoder confusion. Posterior odds, current tick,
budget, broken flag and pending source/due pair are sufficient for future value.
This representation is not valid for the separate moving-label renewal task.
"""
from fractions import Fraction
from functools import lru_cache
import hashlib
import json

import numpy as np


class CompactBeliefPlanner:
    def __init__(self, public, confusion):
        self.public = json.loads(json.dumps(public))
        self.public_sha256 = hashlib.sha256(json.dumps(self.public, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.confusion = np.asarray(confusion, dtype=np.float64)
        if self.confusion.shape != (2, 2) or not np.isfinite(self.confusion).all() or np.any(self.confusion <= 0) or not np.allclose(self.confusion.sum(1), 1):
            raise ValueError('positive row-stochastic decoder confusion required')
        self.emissions = []
        for reliability in public['reliability']:
            law = reliability * self.confusion + (1 - reliability) * self.confusion[::-1]
            self.emissions.append(tuple(tuple(Fraction(float(x)) for x in row) for row in law))
        self.value = lru_cache(None)(self._value)

    def key(self, state):
        belief = Fraction(1, 2)
        seen = set()
        for row in state['history']:
            source, observation = row['source_tick'], row['observation']
            if source in seen or not 0 <= source < state['tick'] or observation not in (0, 1):
                raise ValueError('duplicate, future or invalid completed observation')
            seen.add(source)
            belief = self.updated(belief, source, observation)
        pending = state['pending']
        return (state['tick'], state['budget'], state['broken'],
                None if pending is None else (pending['source_tick'], pending['due_tick']), belief)

    def updated(self, belief, source, observation):
        law = self.emissions[source]
        denominator = (1 - belief) * law[0][observation] + belief * law[1][observation]
        if denominator <= 0:
            raise ValueError('impossible completion under supplied decoder')
        return belief * law[1][observation] / denominator

    def legal(self, key):
        tick, budget, broken, pending, _ = key
        before = tick < 6
        return (True, before, before and budget > 0 and not broken and pending is None
                and tick + self.public['read_delay'][tick] <= 6, before and broken, True, True)

    def branches(self, key, action):
        tick, budget, broken, pending, belief = key
        if action not in (1, 2, 3) or not self.legal(key)[action]:
            raise ValueError('legal nonterminal action required')
        charge = self.public['latency_price'] * self.public['duration'][tick]
        if action == 2:
            pending = (tick, tick + self.public['read_delay'][tick])
            budget -= 1
            charge += self.public['read_price'][tick]
        if action == 3:
            broken = False
            charge += self.public['repair_price']
        if pending is None or pending[1] != tick + 1:
            return ((1., (tick + 1, budget, broken, pending, belief), charge),)
        source = pending[0]
        law = self.emissions[source]
        failure = self.public['failure_probability']
        outcomes = [(failure, (tick + 1, budget, True, None, belief), charge)]
        for observation in (0, 1):
            chance = (1 - belief) * law[0][observation] + belief * law[1][observation]
            outcomes.append(((1 - failure) * float(chance),
                             (tick + 1, budget, broken, None, self.updated(belief, source, observation)), charge))
        return outcomes

    def q(self, key):
        belief = float(key[-1])
        values = [0., float('-inf'), float('-inf'), float('-inf'), 1 - 2 * belief, 2 * belief - 1]
        for action in (1, 2, 3):
            if self.legal(key)[action]:
                values[action] = sum(probability * (self.value(after) - charge)
                                     for probability, after, charge in self.branches(key, action) if probability > 0)
        return np.asarray(values)

    def _value(self, key):
        return float(np.max(self.q(key)))
