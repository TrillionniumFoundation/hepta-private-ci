"""Optional, independent faster root for the frozen scalar regenerative oracle.

The mathematical problem and six-parameter first-order implicit derivative
are unchanged. This module is NOT used by the frozen study. Ordinary tensor
residual diagnostics are not formal interval arithmetic: callers needing a
rigorous binary64-input certificate can request ``rational_certificate``.
That independent, exact-rational check deliberately sits outside timing of the
fast path. No claim of second-order implicit differentiation is made.
"""

from contextlib import contextmanager
from fractions import Fraction
import math

import torch

from .oracle_torch import kappa


EPS = torch.finfo(torch.float64).eps


def _residual(a, y):
    """f=y+expm1(-a-y), with a cancellation-free small-z evaluation."""
    z = a + y
    q = torch.exp(-z)
    derivative = -torch.expm1(-z)
    residual = y - derivative
    small = z < 0.125
    if bool(small.any()):
        # g(z)=z+exp(-z)-1. Alternating Taylor through z^14; the
        # omitted term is bounded by z^15/15! for 0<=z<=1/8.
        w = z[small]
        polynomial = torch.full_like(w, 1 / math.factorial(14))
        for degree in range(13, 1, -1):
            polynomial = polynomial * w + (-1.0) ** degree / math.factorial(degree)
        stable = w.square() * polynomial - a[small]
        residual = residual.clone()
        residual[small] = stable
    return residual, derivative, q


def _advance(a, y, lower, upper, use_halley):
    residual, derivative, q = _residual(a, y)
    lower = torch.where(residual < 0, y, lower)
    upper = torch.where(residual > 0, y, upper)
    if use_halley:
        denominator = 2 * derivative.square() - residual * q
        proposed = y - 2 * residual * derivative / denominator
    else:
        proposed = y - residual / derivative
    admissible = torch.isfinite(proposed) & (proposed >= lower) & (proposed <= upper)
    proposed = torch.where(admissible, proposed, lower + (upper - lower) / 2)
    return torch.where(residual == 0, y, proposed), lower, upper


@torch.no_grad()
def dimensionless_root(a, return_diagnostics=False, fast_steps=3, max_fallback_steps=80):
    """Solve y+expm1(-a-y)=0 for finite a>0, using float64 internally.

    The initial analytic interval is
      2*sqrt(a)/(sqrt(a+2)+sqrt(a)) <= y <= min(sqrt(2*a), 1).
    Three safeguarded Halley iterations are followed by residual-driven
    safeguarded Newton/bisection only for unresolved entries. Endpoint 1 is
    accepted when floating-point rounding makes it the best answer.

    Diagnostics describe floating-point computations, not a formally rounded
    interval library. ``rational_certificate`` supplies an independent rigorous
    enclosure for any returned scalar and the exact binary64 a supplied.
    """
    if not isinstance(a, torch.Tensor) or not a.is_floating_point():
        raise TypeError("a must be a floating-point torch Tensor")
    if not bool(torch.isfinite(a).all()) or not bool((a > 0).all()):
        raise ValueError("Require finite a>0")
    if fast_steps < 0 or max_fallback_steps < 0:
        raise ValueError("Iteration limits must be nonnegative")
    a = a.to(torch.float64)
    square = a.sqrt()
    lower = 2 * square / ((a + 2).sqrt() + square)
    # A few ulps of padding avoid excluding a correctly rounded endpoint.
    lower = (lower * (1 - 8 * EPS)).clamp_min(0)
    upper = ((square * math.sqrt(2)) * (1 + 4 * EPS)).clamp_max(1)
    y = lower + (upper - lower) / 2
    for _ in range(fast_steps):
        y, lower, upper = _advance(a, y, lower, upper, True)
    residual, derivative, q = _residual(a, y)
    tolerance = 8 * EPS * y.abs()
    minimum_derivative = (a + lower) / (1 + a + lower)
    estimated_error = residual.abs() / minimum_derivative
    unresolved = estimated_error > tolerance
    fallback_elements = int(unresolved.sum().item())
    fallback_iterations = 0
    if fallback_elements:
        aa, yy, ll, uu = (v[unresolved].clone() for v in (a, y, lower, upper))
        for iteration in range(max_fallback_steps):
            yy, ll, uu = _advance(aa, yy, ll, uu, False)
            ff, _, _ = _residual(aa, yy)
            mm = (aa + ll) / (1 + aa + ll)
            fallback_iterations = iteration + 1
            if bool((ff.abs() <= mm * (8 * EPS * yy.abs())).all()):
                break
        y[unresolved], lower[unresolved], upper[unresolved] = yy, ll, uu
        residual, derivative, q = _residual(a, y)
        minimum_derivative = (a + lower) / (1 + a + lower)
        estimated_error = residual.abs() / minimum_derivative
    converged = estimated_error <= 8 * EPS * y.abs()
    if not bool(converged.all()):
        raise RuntimeError("Fast root did not meet its floating-point residual criterion")
    if not return_diagnostics:
        return y
    return y, dict(lower=lower, upper=upper, residual=residual,
                   minimum_derivative=minimum_derivative,
                   residual_error_estimate=estimated_error,
                   dy_da=q / derivative,
                   relative_condition_number=a * q / (y * derivative),
                   converged=converged, fast_steps=fast_steps,
                   fallback_elements=fallback_elements,
                   fallback_iterations=fallback_iterations,
                   diagnostic_scope="float64 safeguarded residual; use rational_certificate for a rigorous enclosure")


class _ImplicitFastBoundary(torch.autograd.Function):
    @staticmethod
    def forward(ctx, mu, sigma, rho, K, r, tau):
        arguments = (mu, sigma, rho, K, r, tau)
        if not all(t.is_floating_point() and bool(torch.isfinite(t).all()) for t in arguments):
            raise ValueError("Boundary parameters must be finite floating-point tensors")
        if not ((sigma > 0).all() and (rho > 0).all() and (r < K).all() and (tau >= 0).all()):
            raise ValueError("Require sigma>0, rho>0, r<K, tau>=0")
        ctx.input_dtypes = tuple(t.dtype for t in arguments)
        mu, sigma, rho, K, r, tau = [t.to(torch.float64) for t in arguments]
        kap = kappa(mu, sigma, rho)
        a = rho * tau + kap * (K - r)
        y = dimensionless_root(a)
        q = torch.exp(-a - y)
        one_minus_q = -torch.expm1(-a - y)
        ctx.save_for_backward(mu, sigma, rho, K, r, tau, kap, y, q, one_minus_q)
        return (K + y / kap).to(ctx.input_dtypes[0])

    @staticmethod
    def backward(ctx, grad_output):
        mu, sigma, rho, K, r, tau, kap, y, q, one_minus_q = ctx.saved_tensors
        omega = torch.sqrt(mu.square() + 2 * rho * sigma.square())
        jacobian = kap * one_minus_q
        # Algebraically identical to displacement-q*(displacement+K-r),
        # without subtracting two O(sqrt(a)) quantities near a=0.
        sensitivity = (y * one_minus_q) / kap - q * (K - r)
        kap_mu, kap_sigma, kap_rho = -kap / omega, -sigma * kap.square() / omega, 1 / omega
        derivatives = (-sensitivity * kap_mu / jacobian,
                       -sensitivity * kap_sigma / jacobian,
                       (-sensitivity * kap_rho + tau * q) / jacobian,
                       kap / jacobian, -kap * q / jacobian, rho * q / jacobian)
        return tuple((grad_output.to(torch.float64) * value).to(dtype)
                     for value, dtype in zip(derivatives, ctx.input_dtypes, strict=True))


def free_boundary(mu, sigma, rho, K, r, tau):
    """Drop-in six-tensor, broadcast-compatible FIRST-ORDER boundary function."""
    return _ImplicitFastBoundary.apply(*torch.broadcast_tensors(mu, sigma, rho, K, r, tau))


def _exponential_interval(z, width, max_terms=512):
    """Exact rational bounds on exp(-z), using the positive exponential series.

    S_N <= exp(z) <= S_N+t_(N+1)/(1-z/(N+2)) once N+2>z.
    Reciprocals reverse the bounds. For very large z the upper bound 1/S_N
    alone rapidly falls below width, so no enormous range reduction is used.
    """
    if z < 0 or width <= 0:
        raise ValueError("Require z>=0 and positive rational width")
    term = total = Fraction(1)
    for n in range(max_terms + 1):
        upper = 1 / total
        lower = Fraction(0)
        if Fraction(n + 2) > z:
            next_term = term * z / (n + 1)
            remainder = next_term / (1 - z / (n + 2))
            lower = 1 / (total + remainder)
        if upper - lower <= width:
            return lower, upper, n
        term *= z / (n + 1)
        total += term
    raise RuntimeError("Exact rational exponential certificate reached its term cap")


def _outward_float(value, direction):
    number = float(value)
    exact = Fraction.from_float(number)
    if (direction > 0 and exact < value) or (direction < 0 and exact > value):
        number = math.nextafter(number, math.inf if direction > 0 else -math.inf)
    return number


def rational_certificate(a, y, relative_radius=32 * EPS, max_expansions=12):
    """Prove a root enclosure for exact finite binary64 inputs using Fractions.

    This is intentionally an expensive independent certification layer. Every
    arithmetic operation used to establish signs is an exact rational one;
    exp bounds follow a convergent series with a proven geometric tail. The
    certificate concerns y(a), not rounding in physical a construction or in
    the final b=K+y/kappa. The function raises if a narrow certificate fails.
    """
    a, y = float(a), float(y)
    if not (math.isfinite(a) and math.isfinite(y) and a > 0 and 0 < y <= 1):
        raise ValueError("Require finite a>0 and 0<y<=1")
    aa, yy = Fraction.from_float(a), Fraction.from_float(y)
    radius = Fraction.from_float(relative_radius) * yy
    term_counts = []
    for expansion in range(max_expansions + 1):
        lower, upper = max(Fraction(0), yy - radius), min(Fraction(1), yy + radius)
        minimum_derivative = (aa + lower) / (1 + aa + lower)
        exp_width = radius * minimum_derivative / 64
        ell_low, ell_high, nl = _exponential_interval(aa + lower, exp_width)
        ehi_low, ehi_high, nu = _exponential_interval(aa + upper, exp_width)
        term_counts.extend((nl, nu))
        f_lower_upper = lower - 1 + ell_high
        f_upper_lower = upper - 1 + ehi_low
        if f_lower_upper <= 0 and f_upper_lower >= 0:
            center_low, center_high, nc = _exponential_interval(aa + yy, exp_width)
            term_counts.append(nc)
            residual_bound = max(abs(yy - 1 + center_low), abs(yy - 1 + center_high))
            error_bound = min(max(yy - lower, upper - yy), residual_bound / minimum_derivative)
            return dict(certified=True, input_a_hex=a.hex(), computed_y_hex=y.hex(),
                        lower=_outward_float(lower, -1), upper=_outward_float(upper, 1),
                        residual_absolute_bound=_outward_float(residual_bound, 1),
                        minimum_derivative_lower_bound=_outward_float(minimum_derivative, -1),
                        root_absolute_error_bound=_outward_float(error_bound, 1),
                        root_relative_error_bound=_outward_float(error_bound / yy, 1),
                        bracket_expansions=expansion, maximum_series_terms=max(term_counts),
                        proof="exact rational exponential Taylor bounds plus monotonicity and mean-value theorem",
                        scope="exact binary64 a; excludes physical parameter-to-a and final boundary rounding")
        radius *= 2
    raise RuntimeError("No narrow exact-rational root certificate within the expansion limit")


@contextmanager
def model_runtime_adapter():
    """Single-process optional probe only; restore the original symbol always.

    This temporarily replaces a Python module binding. It changes no source or
    frozen study artifact and is not safe for concurrent threads in one process.
    """
    from . import model
    original = model.free_boundary
    model.free_boundary = free_boundary
    try:
        yield
    finally:
        model.free_boundary = original
