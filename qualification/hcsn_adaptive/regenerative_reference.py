"""FP64 scalar Brownian first-passage and deterministic-delay renewal reference.

X=x+drift*t+sigma*W hits the lower boundary 0, waits exactly refractory,
then restarts at reset. All cycles have the same coefficients. Returned flow
is an expected event density, with a separate time-zero atom when x=0.
This is neither a moving-boundary solver nor a coupled-network state update.
"""

from dataclasses import dataclass
from fractions import Fraction
import math
from numbers import Real

from scipy.special import erfcx, log_ndtr

__all__ = ["RegenerativeReference"]

_MIN_SCALE, _MAX_SCALE = 1e-12, 1e6
_MISSING_TIME = object()


def _scalar(value, name, lower, upper):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a real scalar")
    try:
        value = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} exceeds FP64") from exc
    if not math.isfinite(value) or not lower <= value <= upper:
        raise ValueError(f"{name} must lie in [{lower}, {upper}]")
    return value


def _log_cdf(distance, time, drift, sigma):
    if distance == 0:
        return 0.0  # The first passage is an atom at time zero.
    if time <= 0:
        return -math.inf
    scale = sigma * math.sqrt(time)
    left, right = (-distance - drift * time) / scale, (-distance + drift * time) / scale
    first = float(log_ndtr(left))
    if right <= 0:
        # Cancel the exponential analytically, before FP64 evaluation:
        # -2*mu*x/sigma^2 - right^2/2 = -left^2/2.
        scaled = float(erfcx(-right / math.sqrt(2)))
        second = -0.5 * left * left + math.log(scaled / 2) if scaled else -math.inf
    else:
        second = -2 * drift * distance / sigma**2 + float(log_ndtr(right))
    top, bottom = max(first, second), min(first, second)
    result = top + math.log1p(math.exp(bottom - top)) if top != -math.inf else top
    if math.isnan(result) or result > 8 * math.ulp(1.0):
        raise ArithmeticError("first-passage CDF lost its probability range")
    return min(0.0, result)  # At most eight ulps of CDF addition roundoff.


def _density(distance, time, drift, sigma):
    if distance == 0 or time <= 0:
        return 0.0  # A Dirac atom is never encoded as a finite density.
    z = (distance + drift * time) / (sigma * math.sqrt(time))
    log_density = (
        math.log(distance)
        - math.log(sigma)
        - 0.5 * math.log(2 * math.pi)
        - 1.5 * math.log(time)
        - 0.5 * z * z
    )
    try:
        return math.exp(log_density)
    except OverflowError as exc:
        raise ArithmeticError("first-passage density exceeds finite FP64") from exc


@dataclass(frozen=True)
class RegenerativeReference:
    """Bounded fixed-coefficient reference on the half-line, with no upper wall.

    Times and distances use caller-declared consistent units. Positive model
    scales lie in [1e-12,1e6], |drift|<=1e6, initial distance<=1e6.
    max_horizon<=1e6 and 1<=max_terms<=4096 bound every finite renewal sum.
    Very small results may underflow to zero; no precision guarantee is implied.
    """

    drift: float
    sigma: float
    reset: float
    refractory: float
    max_terms: int = 128
    max_horizon: float = _MAX_SCALE

    def __post_init__(self):
        for name in ("drift", "sigma", "reset", "refractory", "max_horizon"):
            lower = -_MAX_SCALE if name == "drift" else _MIN_SCALE
            object.__setattr__(
                self, name, _scalar(getattr(self, name), name, lower, _MAX_SCALE)
            )
        if type(self.max_terms) is not int or not 1 <= self.max_terms <= 4096:
            raise ValueError("max_terms must be an integer in [1,4096]")

    def _inputs(self, distance, time=_MISSING_TIME):
        distance = _scalar(distance, "initial distance", 0, _MAX_SCALE)
        if time is _MISSING_TIME:
            time = None
        else:
            time = _scalar(time, "horizon", 0, self.max_horizon)
        return distance, time

    def _discount(self, discount):
        discount = _scalar(discount, "discount", 0, _MAX_SCALE)
        if 0 < discount < _MIN_SCALE:
            raise ValueError("positive discount below the reference scale")
        return discount

    def _log_hit(self, distance, discount):
        root = math.hypot(self.drift, self.sigma * math.sqrt(2 * discount))
        # Rationalize the cancelling root when drift is negative.
        rate = (
            2 * discount / (root - self.drift)
            if self.drift < 0
            else (self.drift + root) / self.sigma**2
        )
        return -rate * distance, root

    def _discounted_hit(self, distance, discount, horizon):
        log_hit, root = self._log_hit(distance, discount)
        if horizon is not None:
            # e^(-q*t) f_mu(t) = R_q(x) f_{-sqrt(mu^2+2q*sigma^2)}(t).
            log_hit += _log_cdf(distance, horizon, -root, self.sigma)
        return math.exp(log_hit)

    def _schedule(self, horizon):
        # Exact arithmetic for the supplied FP64 clocks prevents a rounded
        # division from dropping a renewal term at a refractory boundary.
        end, delay = Fraction(horizon), Fraction(self.refractory)
        terms = end // delay + 1
        if terms > self.max_terms:
            raise ValueError("finite renewal term budget exhausted")
        return tuple(float(end - k * delay) for k in range(terms))

    def first_hit_cdf(self, distance, horizon):
        """P(tau<=horizon); distance=0 includes the time-zero atom."""
        distance, horizon = self._inputs(distance, horizon)
        return math.exp(_log_cdf(distance, horizon, self.drift, self.sigma))

    def first_hit_density(self, distance, time):
        """Absolutely continuous part only; the boundary atom has density zero."""
        distance, time = self._inputs(distance, time)
        return _density(distance, time, self.drift, self.sigma)

    def _nth_inputs(self, distance, horizon, number):
        distance, horizon = self._inputs(distance, horizon)
        if type(number) is not int or not 1 <= number <= self.max_terms:
            raise ValueError("event number exceeds the positive integer term budget")
        residual = float(Fraction(horizon) - (number - 1) * Fraction(self.refractory))
        return distance + (number - 1) * self.reset, residual

    def nth_hit_cdf(self, distance, horizon, number):
        """CDF of T_n, including missing probability when drift>0."""
        distance, residual = self._nth_inputs(distance, horizon, number)
        return (
            math.exp(_log_cdf(distance, residual, self.drift, self.sigma))
            if residual >= 0
            else 0.0
        )

    def nth_hit_density(self, distance, time, number):
        """Continuous density of T_n; only T_1 at initial distance 0 has an atom."""
        distance, residual = self._nth_inputs(distance, time, number)
        return _density(distance, residual, self.drift, self.sigma)

    def summary(self, distance, horizon):
        """First risk, count moments and continuous flux from the same renewal law."""
        distance, horizon = self._inputs(distance, horizon)
        times = self._schedule(
            horizon
        )  # Enforce work budget before evaluating kernels.
        tails = [
            math.exp(_log_cdf(distance + k * self.reset, t, self.drift, self.sigma))
            for k, t in enumerate(times)
        ]
        return {
            "first_event_probability": tails[0],
            "expected_events": math.fsum(tails),
            "second_event_moment": math.fsum(
                (2 * k + 1) * p for k, p in enumerate(tails)
            ),
            "continuous_event_rate": math.fsum(
                _density(distance + k * self.reset, t, self.drift, self.sigma)
                for k, t in enumerate(times)
            ),
            "time_zero_event_mass": float(distance == 0),
            "terms_evaluated": len(times),
        }

    def discounted_hit(self, distance, discount, *, horizon=None):
        """E[e^(-q*tau) 1(tau<=horizon)]; None means the infinite horizon."""
        distance, horizon = (
            self._inputs(distance)
            if horizon is None
            else self._inputs(distance, horizon)
        )
        return self._discounted_hit(distance, self._discount(discount), horizon)

    def discounted_events(self, distance, discount, *, horizon=None):
        """Expected discounted sum of ALL events, including a possible initial atom."""
        distance, horizon = (
            self._inputs(distance)
            if horizon is None
            else self._inputs(distance, horizon)
        )
        discount = self._discount(discount)
        if horizon is not None:
            times = self._schedule(horizon)
            return math.fsum(
                math.exp(-discount * k * self.refractory)
                * self._discounted_hit(distance + k * self.reset, discount, t)
                for k, t in enumerate(times)
            )
        reset_log, _ = self._log_hit(self.reset, discount)
        denominator = -math.expm1(reset_log - discount * self.refractory)
        if denominator == 0:
            if discount == 0 and self.drift <= 0:
                raise ValueError(
                    "undiscounted infinite event count diverges for drift<=0"
                )
            raise ArithmeticError("renewal denominator is unresolved in FP64")
        result = self._discounted_hit(distance, discount, None) / denominator
        if not math.isfinite(result):
            raise ArithmeticError("discounted event sum exceeds finite FP64")
        return result

    def value(self, distance, discount, running_reward, event_payoff):
        """Infinite value from the supplied active point, BEFORE a boundary event.

        running_reward is constant per active-time unit; event_payoff is NET
        reward/cost paid immediately on every event. Waiting is frozen with zero
        reward. This is fixed-policy continuation, not an optimized free boundary.
        """
        distance, _ = self._inputs(distance)
        discount = self._discount(discount)
        if discount == 0:
            raise ValueError("regenerative value requires positive discount")
        reward = _scalar(running_reward, "running reward", -_MAX_SCALE, _MAX_SCALE)
        payoff = _scalar(event_payoff, "event payoff", -_MAX_SCALE, _MAX_SCALE)
        initial_log, _ = self._log_hit(distance, discount)
        reset_log, _ = self._log_hit(self.reset, discount)
        denominator = -math.expm1(reset_log - discount * self.refractory)
        reset_value = (
            -math.expm1(reset_log) * reward / discount + math.exp(reset_log) * payoff
        ) / denominator
        result = -math.expm1(initial_log) * reward / discount + math.exp(
            initial_log
        ) * (payoff + math.exp(-discount * self.refractory) * reset_value)
        if not math.isfinite(result):
            raise ArithmeticError("regenerative value exceeds finite FP64")
        return result
