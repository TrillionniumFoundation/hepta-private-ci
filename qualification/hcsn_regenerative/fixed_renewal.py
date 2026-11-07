"""FP64 construction kernels for fixed-generator, zero-delay reset experiments.

This is a separate candidate from the V4 tensor operator. Parameters and grids
are fixed construction inputs; no parameter-autodiff claim is made. The returned
linear state operators may subsequently be executed in an explicitly chosen
tensor dtype. No probability clipping or row normalization is performed.
"""

from dataclasses import dataclass
import math

import numpy as np
from scipy.integrate import quad
from scipy.special import log_ndtr


@dataclass(frozen=True)
class FixedDiffusion:
    mu: float
    sigma: float
    discount: float = .15

    def __post_init__(self):
        for value in (self.mu, self.sigma, self.discount):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError('Fixed construction parameters must be finite real scalars')
        if abs(self.mu) > 2 or not .05 <= self.sigma <= 4 or not .01 <= self.discount <= 4:
            raise ValueError('Fixed diffusion is outside the registered parameter box')

    def first_hit(self, x, time, *, discounted=False):
        """Continuous first-hit law, including the initial boundary atom."""
        return math.exp(self.log_first_hit(x, time, discounted=discounted))

    def log_first_hit(self, x, time, *, discounted=False):
        """Log probability retains tails below the FP64 exponential range."""
        _point_inputs(x, time)
        if x == 0:
            return 0.
        if time == 0:
            return -math.inf
        scale = self.sigma * math.sqrt(time)
        if discounted:
            chi = math.sqrt(self.mu**2 + 2*self.discount*self.sigma**2)
            minus = 2*self.discount/(chi+self.mu) if self.mu > 0 else (chi-self.mu)/self.sigma**2
            plus = 2*self.discount/(chi-self.mu) if self.mu < 0 else (chi+self.mu)/self.sigma**2
            left = minus*x + log_ndtr((-x-chi*time)/scale)
            right = -plus*x + log_ndtr((-x+chi*time)/scale)
        else:
            left = log_ndtr((-x-self.mu*time)/scale)
            right = -2*self.mu*x/self.sigma**2 + log_ndtr((-x+self.mu*time)/scale)
        value = float(np.logaddexp(left, right))
        if not math.isfinite(value) or value > math.log1p(5e-12):
            raise FloatingPointError('Fixed first-hit evaluation is unresolved')
        return value


def _point_inputs(x, time):
    for value in (x, time):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Distance and time must be finite real scalars')
    if x < 0 or not 0 <= time <= 8:
        raise ValueError('Require x >= 0 and 0 <= time <= 8')


def _log_difference(left, right):
    if right == -math.inf:
        return left
    if left < right:
        raise FloatingPointError('A positive log difference is unresolved')
    if left == right:
        return -math.inf
    return left + math.log(-math.expm1(right-left))


def _normal_interval_log(mean, scale, low, high):
    lower, upper = (low-mean)/scale, (high-mean)/scale
    if lower == upper:
        raise FloatingPointError('Interval endpoints coincide at construction precision')
    if lower >= 0:
        return _log_difference(float(log_ndtr(-lower)), float(log_ndtr(-upper)))
    return _log_difference(float(log_ndtr(upper)), float(log_ndtr(lower)))


@dataclass
class ConstructionDiagnostics:
    positive_quadrature_fallbacks: int = 0
    positive_quadrature_error_sum: float = 0.
    underflowed_intervals: int = 0


def _positive_interval(process, x, time, low, high, log_weight, diagnostics):
    """Independent positive y-integral when a difference is poorly resolved."""
    sigma2t = process.sigma**2*time
    scale = math.sqrt(sigma2t)
    mean = x+process.mu*time
    lower, upper = (low-mean)/scale, (high-mean)/scale

    def integrand(z):
        y = mean+scale*z
        if y <= 0:
            return 0.
        factor = -math.expm1(-2*x*y/sigma2t)
        return math.exp(log_weight-.5*z*z-.5*math.log(2*math.pi))*factor

    value, error = quad(integrand, lower, upper, epsabs=1e-13, epsrel=2e-11, limit=300)
    diagnostics.positive_quadrature_fallbacks += 1
    diagnostics.positive_quadrature_error_sum += error
    if not math.isfinite(value) or value < 0 or error > 1e-12+2e-10*value:
        raise FloatingPointError('Positive killed-density integral is unresolved')
    return value


def _weighted_killed_interval(process, x, time, low, high, log_weight, diagnostics):
    if high <= low or x == 0:
        return 0.
    if time == 0:
        return math.exp(log_weight) if low <= x < high else 0.
    scale = process.sigma*math.sqrt(time)
    left = _normal_interval_log(x+process.mu*time, scale, low, high)
    right = (-2*process.mu*x/process.sigma**2
             + _normal_interval_log(-x+process.mu*time, scale, low, high))
    if left == -math.inf and right == -math.inf:
        diagnostics.underflowed_intervals += 1
        return 0.
    difference = right-left
    if not math.isfinite(left) or difference >= -1e-5:
        return _positive_interval(process, x, time, low, high, log_weight, diagnostics)
    log_value = log_weight+left+math.log(-math.expm1(difference))
    value = math.exp(log_value)
    if value == 0:
        diagnostics.underflowed_intervals += 1
    if not math.isfinite(value) or value < 0:
        raise FloatingPointError('Weighted killed interval is unresolved')
    return value


def killed_interval(process, x, time, low, high, *, diagnostics=None):
    """Unconditional killed mass in [low, high); high may be +infinity."""
    _point_inputs(x, time)
    if not math.isfinite(low) or low < 0 or math.isnan(high) or high <= low:
        raise ValueError('Require 0 <= low < high, with only high possibly infinite')
    diagnostics = ConstructionDiagnostics() if diagnostics is None else diagnostics
    return _weighted_killed_interval(process, x, time, low, high, 0., diagnostics)


def released_interval(process, distance, reset_margin, time, low, high, *, diagnostics=None):
    """Exact release convolution, integrated over one destination interval.

    C(L,a;t,y) = integral f_L(s) K(a;t-s,y) ds. For y<a it equals
    K(a+L;t,y); for y>=a it equals exp(-2*mu*L/sigma**2) K(a;t,y+L).
    L=0 includes the first-hit atom. T=0 is the reset atom only when L=0.
    """
    _point_inputs(distance, time)
    if not isinstance(reset_margin, (int, float)) or isinstance(reset_margin, bool) or not 0 < reset_margin <= 8:
        raise ValueError('Reset distance must be a fixed scalar in (0,8]')
    if not math.isfinite(low) or low < 0 or math.isnan(high) or high <= low:
        raise ValueError('Require 0 <= low < high')
    diagnostics = ConstructionDiagnostics() if diagnostics is None else diagnostics
    if time == 0:
        return float(distance == 0 and low <= reset_margin < high)
    result = 0.
    if low < reset_margin:
        result += _weighted_killed_interval(process, reset_margin+distance, time, low,
                                            min(high, reset_margin), 0., diagnostics)
    if high > reset_margin:
        result += _weighted_killed_interval(process, reset_margin, time,
                                            max(low, reset_margin)+distance, high+distance,
                                            -2*process.mu*distance/process.sigma**2, diagnostics)
    if not math.isfinite(result) or not 0 <= result <= 1+5e-10:
        raise FloatingPointError('Release interval mass is unresolved')
    return result


def hit_count_tail_bound(process, distance, reset_margin, time):
    """Chernoff/geometric bound on sum_j>=0 F(distance+j*a, time).

    The displayed analytic bound is evaluated in FP64; it is not an outward
    rounded interval-arithmetic certificate. It also bounds discounted counts.
    """
    if time == 0:
        return float(distance == 0)
    sigma2 = process.sigma**2
    eta = max((distance+process.mu*time)/(sigma2*time),
              1/(process.sigma*math.sqrt(time)), 2*max(process.mu, 0)/sigma2+1)
    laplace = .5*sigma2*eta*eta-process.mu*eta
    log_bound = laplace*time-eta*distance-math.log(-math.expm1(-eta*reset_margin))
    if log_bound < math.log(math.ulp(0.)):
        return math.ulp(0.)
    return math.exp(log_bound) if log_bound < 709 else math.inf


@dataclass(frozen=True)
class InstantResetTransition:
    process: FixedDiffusion
    reset_margin: float
    initial_distance: float
    horizon: float
    active_bins: np.ndarray
    upper_tail: float
    first_hit_probability: float
    expected_hits_partial: float
    expected_discounted_hits_partial: float
    omitted_active_mass: float
    log_omitted_active_mass: float | None
    omitted_hit_count_bound: float
    terms: int
    mass_residual_against_truncated_law: float
    construction_diagnostics: ConstructionDiagnostics


def instant_reset_transition(process, reset_margin, x, time, edges, *, tolerance=1e-10, max_terms=4096):
    """A genuinely zero-refractory law with an explicit, positive renewal tail.

    After N releases the omitted active probability is exactly F(x+N*a,T).
    We also require a Chernoff bound for all omitted hit rewards. The truncated
    result stays a subprobability: no synthetic bucket or renormalization hides
    its omitted mass. Grids, a, N-selection and process parameters are fixed.
    """
    _point_inputs(x, time)
    if isinstance(reset_margin, bool) or not isinstance(reset_margin, (int, float)) or not 0 < reset_margin <= 8:
        raise ValueError('Reset distance must be a fixed scalar in (0,8]')
    if isinstance(max_terms, bool) or not isinstance(max_terms, int) or not 1 <= max_terms <= 16384:
        raise ValueError('max_terms must be a fixed integer in [1,16384]')
    if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool) or not 1e-13 <= tolerance <= 1e-5:
        raise ValueError('Construction tolerance must be in [1e-13,1e-5]')
    edges = np.asarray(edges, dtype=np.float64)
    if edges.ndim != 1 or len(edges) < 2 or edges[0] != 0 or not np.isfinite(edges).all() or not (np.diff(edges) > 0).all():
        raise ValueError('Active edges must be fixed, finite and increasing from zero')
    intervals = list(zip(edges[:-1], edges[1:]))+[(edges[-1], math.inf)]
    diagnostics = ConstructionDiagnostics()
    masses = np.array([killed_interval(process, x, time, float(lo), float(hi), diagnostics=diagnostics)
                       for lo, hi in intervals])
    hits, discounted_hits = 0., 0.
    for terms in range(1, max_terms+1):
        distance = x+(terms-1)*reset_margin
        masses += np.array([released_interval(process, distance, reset_margin, time,
                                              float(lo), float(hi), diagnostics=diagnostics)
                            for lo, hi in intervals])
        hits += process.first_hit(distance, time)
        discounted_hits += process.first_hit(distance, time, discounted=True)
        tail_distance = x+terms*reset_margin
        omitted = process.first_hit(tail_distance, time)
        count_bound = hit_count_tail_bound(process, tail_distance, reset_margin, time)
        if max(omitted, count_bound) <= tolerance:
            break
    else:
        raise FloatingPointError('Explicit max_terms does not resolve the zero-delay renewal tail')
    residual = float(1-omitted-masses.sum())
    if not np.isfinite(masses).all() or np.any(masses < 0) or abs(residual) > 5e-10:
        raise FloatingPointError('Zero-delay mass is unresolved; no row renormalization is permitted')
    log_omitted = process.log_first_hit(tail_distance, time) if time > 0 else None
    return InstantResetTransition(process, reset_margin, x, time, masses[:-1], float(masses[-1]), process.first_hit(x, time),
                                  hits, discounted_hits, omitted, log_omitted, count_bound, terms,
                                  residual, diagnostics)


def instant_reset_value(process, transition, time, *, active_reward=0., terminal_reward=0., hit_reward=1.):
    """Constant-payoff value of this same zero-delay forward law.

    A zero-duration refractory phase has zero occupation. The count truncation
    bounds the only omitted term. An initial x=0 hit is included by the kernel.
    """
    if not isinstance(transition, InstantResetTransition):
        raise TypeError('A matching zero-delay transition is required')
    if process != transition.process or time != transition.horizon:
        raise ValueError('Value and forward state must share the exact generator and horizon')
    if not math.isfinite(time) or not 0 <= time <= 8:
        raise ValueError('Invalid horizon')
    for value in (active_reward, terminal_reward, hit_reward):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise ValueError('Payoffs must be finite fixed scalars')
    occupation = -math.expm1(-process.discount*time)/process.discount
    value = active_reward*occupation+terminal_reward*math.exp(-process.discount*time)
    value += hit_reward*transition.expected_discounted_hits_partial
    return {'value': value, 'discounted_active_occupation': occupation,
            'absolute_value_tail_bound': abs(hit_reward)*transition.omitted_hit_count_bound,
            'physical_refractory': 0., 'construction_dtype': 'float64',
            'parameter_autodiff_qualified': False}
