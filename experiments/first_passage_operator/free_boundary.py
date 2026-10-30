"""Globally verified natural-spike boundary in a scoped regenerative model.

While active, dX=mu dt+sigma dW on the whole real line. Choosing a spike earns
X-c, resets to r, and holds there for a mandatory duration a. Reward during
refractoriness is zero. q>0 discounts actual time. The scope c>=r excludes the
immediate-firing degeneracy. No external maintenance decision is present.
"""

from dataclasses import dataclass
import math

import numpy as np
from scipy.optimize import brentq
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import spsolve


@dataclass(frozen=True)
class NaturalSpikeSpec:
    mu: float
    sigma: float
    reset: float
    refractory: float
    discount: float
    spike_cost: float

    def __post_init__(self):
        if not all(math.isfinite(v) for v in vars(self).values()):
            raise ValueError("finite natural-spike coefficients required")
        if (self.sigma <= 0 or self.refractory <= 0 or self.discount <= 0
                or self.spike_cost < self.reset):
            raise ValueError("sigma,a,q>0 and spike_cost>=reset required")

    @property
    def exponent(self):
        root = math.hypot(self.mu, math.sqrt(2 * self.discount) * self.sigma)
        return (2 * self.discount / (root + self.mu) if self.mu >= 0
                else (root - self.mu) / (self.sigma * self.sigma))


def solve_boundary(spec):
    """Solve value matching and smooth fit, and return implicit derivatives."""
    lam = spec.exponent
    beta = math.exp(-spec.discount * spec.refractory)
    c, r = spec.spike_cost, spec.reset
    function = lambda b: lam * (b - c) + beta * math.exp(-lam * (b - r)) - 1
    boundary = brentq(function, c, c + 1 / lam, xtol=1e-14, rtol=1e-14)
    reset_value = math.exp(-lam * (boundary - r)) / lam
    recycle = beta * math.exp(-lam * (boundary - r))
    denominator = lam * (1 - recycle)
    partial_lambda = boundary - c - (boundary - r) * recycle
    root = spec.mu + spec.sigma * spec.sigma * lam
    gradients = {
        "mu": partial_lambda * lam / root / denominator,
        "sigma": partial_lambda * spec.sigma * lam * lam / root / denominator,
        "discount": -(partial_lambda / root - spec.refractory * recycle) / denominator,
        "reset": -recycle / (1 - recycle),
        "spike_cost": 1 / (1 - recycle),
        "refractory": spec.discount * recycle / denominator,
    }
    return {"boundary": boundary, "reset_value": reset_value, "lambda": lam,
            "beta": beta, "boundary_gradients": gradients,
            "value_matching_residual": function(boundary) / lam,
            "smooth_fit_residual": lam * (boundary - c + beta * reset_value) - 1,
            "stopping_generator_at_boundary": -0.5 * spec.sigma * spec.sigma * lam}


def optimal_value(spec, state, *, pending_refractory=0.0):
    """The verified value over all admissible nonanticipating spike policies."""
    result = solve_boundary(spec)
    x = np.asarray(state, float)
    if not np.isfinite(x).all() or not math.isfinite(pending_refractory) or pending_refractory < 0:
        raise ValueError("finite state and nonnegative refractory time required")
    if pending_refractory > spec.refractory:
        raise ValueError("remaining refractory exceeds the mandatory duration")
    if pending_refractory:
        if not np.all(x == spec.reset):
            raise ValueError("refractory state must equal reset")
        return np.full_like(x, math.exp(-spec.discount * pending_refractory) * result["reset_value"])
    b, lam, c0 = result["boundary"], result["lambda"], result["reset_value"]
    return np.where(x < b, np.exp(np.minimum(lam * (x - b), 0.0)) / lam,
                    x - spec.spike_cost + result["beta"] * c0)


def threshold_value(spec, threshold, state=None):
    """Renewal value of a given first-passage spike threshold, independently."""
    b, x = float(threshold), spec.reset if state is None else float(state)
    if not math.isfinite(b) or not math.isfinite(x) or b <= spec.reset:
        raise ValueError("finite threshold above reset required")
    lam = spec.exponent
    hit = math.exp(-lam * (b - spec.reset))
    beta = math.exp(-spec.discount * spec.refractory)
    reset_value = (b - spec.spike_cost) * hit / (-math.expm1(-lam * (b - spec.reset)
                                                                          - spec.discount * spec.refractory))
    at_spike = (x if x >= b else b) - spec.spike_cost + beta * reset_value
    return at_spike if x >= b else math.exp(-lam * (b - x)) * at_spike


def solve_grid_qvi(spec, *, spacing=0.01, lower=None, upper=None, maximum_iterations=200):
    """Independent monotone finite-difference Howard iteration.

    No analytic boundary is used in the solver. Zero is imposed at a remote
    negative endpoint; the upper endpoint must be an immediate-spike state.
    Grid and truncation errors remain explicit and are checked by refinement.
    """
    if not math.isfinite(spacing) or spacing <= 0:
        raise ValueError("positive spacing required")
    lower = spec.reset - 12.0 if lower is None else float(lower)
    upper = spec.spike_cost + 12.0 if upper is None else float(upper)
    left_count = int(math.ceil((spec.reset - lower) / spacing))
    right_count = int(math.ceil((upper - spec.reset) / spacing))
    if left_count < 2 or right_count < 2 or left_count + right_count > 50000:
        raise ValueError("bounded grid straddling reset required")
    x = spec.reset + np.arange(-left_count, right_count + 1) * spacing
    reset_index, count = left_count, len(x)
    diffusion = 0.5 * spec.sigma * spec.sigma / spacing ** 2
    # Central drift is second order whenever it keeps generator rates positive.
    # Coarser grids use monotone upwind rates instead of negative probabilities.
    if diffusion >= abs(spec.mu)/(2*spacing):
        down = diffusion-spec.mu/(2*spacing)
        up = diffusion+spec.mu/(2*spacing)
    else:
        down = diffusion+max(-spec.mu, 0.0)/spacing
        up = diffusion+max(spec.mu, 0.0)/spacing
    rate = spec.discount + down + up
    beta = math.exp(-spec.discount * spec.refractory)
    stop = x > spec.spike_cost + 1.0
    stop[0], stop[-1] = False, True
    value = np.zeros(count)
    for iteration in range(maximum_iterations):
        matrix = lil_matrix((count, count))
        rhs = np.zeros(count)
        matrix[0, 0] = 1.0
        for i in range(1, count):
            if stop[i]:
                matrix[i, i] = 1.0
                matrix[i, reset_index] -= beta
                rhs[i] = x[i] - spec.spike_cost
            else:
                matrix[i, i] = rate
                matrix[i, i-1] = -down
                matrix[i, i+1] = -up
        value = spsolve(matrix.tocsc(), rhs)
        wait = (down * value[:-2] + up * value[2:]) / rate
        fire = x[1:-1] - spec.spike_cost + beta * value[reset_index]
        updated = stop.copy()
        updated[1:-1] = fire >= wait + 1e-13
        if np.array_equal(updated, stop):
            break
        stop = updated
    else:
        raise ArithmeticError("Howard policy iteration did not converge")
    residual = np.maximum(wait - value[1:-1], fire - value[1:-1])
    indices = np.flatnonzero(stop)
    if len(indices) == 0 or not np.all(stop[indices[0]:]):
        raise ArithmeticError("computed stopping set is not an upper ray")
    return {"state": x, "value": value, "stop": stop, "boundary": float(x[indices[0]]),
            "reset_value": float(value[reset_index]), "iterations": iteration + 1,
            "bellman_residual": float(np.max(np.abs(residual))), "spacing": spacing,
            "lower": float(x[0]), "upper": float(x[-1])}
