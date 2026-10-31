"""Bounded maximum likelihood from observed times and explicit censoring types."""

from collections import Counter
from dataclasses import dataclass
import math
import time

import numpy as np
from scipy.optimize import minimize

from .kernels import Params, log_event_likelihood, score_event


@dataclass(frozen=True)
class FitResult:
    params: Params
    loss: float
    calls: int
    iterations: int
    elapsed: float
    success: bool
    message: str
    projected_gradient_max: float


class EventObjective:
    """Average negative log likelihood, retaining the full observation law.

    Identical censored observations are grouped as a sufficient computation
    shortcut. No selection or conditional-on-hit renormalization is performed.
    """

    def __init__(self, records):
        if not records:
            raise ValueError("At least one observed contract is required")
        self.count = len(records)
        hits, grouped = [], Counter()
        for event, duration, distance in records:
            if event not in {"hit", "no_hit", "cancel", "survive"}:
                raise ValueError("Unknown observation event")
            if not all(math.isfinite(x) and x >= 0 for x in (duration, distance)):
                raise ValueError("Finite nonnegative time and distance required")
            if event == "hit" and distance > 0:
                if duration == 0:
                    raise ValueError("Positive-distance hit at zero time is impossible")
                hits.append((duration, distance))
            else:
                grouped[(event, duration, distance)] += 1
        self.hits = np.asarray(hits, dtype=float).reshape((-1, 2))
        self.grouped = grouped

    def __call__(self, values):
        params = Params(*values)
        params.validate()
        mu, sigma, rate = values
        total, score = 0.0, np.zeros(3)
        if len(self.hits):
            duration, distance = self.hits.T
            residual = distance - mu * duration
            total += float(np.sum(np.log(distance / sigma) - 0.5 * math.log(2 * math.pi)
                                  - 1.5 * np.log(duration)
                                  - residual ** 2 / (2 * sigma ** 2 * duration)
                                  - rate * duration))
            score += np.array([np.sum(residual / sigma ** 2),
                               np.sum(-1 / sigma + residual ** 2 / (sigma ** 3 * duration)),
                               -np.sum(duration)])
        for (event, duration, distance), count in self.grouped.items():
            value = log_event_likelihood(event, duration, distance, params)
            if not math.isfinite(value):
                raise ValueError("An observation has zero probability under these parameters")
            total += count * value
            score += count * score_event(event, duration, distance, params)
        return -total / self.count, -score / self.count


def fit_events(records, initial, bounds):
    """Fit three physical parameters; non-convergence remains visible to callers."""
    initial.validate()
    if len(bounds) != 3:
        raise ValueError("One compact bound interval per physical parameter is required")
    if any(not math.isfinite(x) for interval in bounds for x in interval):
        raise ValueError("Finite bounds required")
    if any(low >= high for low, high in bounds) or bounds[1][0] <= 0 or bounds[2][0] < 0:
        raise ValueError("Invalid parameter domain")
    vector = np.array([initial.mu, initial.sigma, initial.cancel_rate])
    if any(not low <= value <= high for value, (low, high) in zip(vector, bounds)):
        raise ValueError("Initialization must lie inside the declared domain")
    objective = EventObjective(records)
    started = time.perf_counter()
    result = minimize(objective, vector, jac=True, method="L-BFGS-B", bounds=bounds,
                      options={"maxiter": 200, "ftol": 1e-11, "gtol": 1e-7})
    loss, gradient = objective(result.x)
    projected = result.x - np.clip(result.x - gradient, np.array(bounds)[:, 0],
                                   np.array(bounds)[:, 1])
    return FitResult(Params(*map(float, result.x)), float(loss), int(result.nfev),
                     int(result.nit), time.perf_counter() - started, bool(result.success),
                     str(result.message), float(np.max(np.abs(projected))))
