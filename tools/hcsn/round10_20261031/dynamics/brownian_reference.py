"""Independent event-driven Brownian law with moving upper boundary.

Active state has dX=mu*dt+sigma*dW. At a real first hit X resets to a
fixed absolute location and is held there for a deterministic refractory
duration. The continuous piecewise-linear boundary may move during the hold.
No spatial mesh, time stepping, finite generator or production FPT code is used.
"""

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True)
class Case:
    name: str
    times: tuple
    boundaries: tuple
    mu: float
    sigma: float
    reset: float
    refractory: float
    initial: float

    def validate(self):
        values = (*self.times, *self.boundaries, self.mu, self.sigma,
                  self.reset, self.refractory, self.initial)
        if not all(math.isfinite(x) for x in values):
            raise ValueError("Finite parameters required")
        if len(self.times) != len(self.boundaries) or len(self.times) < 2:
            raise ValueError("Paired boundary knots required")
        if self.times[0] != 0 or any(b <= a for a, b in zip(self.times, self.times[1:])):
            raise ValueError("Strictly increasing times starting at zero required")
        if self.sigma <= 0 or self.refractory <= 0:
            raise ValueError("Positive diffusion and fixed refractory duration required")
        if self.reset >= min(self.boundaries) or self.initial >= self.boundaries[0]:
            raise ValueError("Reset and initial state must remain eligible below the boundary")

    def boundary(self, t):
        return float(np.interp(t, self.times, self.boundaries))


def first_hit_time(gap, relative_drift, sigma, rng):
    """Lower-gap first hit: inverse Gaussian, with its exact defective mass.

    For positive relative drift, condition on ever hitting, then reverse the
    drift. Zero drift has the Levy representation gap**2/(sigma**2 Z**2).
    """
    if gap <= 0:
        return 0.
    if relative_drift > 0:
        if rng.random() > math.exp(-2*relative_drift*gap/(sigma*sigma)):
            return math.inf
    if relative_drift == 0:
        z = rng.normal()
        return math.inf if z == 0 else (gap/(sigma*z))**2
    return float(rng.wald(gap/abs(relative_drift), (gap/sigma)**2))


def surviving_endpoint(gap, relative_drift, sigma, duration, rng):
    """Sample the killed Gaussian conditioned on no hit before duration.

    The free endpoint is accepted with Brownian-bridge survival probability
    1-exp(-2*gap*y/(sigma**2*duration)). This keeps the true conditional
    survivor distribution; no Gaussian or mean replacement is made.
    """
    variance = sigma*sigma*duration
    mean, scale = gap+relative_drift*duration, math.sqrt(variance)
    for proposals in range(1, 1_000_001):
        y = float(rng.normal(mean, scale))
        if y > 0 and rng.random() < -math.expm1(-2*gap*y/variance):
            return y, proposals
    raise RuntimeError("Conditional survivor rejection budget exhausted")


def sample(case, samples, seed):
    case.validate()
    rng = np.random.default_rng(seed)
    end = case.times[-1]
    counts = np.zeros(samples, dtype=np.int16)
    first = np.full(samples, np.inf)
    position = np.empty(samples)
    refractory = np.zeros(samples, dtype=bool)
    traces, proposals = [], 0
    for index in range(samples):
        t, x, events = 0., case.initial, []
        while t < end:
            segment = int(np.searchsorted(case.times, t, side="right"))-1
            duration = case.times[segment+1]-t
            slope = ((case.boundaries[segment+1]-case.boundaries[segment]) /
                     (case.times[segment+1]-case.times[segment]))
            gap = case.boundary(t)-x
            wait = first_hit_time(gap, slope-case.mu, case.sigma, rng)
            if wait <= duration:
                hit = t+wait
                if hit <= t:
                    raise ArithmeticError("Event time cannot advance represented clock")
                counts[index] += 1
                if not events:
                    first[index] = hit
                release = hit+case.refractory
                events.append(dict(hit=hit, release=release,
                                   boundary=case.boundary(hit), absolute_reset=case.reset))
                x = case.reset
                if release > end:
                    refractory[index] = True
                    t = end
                else:
                    t = release
            else:
                y, draws = surviving_endpoint(gap, slope-case.mu, case.sigma, duration, rng)
                proposals += draws
                t = case.times[segment+1]
                x = case.boundary(t)-y
        position[index] = x
        if index < 12:
            traces.append(dict(index=index, events=events, final_position=x,
                               final_refractory=bool(refractory[index])))
    max_events = math.floor(end/case.refractory)+1
    if int(counts.max()) > max_events:
        raise AssertionError("Fixed refractory duration event-count bound violated")
    return dict(counts=counts, first=first, position=position, refractory=refractory,
                traces=traces, survivor_proposals=proposals, seed=seed,
                bit_generator=type(rng.bit_generator).__name__)


def statistics(raw):
    arrays = dict(events=raw["counts"].astype(float), ever=(raw["counts"] > 0).astype(float),
                  refractory=raw["refractory"].astype(float), mean=raw["position"],
                  second_moment=raw["position"]**2)
    metrics = {key: dict(value=float(x.mean()), standard_error=float(x.std(ddof=1)/math.sqrt(len(x))))
               for key, x in arrays.items()}
    metrics["variance"] = dict(value=float(raw["position"].var(ddof=0)),
        standard_error=float(((raw["position"]-raw["position"].mean())**2).std(ddof=1)/math.sqrt(len(raw["position"]))))
    return metrics
