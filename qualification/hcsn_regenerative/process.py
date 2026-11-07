"""One killed Brownian generator and its fixed-reset renewal value.

This is a separate scalar FP64 reference, not a replacement for the frozen
HCSN experiment. It has constant drift/volatility, fixed reset margin and a
physical refractory duration; it does not silently freeze a dynamic policy.
"""

from dataclasses import dataclass
import math

import numpy as np
from scipy.integrate import quad

from qualification.hcsn import reference
from qualification.hcsn.population import killed_transition


def _integrate(function, lo, hi, tolerance):
    result = quad(function, lo, hi, epsabs=tolerance, epsrel=1e-10,
                  limit=250, full_output=1)
    if len(result) != 3 or not all(math.isfinite(v) for v in result[:2]):
        raise FloatingPointError("Active occupation quadrature did not converge")
    return result[:2]


def _scalar(name, value, lower=None, strict=False):
    if not np.isscalar(value) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite scalar")
    if lower is not None and (value <= lower if strict else value < lower):
        raise ValueError(f"{name} is outside its domain")


@dataclass(frozen=True)
class Transition:
    survivor_bins: tuple
    hit: float
    upper_tail: float


@dataclass(frozen=True)
class KilledDiffusion:
    """dX = mu dt + sigma dW, killed at X=0; L=mu*d_x+sigma²/2*d_xx."""

    mu: float
    sigma: float
    discount: float = 0.0

    def __post_init__(self):
        _scalar("mu", self.mu)
        _scalar("sigma", self.sigma, 0, strict=True)
        _scalar("discount", self.discount, 0)
        if not 0 < self.sigma * self.sigma < math.inf:
            raise ValueError("sigma squared must be representable in FP64")

    def hit_probability(self, x, horizon):
        return reference.first_passage_cdf(x, horizon, self.mu, self.sigma)

    def survival(self, x, horizon):
        return reference.first_passage_survival(x, horizon, self.mu, self.sigma)

    def discounted_hit(self, x, horizon):
        return reference.discounted_first_passage(
            x, horizon, self.mu, self.sigma, self.discount)

    def density(self, time, x):
        """Regular first-hit density; the x=0 atom is carried by hit_probability."""
        return reference.first_passage_density(time, x, self.mu, self.sigma)

    def laplace_root(self, rate):
        _scalar("rate", rate, 0)
        chi = math.hypot(self.mu, math.sqrt(2 * rate) * self.sigma)
        if self.mu < 0:
            return 2 * rate / (chi - self.mu)
        return (chi + self.mu) / self.sigma**2

    def laplace(self, x, rate=None):
        _scalar("x", x, 0)
        rate = self.discount if rate is None else rate
        return math.exp(-self.laplace_root(rate) * x)

    def transition(self, x, horizon, edges):
        """Unconditional surviving mass in [edge_i,edge_(i+1)), plus hit/tail.

        The upper tail remains explicit. At horizon=0, surviving mass is a
        Dirac atom at x; x=0 is already killed, including the (0,0) corner.
        """
        _scalar("x", x, 0)
        _scalar("horizon", horizon, 0)
        edges = np.asarray(edges, dtype=np.float64)
        if (edges.ndim != 1 or edges.size < 2 or edges[0] != 0
                or np.any(~np.isfinite(edges[:-1])) or np.isnan(edges[-1])
                or np.any(np.diff(edges) <= 0)):
            raise ValueError("edges must increase strictly from zero, with only the last optionally infinite")
        if x == 0:
            return Transition((0.0,) * (edges.size - 1), 1.0, 0.0)
        if horizon == 0:
            bins = np.zeros(edges.size - 1)
            index = np.searchsorted(edges, x, side="right") - 1
            if index < len(bins):
                bins[index] = 1.0
            return Transition(tuple(bins), 0.0, float(x >= edges[-1]))
        # Let the inherited kernel integrate the last half-line as its tail.
        # Avoid its indeterminate log(0)-log(0) at an infinite escape edge.
        unbounded = math.isinf(edges[-1])
        finite_edges = edges[:-1] if unbounded else edges
        matrix, hit, tail = killed_transition(
            np.array([x]), finite_edges, np.array([self.mu]), self.sigma, horizon)
        bins = tuple(float(v) for v in matrix[0])
        if unbounded:
            return Transition(bins + (float(tail[0]),), float(hit[0]), 0.0)
        return Transition(bins, float(hit[0]), float(tail[0]))


@dataclass(frozen=True)
class ResetRule:
    """Pay hit_reward at each hit, wait refractory, then restart at margin>0."""

    margin: float
    refractory: float = 0.0
    hit_reward: float = 1.0

    def __post_init__(self):
        _scalar("margin", self.margin, 0, strict=True)
        _scalar("refractory", self.refractory, 0)
        _scalar("hit_reward", self.hit_reward)


@dataclass(frozen=True)
class ValueReceipt:
    single_cycle: float
    regenerative: float
    expected_discounted_hits: float
    active_probability: float
    active_time: float
    renewal_tail_bound: float
    value_tail_bound: float
    quadrature_error: float
    terms: int


def _term_count(process, reset, x, horizon, tolerance, max_terms):
    """Bound every omitted event probability by a Laplace/Chernoff series.

    For beta>0: sum_{j>n} P(S_j<=T) <=
    exp(beta*T-lambda(beta)*x) * r**n/(1-r),
    r=exp(-beta*refractory-lambda(beta)*reset_margin).
    This also bounds the discounted count because discount>=0.
    """
    if horizon == 0:
        return 1, 0.0
    beta = 1 / horizon
    root = process.laplace_root(beta)
    log_ratio = -beta * reset.refractory - root * reset.margin
    if not math.isfinite(log_ratio) or log_ratio >= 0:
        raise FloatingPointError("Renewal remainder is unresolved in this FP64 domain")
    log_bound = beta * horizon - root * x - math.log(-math.expm1(log_ratio))
    for terms in range(1, max_terms + 1):
        if reset.refractory and terms * reset.refractory >= horizon:
            return terms, 0.0
        remainder = math.exp(min(700.0, log_bound + terms * log_ratio))
        if remainder <= tolerance:
            return terms, remainder
    raise ValueError("max_terms cannot resolve the declared renewal tolerance")


def _active_probability(process, reset, x, horizon, terms):
    if reset.refractory == 0:
        # Instantaneous resets occupy no positive time; boundary release at t=0
        # makes terminal active reward payable even when x initially equals 0.
        return 1.0
    values = [process.survival(x, horizon)]
    for n in range(1, terms + 1):
        remaining = horizon - n * reset.refractory
        if remaining < 0:
            break
        distance = x + (n - 1) * reset.margin
        values.append(process.hit_probability(distance, remaining)
                      - process.hit_probability(distance + reset.margin, remaining))
    result = math.fsum(values)
    if result < -1e-12 or result > 1 + 1e-10:
        raise FloatingPointError("Renewal active probability violates probability bounds")
    return result


def finite_horizon_value(process, reset, x, horizon, *, active_reward=0.0,
                         terminal_reward=0.0, tolerance=1e-10, max_terms=10000):
    """Return finite-horizon single-cycle E and regenerative U from one process.

    Active running reward is constant; terminal_reward is paid only if active
    at the deadline. Refractory states earn zero. The nth hit is a first passage
    from x+(n-1)*reset.margin, delayed by (n-1)*refractory. Hence multiple hits
    within the same observation interval and physical remaining-time reset are
    included. No time grid, step-end deposition, or hidden tail normalization is
    used. Active occupation uses adaptive quadrature and reports its error.
    """
    _scalar("x", x, 0)
    _scalar("horizon", horizon, 0)
    _scalar("active_reward", active_reward)
    _scalar("terminal_reward", terminal_reward)
    _scalar("tolerance", tolerance, 0, strict=True)
    if isinstance(max_terms, bool) or not isinstance(max_terms, int) or max_terms < 1:
        raise ValueError("max_terms must be a positive integer")
    terms, tail = _term_count(process, reset, x, horizon, tolerance, max_terms)
    q = process.discount
    hits = []
    for n in range(1, terms + 1):
        delay = (n - 1) * reset.refractory
        if delay > horizon:
            break
        distance = x + (n - 1) * reset.margin
        hits.append(math.exp(-q * delay) * process.discounted_hit(distance, horizon - delay))
    discounted_hits = math.fsum(hits)
    active = _active_probability(process, reset, x, horizon, terms)
    quadrature_error = 0.0
    if horizon == 0:
        one_time = active_time = 0.0
    else:
        one_time, error = _integrate(
            lambda t: math.exp(-q * t) * process.survival(x, t),
            0, horizon, tolerance)
        quadrature_error += error
        if reset.refractory == 0:
            active_time = horizon if q == 0 else -math.expm1(-q * horizon) / q
        else:
            # Split at release discontinuities (the initial boundary atom can
            # release at exactly refractory); do not round duration to a grid.
            breaks = [0.0] + [n * reset.refractory for n in range(1, terms + 1)
                              if n * reset.refractory < horizon] + [horizon]
            pieces = []
            for lo, hi in zip(breaks[:-1], breaks[1:]):
                value, error = _integrate(
                    lambda t: math.exp(-q * t) * _active_probability(process, reset, x, t, terms),
                    lo, hi, tolerance / len(breaks))
                pieces.append(value)
                quadrature_error += error
            active_time = math.fsum(pieces)
    discount = math.exp(-q * horizon)
    single = (active_reward * one_time + reset.hit_reward * process.discounted_hit(x, horizon)
              + terminal_reward * discount * process.survival(x, horizon))
    regenerative = (active_reward * active_time + reset.hit_reward * discounted_hits
                    + terminal_reward * discount * active)
    value_bound = tail * (abs(reset.hit_reward) + horizon * abs(active_reward) + abs(terminal_reward))
    return ValueReceipt(single, regenerative, discounted_hits, active, active_time,
                        tail, value_bound, quadrature_error, terms)


@dataclass(frozen=True)
class StationaryHXValue:
    single_cycle: float
    regenerative: float
    reset_single_cycle: float
    reset_regenerative: float
    discounted_reset_probability: float
    renewal_multiplier: float


def stationary_hx_value(par, reset, x):
    """Extend the existing killed HX cashflow E to U at its fixed boundary.

    Drift, volatility and discount are derived only from par; callers cannot
    accidentally supply a different risk generator. This does not optimize the
    boundary for the regenerative problem and does not make HX financial
    cashflow a measured neural task reward.
    """
    _scalar("x", x, 0)
    if not reference.parameter_feasibility(par)["local_admissible"]:
        raise ValueError("The HX single-cycle root is locally inadmissible")
    process = KilledDiffusion(par.mu, par.sigma, par.r)
    log_cycle = -par.r * reset.refractory - process.laplace_root(par.r) * reset.margin
    denominator = -math.expm1(log_cycle)
    if not denominator > 0:
        raise FloatingPointError("Stationary renewal does not have a resolved contraction")
    boundary = reference.hx_boundary(par)
    e_x = reference.hx_equity(x, par, boundary)
    e_reset = reference.hx_equity(reset.margin, par, boundary)
    u_reset = (e_reset + process.laplace(reset.margin) * reset.hit_reward) / denominator
    u_x = e_x + process.laplace(x) * (
        reset.hit_reward + math.exp(-par.r * reset.refractory) * u_reset)
    return StationaryHXValue(e_x, u_x, e_reset, u_reset,
                             math.exp(log_cycle), 1 / denominator)
