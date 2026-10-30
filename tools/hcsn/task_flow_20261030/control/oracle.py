"""Finite Bellman values conditioned on a TRAIN-calibrated observation law."""
from functools import lru_cache
import numpy as np
from common import ACTIONS


def feasible(meta, job, tick, budget):
    active = job < 2 and tick < meta["deadline"]
    return np.array([True, active and tick+1 < meta["deadline"],
                     active and budget > 0 and tick+1 < meta["deadline"], active])


def likelihood(confusion, reliability):
    return reliability*confusion + (1-reliability)*confusion[::-1]


def outcomes(posterior, law):
    probability = (1-posterior)*law[0] + posterior*law[1]
    return probability, np.divide(posterior*law[1], probability, out=np.full(2, .5), where=probability > 0)


class Bellman:
    def __init__(self, meta, confusion, multiplier, future=True):
        self.meta, self.confusion = meta, np.asarray(confusion, np.float64)
        self.multiplier, self.future = float(multiplier), future
        self.value = lru_cache(maxsize=None)(self._value)
        self.q = lru_cache(maxsize=None)(self._q)

    def _value(self, job, tick, budget, posterior):
        return float(max(self.q(job, tick, budget, posterior)))

    def _q(self, job, tick, budget, posterior):
        valid = feasible(self.meta, job, tick, budget)
        result = [0., -4., -4., -4.]
        if not valid[3]:
            return tuple(result)
        if valid[1]:
            result[1] = self.value(job, tick+1, budget, posterior)
        if valid[2]:
            law = likelihood(self.confusion, self.meta["reliability"][job][tick])
            probability, beliefs = outcomes(posterior, law)
            continuation = sum(float(probability[o])*self.value(job, tick+1, budget-1, float(beliefs[o])) for o in range(2))
            result[2] = continuation-self.multiplier*self.meta["price"][job][tick]
        continuation = self.value(job+1, tick+2, budget, .5) if self.future else 0.
        result[3] = abs(2*posterior-1)+continuation
        return tuple(result)


def features(meta, job, tick, budget, posterior, confusion, multiplier):
    remaining = max(meta["deadline"]-tick, 0)
    active = job < 2 and remaining > 0
    quality = np.asarray(meta["reliability"][min(job, 1)][min(tick, meta["deadline"]-1):], float)
    price = multiplier*np.asarray(meta["price"][min(job, 1)][min(tick, meta["deadline"]-1):], float)
    q, cost = float(quality[0]), float(price[0])
    law = likelihood(confusion, q)
    probability, beliefs = outcomes(posterior, law)
    gain = float(np.sum(probability*np.abs(2*beliefs-1))-abs(2*posterior-1))
    base = np.array([posterior, abs(2*posterior-1), remaining/10., budget/4., job,
                     q, cost, float(quality.max()), float(quality.mean()), float(price.min()),
                     float(price.mean()), multiplier/3., gain, remaining > 2, active], float)
    pairs = np.array([base[1]*base[2], base[1]*base[6], base[1]*base[3], base[2]*base[3],
                      base[4]*base[2], base[6]*base[3], base[7]-base[5], gain-cost,
                      base[5]*base[2], base[1]*base[4], base[7]*base[3]], float)
    return np.concatenate([[1.], base, base[:13]**2, pairs])


def myopic_action(meta, job, tick, budget, posterior, confusion, multiplier):
    valid = feasible(meta, job, tick, budget)
    if not valid[3]:
        return "STOP"
    immediate = abs(2*posterior-1)
    if valid[2]:
        law = likelihood(confusion, meta["reliability"][job][tick])
        prob, belief = outcomes(posterior, law)
        after = float(prob @ np.abs(2*belief-1))-multiplier*meta["price"][job][tick]
        if after > immediate + 1e-12:
            return "READ"
    if valid[1] and tick+2 < meta["deadline"] and budget > 0:
        next_quality = max(meta["reliability"][job][tick+1:])
        next_cost = multiplier*min(meta["price"][job][tick+1:])
        prob, belief = outcomes(posterior, likelihood(confusion, next_quality))
        if float(prob @ np.abs(2*belief-1))-next_cost > immediate + 1e-12:
            return "SKIP"
    return "FIRE" if immediate > 0. else "STOP"
