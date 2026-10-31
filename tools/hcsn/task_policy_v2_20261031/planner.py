"""Public-model, one-additional-observation planning baseline.

This is an explicitly bounded planner, not a learned policy or the full Bellman
teacher. It permits one further observation for each remaining job. It is used
as a transparent ordinary baseline and prior for a separately fitted residual.
"""
import numpy as np

from ..task_value_factorial_20261030.task import elapsed, feasible, likelihood, outcomes


class OneRead:
    def __init__(self, meta, confusion, multiplier, latency_price):
        self.meta = meta
        self.confusion = np.asarray(confusion, float)
        self.multiplier, self.latency_price = multiplier, latency_price
        self.deadline = meta["deadline"]
        self.laws = [[likelihood(self.confusion, reliability) for reliability in row]
                     for row in meta["reliability"]]
        self.wait = np.r_[0., np.cumsum(meta["duration"])]*latency_price
        self.fire_cost = np.array([latency_price*elapsed(meta, t, 2)
                                   for t in range(self.deadline)])
        self.next_values = {}

    def next_value(self, job, tick, budget):
        if job >= 2 or tick >= self.deadline:
            return 0.
        key = (job, tick, budget > 0)
        if key not in self.next_values:
            self.next_values[key] = self.value(job, tick, budget, .5)
        return self.next_values[key]

    def read_once(self, job, tick, budget, posterior):
        probability, beliefs = outcomes(posterior, self.laws[job][tick])
        after_fire = self.next_value(job+1, tick+3, budget-1)
        terminal = np.maximum(0., np.abs(2*beliefs-1)-self.fire_cost[tick+1]+after_fire)
        cost = self.multiplier*self.meta["price"][job][tick]+self.wait[tick+1]-self.wait[tick]
        return float(probability@terminal-cost)

    def value(self, job, tick, budget, posterior):
        if job >= 2 or tick >= self.deadline:
            return 0.
        best = max(0., abs(2*posterior-1)-self.fire_cost[tick]+self.next_value(job+1, tick+2, budget))
        if budget > 0:
            for read_tick in range(tick, self.deadline-1):
                candidate = self.read_once(job, read_tick, budget, posterior)-(self.wait[read_tick]-self.wait[tick])
                best = max(best, candidate)
        return best

    def q(self, job, tick, budget, posterior):
        legal = feasible(self.meta, job, tick, budget)
        q = np.array([0., -np.inf, -np.inf, -np.inf])
        if not legal[3]:
            return q
        if legal[1]:
            q[1] = self.value(job, tick+1, budget, posterior)-(self.wait[tick+1]-self.wait[tick])
        if legal[2]:
            q[2] = self.read_once(job, tick, budget, posterior)
        q[3] = abs(2*posterior-1)-self.fire_cost[tick]+self.next_value(job+1, tick+2, budget)
        return q

    def features(self, job, tick, budget, posterior, prior=None):
        """Relative future schedules plus bounded-planning prior, no teacher calls."""
        d = self.deadline-tick
        reliability, price, duration = np.zeros((2, 10)), np.zeros((2, 10)), np.zeros(10)
        reliability[:2-job, :d] = np.asarray(self.meta["reliability"])[job:, tick:]
        price[:2-job, :d] = np.asarray(self.meta["price"])[job:, tick:]*self.multiplier
        duration[:d] = np.asarray(self.meta["duration"])[tick:]*self.latency_price
        q = self.q(job, tick, budget, posterior) if prior is None else prior
        # Hidden/observed class relabeling preserves this symmetric reward. The
        # confusion matrix is relabeled too, so asymmetric calibrations remain
        # representable. The actual owner posterior is never modified.
        canonical = self.confusion if posterior >= .5 else self.confusion[::-1, ::-1]
        return np.r_[job, d/10., budget/4., max(posterior, 1-posterior), abs(2*posterior-1),
                     canonical.flatten(), self.multiplier, self.latency_price,
                     reliability.flatten(), price.flatten(), duration,
                     np.where(np.isfinite(q), q, 0.)]
