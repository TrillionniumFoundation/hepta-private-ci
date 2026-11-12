"""Continuous reflecting-diffusion reference for the finite QVI fixture.

Solves an interior intervention threshold for g(x)=x, a fixed reset and a
deterministic zero-reward delay. This is an independent ODE calculation, not
the HCSN half-line process, a neural boundary, or an interval certificate.
"""

from dataclasses import dataclass
import math

import numpy as np

from .oracle import Problem


@dataclass(frozen=True)
class BoundarySolution:
    problem: Problem
    boundary: float
    positive_root: float
    negative_root: float
    positive_coefficient: float
    negative_coefficient: float
    root_bracket: tuple = ()

    def continuation(self, points, derivative=0):
        x = np.asarray(points, dtype=float)
        p, a, c = self.problem, self.positive_coefficient, self.negative_coefficient
        rp, rm, b = self.positive_root, self.negative_root, self.boundary
        ep, em = np.exp(rp * (x - p.upper)), np.exp(rm * (x - b))
        if derivative == 0:
            return x / p.discount + p.mu / p.discount**2 + a * ep + c * em
        if derivative == 1:
            return 1 / p.discount + a * rp * ep + c * rm * em
        if derivative == 2:
            return a * rp**2 * ep + c * rm**2 * em
        raise ValueError("only value and first two spatial derivatives are supported")

    def value(self, points):
        x = np.asarray(points, dtype=float)
        if not np.isfinite(x).all() or np.any((x < 0) | (x > self.problem.upper)):
            raise ValueError("evaluation points must lie in the reflecting domain")
        return self.continuation(np.maximum(x, self.boundary))

    def residuals(self):
        p, b = self.problem, self.boundary
        x = np.linspace(b, p.upper, 257)
        value = self.continuation(x)
        slope = self.continuation(x, derivative=1)
        curvature = self.continuation(x, derivative=2)
        target = -p.cost + math.exp(-p.discount * p.delay) * self.value(p.reset)
        return {
            "value_matching": float(self.value(b) - target),
            "smooth_pasting": float(self.continuation(b, derivative=1)),
            "upper_reflection": float(self.continuation(p.upper, derivative=1)),
            "maximum_continuation_ode_residual": float(np.max(np.abs(
                0.5 * p.sigma**2 * curvature + p.mu * slope - p.discount * value + x))),
            "maximum_intervention_generator_residual": float(b - p.discount * self.value(b)),
            "minimum_sampled_continuation_slope": float(np.min(slope)),
            "minimum_sampled_continuation_gap": float(np.min(value - target)),
            "sampled_continuation_points": len(x),
        }

    def cost_derivative(self):
        """Implicit derivative of the three boundary equations, in this regime."""
        if not self.root_bracket:
            raise ValueError("cost derivative requires a solved interior free boundary")
        p, b = self.problem, self.boundary
        rp, rm = self.positive_root, self.negative_root
        a, c = self.positive_coefficient, self.negative_coefficient
        eta = math.exp(-p.discount * p.delay)
        eb = math.exp(rp * (b - p.upper))
        er = math.exp(rp * (p.reset - p.upper))
        hl = math.exp(rm * (p.upper - b))
        hr = math.exp(rm * (p.reset - b))
        jacobian = np.array([
            [rp, rm * hl, -c * rm**2 * hl],
            [rp * eb, rm, a * rp**2 * eb],
            [eb - eta * er, 1 - eta * hr,
             1 / p.discount + a * rp * eb + eta * c * rm * hr],
        ])
        da, dc, db = np.linalg.solve(jacobian, [0, 0, -1])
        x = max(p.initial, b)
        value_derivative = (
            da * math.exp(rp * (x - p.upper))
            + (dc - c * rm * db) * math.exp(rm * (x - b))
        )
        return {
            "boundary": float(db), "initial_value": float(value_derivative),
            "coefficient_direction": [float(da), float(dc)],
            "equation_jacobian": jacobian.tolist(),
            "unscaled_jacobian_condition_inf": float(np.linalg.cond(jacobian, np.inf)),
            "scope": "Interior threshold, fixed reset and delay; mixed-unit unscaled condition estimate.",
        }


def _rates(problem):
    p = problem
    numbers = (p.upper, p.mu, p.sigma, p.discount, p.reset, p.delay, p.cost, p.initial)
    if any(isinstance(v, bool) or not math.isfinite(v) for v in numbers):
        raise ValueError("finite real problem parameters required")
    if (min(p.upper, p.sigma, p.discount, p.delay, p.cost) <= 0
            or not 0 < p.reset < p.upper or not 0 <= p.initial <= p.upper):
        raise ValueError("positive coefficients, interior reset and in-domain initial state required")
    discriminant = math.hypot(p.mu, math.sqrt(2 * p.discount) * p.sigma)
    positive = (2 * p.discount / (discriminant + p.mu) if p.mu >= 0
                else (discriminant - p.mu) / p.sigma**2)
    negative = (-2 * p.discount / (discriminant - p.mu) if p.mu <= 0
                else -(discriminant + p.mu) / p.sigma**2)
    if not 0 < positive < math.inf or not -math.inf < negative < 0:
        raise FloatingPointError("characteristic roots are unresolved")
    return positive, negative


def fixed_threshold(problem, boundary):
    """Evaluate a fixed interior threshold; smooth pasting is not imposed."""
    rp, rm = _rates(problem)
    p, b = problem, float(boundary)
    if not math.isfinite(b) or not 0 < b < p.reset:
        raise ValueError("a fixed threshold strictly between zero and reset is required")
    eta = math.exp(-p.discount * p.delay)
    system = np.array([
        [rp, rm * math.exp(rm * (p.upper - b))],
        [math.exp(rp * (b - p.upper)) - eta * math.exp(rp * (p.reset - p.upper)),
         1 - eta * math.exp(rm * (p.reset - b))],
    ])
    particular = lambda x: x / p.discount + p.mu / p.discount**2
    a, c = np.linalg.solve(system, [-1 / p.discount,
        -p.cost + eta * particular(p.reset) - particular(b)])
    if not np.isfinite([a, c]).all():
        raise FloatingPointError("fixed-policy coefficients are unresolved")
    return BoundarySolution(p, b, rp, rm, float(a), float(c))


def solve_boundary(problem=Problem()):
    """Find one interior root; reject unsupported no-intervention regimes."""
    rp, rm = _rates(problem)
    p = problem

    def candidate(b):
        system = np.array([
            [rp, rm * math.exp(rm * (p.upper - b))],
            [rp * math.exp(rp * (b - p.upper)), rm],
        ])
        a, c = np.linalg.solve(system, [-1 / p.discount, -1 / p.discount])
        result = BoundarySolution(p, b, rp, rm, float(a), float(c))
        residual = (float(result.value(b)) + p.cost
                    - math.exp(-p.discount * p.delay) * float(result.value(p.reset)))
        if not math.isfinite(residual):
            raise FloatingPointError("boundary equation is unresolved")
        return residual, result

    lower, upper = 0.0, p.reset
    left, _ = candidate(lower)
    right, _ = candidate(upper)
    if left == 0 or right == 0 or math.copysign(1, left) == math.copysign(1, right):
        raise ValueError("no bracketed interior threshold; endpoint regimes are outside this solver")
    for _ in range(128):
        middle = (lower + upper) / 2
        residual, result = candidate(middle)
        if math.copysign(1, residual) == math.copysign(1, left):
            lower, left = middle, residual
        else:
            upper = middle
        if upper - lower <= 1e-13 * max(1, p.upper):
            _, result = candidate((lower + upper) / 2)
            break
    else:
        raise RuntimeError("boundary bisection exceeded its fixed budget")
    result = BoundarySolution(p, result.boundary, rp, rm,
                              result.positive_coefficient, result.negative_coefficient,
                              (lower, upper))
    if abs(result.residuals()["value_matching"]) > 1e-10:
        raise FloatingPointError("value-matching residual exceeded the fixed limit")
    return result
