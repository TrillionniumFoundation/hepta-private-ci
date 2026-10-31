"""P0/P2 analytic reference: finite-horizon discounted Brownian repeated FIREs.

For dX=mu dt+sigma dW, an upper threshold b, reset r<b, deterministic
refractory h>=0 and constant discount rho>0, the n-th event time is the
first-passage time over d0+n*(b-r), plus n*h (for initial x<b).

This identity follows from stationary independent Brownian increments and
strong Markov. It does NOT describe He--Xiong's coupled bond/equity free
boundary, a moving boundary, or a live native GPU spike kernel.

A geometrically bounded truncation controls the omitted *analytic terms*,
not rounding or normal-CDF implementation error. Unsupported regimes refuse.
"""

from dataclasses import dataclass
import math

from scipy.special import log_ndtr, logsumexp

from .stopping import Stop


class UnresolvedRenewal(ValueError):
    """Refuse a numerically undecidable or unsupported scalar renewal case."""


@dataclass(frozen=True)
class SeriesEstimate:
    discounted_events: float
    omitted_events_upper_bound: float
    terms_evaluated: int
    full_finite_series: bool


def _finite(*values: float) -> bool:
    return all(type(v) in (float, int) and math.isfinite(v) for v in values)


def _kappa(mu: float, sigma: float, rate: float) -> float:
    magnitude = math.hypot(mu, sigma * math.sqrt(2 * rate))
    if mu >= 0:
        denominator = magnitude + mu
        k = 2 * rate / denominator if denominator else 0.0
    else:
        k = (magnitude - mu) / (sigma * sigma)
    if not math.isfinite(k) or k < 0:
        raise UnresolvedRenewal('unresolved Laplace root')
    return k


def discounted_first_hit(distance: float, drift: float, diffusion: float,
                         rate: float, horizon: float) -> float:
    """E[exp(-rate*T_hit) 1{T_hit<=horizon}] for upward Brownian hitting.

    A positive sum of two log-normal-tail terms avoids subtracting nearly
    equal default and survival probabilities. An at-boundary hit is at t=0.
    """
    if (not _finite(distance, drift, diffusion, rate, horizon)
            or distance < 0 or diffusion <= 0 or rate < 0 or horizon < 0):
        raise UnresolvedRenewal('invalid first-passage inputs')
    if distance == 0:
        return 1.0
    if horizon == 0:
        return 0.0
    scale = diffusion * math.sqrt(horizon)
    magnitude = math.hypot(drift, diffusion * math.sqrt(2 * rate))
    variance = diffusion * diffusion
    if not _finite(scale, magnitude, variance) or scale <= 0 or variance <= 0:
        raise UnresolvedRenewal('unresolved Brownian scaling')
    # Signed roots, rationalizing the potentially cancelling branch.
    plus = ((magnitude + drift) / variance if drift >= 0 else
            (2 * rate / (magnitude - drift) if magnitude > drift else 0.0))
    minus = (-(magnitude - drift) / variance if drift <= 0 else
             (-2 * rate / (magnitude + drift) if magnitude + drift else 0.0))
    q1 = (-distance - magnitude * horizon) / scale
    q2 = (-distance + magnitude * horizon) / scale
    a = plus * distance + float(log_ndtr(q1))
    b = minus * distance + float(log_ndtr(q2))
    if any(math.isnan(x) or x == math.inf for x in (a, b)):
        raise UnresolvedRenewal('unresolved logarithmic normal-tail terms')
    lp = float(logsumexp((a, b)))
    # True discounted probability is in [0,1], no silent clipping to mask error.
    if math.isnan(lp) or lp > 0:
        raise UnresolvedRenewal('discounted first-hit probability outside [0,1]')
    return math.exp(lp)


def _validate(p: Stop, state: float, boundary: float, horizon: float,
              absolute_tail_tolerance: float, max_terms: int) -> None:
    if not isinstance(p, Stop) or not _finite(state, boundary, horizon,
                                               absolute_tail_tolerance):
        raise UnresolvedRenewal('invalid renewal inputs')
    if not (boundary > p.cost and boundary > p.reset and horizon >= 0
            and 0 < absolute_tail_tolerance < 1 and
            type(max_terms) is int and 1 <= max_terms <= 100000):
        raise UnresolvedRenewal('invalid threshold, horizon or truncation budget')


def expected_discounted_event_count(
    p: Stop, state: float, boundary: float, horizon: float, *,
    absolute_tail_tolerance: float = 1e-11, max_terms: int = 4096,
) -> SeriesEstimate:
    """Finite-horizon E[sum_{spikes at t<=T} exp(-rho*t)] for fixed b.

    For initial state x<b, nth term is exp(-rho*n*h)*G_rho(
      (b-x)+n*(b-reset), T-n*h), n>=0.
    For x>=b, count 1 at t=0 plus n>=1 with distance n*(b-reset).
    Truncation uses the *infinite-horizon* Laplace geometric envelope.
    """
    _validate(p, state, boundary, horizon, absolute_tail_tolerance, max_terms)
    kappa = _kappa(p.drift, p.diffusion, p.discount)
    gap = boundary - p.reset
    cycle_decay = p.discount * p.refractory + kappa * gap
    if not math.isfinite(cycle_decay) or cycle_decay <= 0:
        raise UnresolvedRenewal('noncontractive or unresolvable reset cycle')
    denominator = -math.expm1(-cycle_decay)
    if denominator <= 0:
        raise UnresolvedRenewal('unresolved geometric denominator')

    instant = state >= boundary
    initial_distance = gap if instant else boundary - state
    start_index = 1 if instant else 0
    # Event n first appears at n*h, including all possible n for finite h.
    n_max = None
    if p.refractory > 0:
        budget = horizon / p.refractory
        if not math.isfinite(budget):
            raise UnresolvedRenewal('unresolved physical horizon/event budget')
        n_max = math.floor(budget)
    values = [1.0] if instant else []
    terms = 0
    tail = math.inf
    full = False
    for n in range(start_index, start_index + max_terms):
        if n_max is not None and n > n_max:
            full, tail = True, 0.0
            break
        remaining = horizon - n * p.refractory
        if remaining < 0:
            full, tail = True, 0.0
            break
        distance = initial_distance + (n - start_index) * gap
        # In the instant case, n=1 is the first future hitting event.
        term = math.exp(-p.discount * n * p.refractory) * discounted_first_hit(
            distance, p.drift, p.diffusion, p.discount, remaining)
        values.append(term)
        terms += 1
        # First omitted event n+1, with an upper bound from infinite horizon.
        omitted_index = n + 1
        log_tail = (-p.discount * omitted_index * p.refractory
                    -kappa * (initial_distance + (omitted_index-start_index) * gap))
        tail = math.exp(log_tail) / denominator
        if n_max is not None and omitted_index > n_max:
            full, tail = True, 0.0
            break
        if tail <= absolute_tail_tolerance:
            break
    if not math.isfinite(tail) or tail > absolute_tail_tolerance:
        raise UnresolvedRenewal('truncation tail cannot be bounded by budget')
    result = math.fsum(values)
    if not math.isfinite(result) or result < 0:
        raise UnresolvedRenewal('nonfinite or negative event estimate')
    return SeriesEstimate(result, tail, terms, full)


def expected_discounted_reward(
    p: Stop, state: float, boundary: float, horizon: float, *,
    absolute_tail_tolerance: float = 1e-11, max_terms: int = 4096,
) -> tuple[float, float]:
    """Finite-horizon threshold-policy reward and analytic truncation bound.

    The first immediate reward from x>=b is (x-K) rather than (b-K).
    """
    estimate = expected_discounted_event_count(
        p, state, boundary, horizon,
        absolute_tail_tolerance=absolute_tail_tolerance, max_terms=max_terms)
    payoff = boundary - p.cost
    value = payoff * estimate.discounted_events
    if state >= boundary:
        value = math.fsum((value, state - boundary))
    return value, payoff * estimate.omitted_events_upper_bound
