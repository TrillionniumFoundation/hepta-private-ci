"""Finite deadline/budget renewal values and actual sampled executions.

The contract has a constant threshold for an entire episode, positive drift,
zero reset voltage, independent global cancellation, and a separate discount.
The planner is restricted to this policy family; it is not a finite-horizon
solution of the unrestricted impulse-control problem.
"""

from dataclasses import asdict, dataclass
import math

import numpy as np

from experiments.first_passage_cell.kernels import (
    first_passage, first_passage_gradients,
)


@dataclass(frozen=True)
class ThresholdContext:
    mu: float
    sigma: float
    cancel_rate: float
    cost: float
    horizon: float
    budget: int
    refractory: float
    discount: float
    stratum: str = "nominal"

    def validate(self):
        values = (self.mu, self.sigma, self.cancel_rate, self.cost, self.horizon,
                  self.budget, self.refractory, self.discount)
        if (not np.isfinite(values).all() or self.mu <= 0 or self.sigma <= 0
                or self.cancel_rate < 0 or self.horizon <= 0 or self.budget < 1
                or int(self.budget) != self.budget or self.refractory < 0
                or self.discount < 0):
            raise ValueError("Invalid positive-drift renewal context")


@dataclass
class EvaluationCost:
    calls: int = 0
    context_evaluations: int = 0
    first_passage_terms: int = 0
    gradient_terms: int = 0


def make_contexts(protocol, split, fit_seed):
    """Generate only the requested split using its registered named stream."""
    rng = np.random.default_rng(np.random.SeedSequence([
        protocol["split_seed_bases"][split], fit_seed]))
    count = protocol["contexts_per_fit_seed"][split]
    strata = protocol["strata"]
    contexts = []
    for index in range(count):
        stratum = strata[index % len(strata)]
        spec = dict(protocol["nominal_distribution"])
        spec.update(protocol["stratum_overrides"].get(stratum, {}))
        contexts.append(ThresholdContext(
            mu=float(rng.uniform(*spec["mu_uniform"])),
            sigma=float(rng.uniform(*spec["sigma_uniform"])),
            cancel_rate=float(rng.uniform(*spec["cancel_rate_uniform"])),
            cost=float(rng.uniform(*spec["cost_uniform"])),
            horizon=float(rng.uniform(*spec["horizon_uniform"])),
            budget=int(rng.integers(spec["budget_integers_inclusive"][0],
                                    spec["budget_integers_inclusive"][1]+1)),
            refractory=float(rng.uniform(*spec["refractory_uniform"])),
            discount=float(spec["discount"]), stratum=stratum))
    return contexts


def renewal_value(thresholds, contexts, *, derivative=False, counter=None):
    """J and optional dJ/db; threshold zero is the explicit STOP action.

    The n-th passage time is distributed as a first passage over n*b plus
    (n-1)*refractory, by independent reset increments of Brownian motion.
    Old kernels use distance with *lower* drift, so their drift is -ctx.mu.
    """
    if not contexts:
        raise ValueError("At least one context is required")
    for context in contexts:
        context.validate()
    b = np.broadcast_to(np.asarray(thresholds, dtype=float), (len(contexts),))
    if not np.isfinite(b).all() or np.any(b < 0):
        raise ValueError("Thresholds must be finite and nonnegative")
    mu, sigma, rate, cost, horizon, budget, ref, discount = np.array([
        [c.mu, c.sigma, c.cancel_rate, c.cost, c.horizon, c.budget,
         c.refractory, c.discount] for c in contexts]).T
    n = np.arange(1, int(budget.max())+1)[None, :]
    hold = (n-1)*ref[:, None]
    remaining = horizon[:, None]-hold
    valid = (n <= budget[:, None]) & (remaining > 0) & (b[:, None] > 0)
    distance = np.broadcast_to(n*np.where(b > 0, b, 1)[:, None], valid.shape)
    time = np.where(valid, remaining, 1.0)
    q = (rate+discount)[:, None]
    weights = np.exp(-q*hold)*valid
    law = first_passage(distance, -mu[:, None], sigma[:, None], time, q)
    count = np.sum(weights*law["H"], axis=1)
    value = (b-cost)*count
    if counter is not None:
        counter.calls += 1
        counter.context_evaluations += len(contexts)
        counter.first_passage_terms += int(valid.size)
    if not derivative:
        return value
    gradient = first_passage_gradients(
        distance, -mu[:, None], sigma[:, None], time, q)["H"]["x"]
    result = count+(b-cost)*np.sum(weights*n*gradient, axis=1)
    result = np.where(b == 0, 0.0, result)
    if counter is not None:
        # first_passage_gradients also calls first_passage internally. Count
        # every evaluated placeholder term, including inactive budget slots.
        counter.first_passage_terms += int(valid.size)
        counter.gradient_terms += int(valid.size)
    return value, result


def named_noise(context, *, seed_base, fit_seed, context_index, repeats):
    rng = np.random.default_rng(np.random.SeedSequence([
        seed_base, fit_seed, context_index]))
    return {
        "normal": rng.standard_normal((repeats, context.budget)),
        "branch": rng.random((repeats, context.budget)),
        "cancellation": rng.random(repeats),
    }


def execute(threshold, context, noise):
    """Execute a finite episode on inverse-Gaussian passage-time samples.

    Same noise inputs across arms couple valid marginal passage distributions;
    they are not a reconstruction of one shared continuous Brownian path.
    No event after cancellation, timeout or exhausted budget earns utility.
    """
    context.validate()
    if not math.isfinite(threshold) or threshold < 0:
        raise ValueError("Expected finite threshold >= 0")
    z, u = np.asarray(noise["normal"]), np.asarray(noise["branch"])
    cancel_u = np.asarray(noise["cancellation"])
    if (z.shape != u.shape or z.ndim != 2 or z.shape[1] != context.budget
            or cancel_u.shape != (z.shape[0],) or not np.isfinite(z).all()
            or not np.isfinite(u).all() or not np.isfinite(cancel_u).all()
            or np.any((u < 0) | (u >= 1))
            or np.any((cancel_u < 0) | (cancel_u >= 1))):
        raise ValueError("Invalid named passage-time noise")
    repeats = z.shape[0]
    if threshold == 0:
        return {"utility": np.zeros(repeats), "hits": np.zeros(repeats, int),
                "terminal": np.full(repeats, "STOP"),
                "last_hit_time": np.full(repeats, np.nan)}
    mean = threshold/context.mu
    shape = threshold**2/context.sigma**2
    s = mean*z*z/(2*shape)
    small = mean/(1+s+np.sqrt(s*(2+s)))
    passage = np.where(u <= mean/(mean+small), small, mean**2/small)
    times = np.cumsum(passage, axis=1)
    times += np.arange(context.budget)[None, :]*context.refractory
    cancellation = np.full(repeats, np.inf)
    if context.cancel_rate > 0:
        cancellation = -np.log1p(-cancel_u)/context.cancel_rate
    allowed = ((times < cancellation[:, None])
               & (times <= context.horizon))
    counts = allowed.sum(axis=1)
    utility = np.sum(np.exp(-context.discount*times)*allowed, axis=1)
    utility *= threshold-context.cost
    terminal = np.where(cancellation <= context.horizon, "CANCEL", "TIMEOUT")
    terminal = np.where(counts == context.budget, "BUDGET", terminal)
    last = np.max(np.where(allowed, times, -np.inf), axis=1)
    return {"utility": utility, "hits": counts, "terminal": terminal,
            "last_hit_time": np.where(counts > 0, last, np.nan)}


def context_dicts(contexts):
    return [asdict(context) for context in contexts]
