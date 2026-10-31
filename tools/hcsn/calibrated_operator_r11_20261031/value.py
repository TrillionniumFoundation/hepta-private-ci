"""Ordinary belief-grid Bellman control with exact action semantics.

This is a numerical value controller fitted to each public schedule by backward
Bellman backups, not a claim that an unconstrained MLP has learned DP. No packet
or evaluator label is needed. The observation law is fitted on TRAIN packets.
"""
import time

import numpy as np

from ..task_value_factorial_20261030.dataset import decode_features
from ..task_value_factorial_20261030.task import elapsed, feasible, likelihood


def select_action(q, valid):
    """Priority STOP/SKIP/READ/FIRE for numerical ties within 1e-12 utility."""
    choice = 0
    for index in range(1, 4):
        if valid[index] and q[index] > q[choice]+1e-12:
            choice = index
    return choice


class GridValue:
    def __init__(self, meta, confusion, multiplier, latency_price, nodes=129):
        if nodes < 3 or nodes % 2 != 1:
            raise ValueError("An odd grid including prior 0.5 is required")
        start = time.process_time()
        self.meta, self.confusion = meta, np.asarray(confusion, float)
        self.multiplier, self.latency_price = float(multiplier), float(latency_price)
        self.grid = np.linspace(0., 1., nodes)
        self.values = np.zeros((3, meta["deadline"]+2, meta["budget"]+1, nodes))
        self.backups = 0
        for job in (1, 0):
            for tick in range(meta["deadline"]-1, -1, -1):
                for budget in range(meta["budget"]+1):
                    self.values[job, tick, budget] = np.max(self.q(job, tick, budget, self.grid), axis=0)
                    self.backups += nodes
        self.fit_cpu_seconds = time.process_time()-start

    def value(self, job, tick, budget, posterior):
        if job >= 2 or tick >= self.meta["deadline"]:
            return np.zeros_like(posterior, dtype=float)
        return np.interp(posterior, self.grid, self.values[job, tick, budget])

    def q(self, job, tick, budget, posterior):
        posterior = np.asarray(posterior, float)
        if np.any((posterior < 0) | (posterior > 1)):
            raise ValueError("Belief outside [0,1]")
        result = np.full((4,)+posterior.shape, -np.inf)
        result[0] = 0.  # STOP is a contract, never a learned nonzero output.
        legal = feasible(self.meta, job, tick, budget)
        if not legal[3]:
            return result
        cost = self.latency_price*elapsed(self.meta, tick, 1)
        if legal[1]:
            result[1] = self.value(job, tick+1, budget, posterior)-cost
        if legal[2]:
            law = likelihood(self.confusion, self.meta["reliability"][job][tick])
            p = (1-posterior[..., None])*law[0]+posterior[..., None]*law[1]
            b = posterior[..., None]*law[1]/p
            result[2] = sum(p[..., o]*self.value(job, tick+1, budget-1, b[..., o]) for o in (0, 1))
            result[2] -= self.multiplier*self.meta["price"][job][tick]+cost
        result[3] = (abs(2*posterior-1)+self.value(job+1, tick+2, budget, .5)
                     -self.latency_price*elapsed(self.meta, tick, 2))
        return result

    def record_q(self, record):
        x = record["features"]
        return self.q(int(x[0]), int(x[1]), int(x[2]), x[3])


def anchors(records, nodes):
    """Fit once per identical public schedule, independent of causal history."""
    controllers, result = {}, []
    for row in records:
        x = row["features"]
        key = tuple(x[4:])
        if key not in controllers:
            d = decode_features(x)
            controllers[key] = GridValue(d["meta"], d["confusion"], d["multiplier"], d["latency_price"], nodes)
        q = controllers[key].record_q(row)
        result.append(np.where(row["feasible"], q, 0.))
    return np.asarray(result), dict(schedules=len(controllers),
        fit_cpu_seconds=sum(c.fit_cpu_seconds for c in controllers.values()),
        backups=sum(c.backups for c in controllers.values()))


def metrics(predicted, records):
    valid = np.asarray([r["feasible"] for r in records], bool)
    target = np.asarray([r["q"] for r in records])
    action = np.asarray([select_action(q, mask) for q, mask in zip(predicted, valid)])
    best = np.max(np.where(valid, target, -np.inf), axis=1)
    regret = best-target[np.arange(len(records)), action]
    return dict(max_q_error=float(np.max(np.abs(predicted-target)[valid])),
                mean_action_regret=float(regret.mean()), max_action_regret=float(regret.max()),
                optimal_action_fraction=float(np.mean(regret < 1e-10)),
                stop_max_absolute=float(np.max(np.abs(predicted[:, 0]))))
