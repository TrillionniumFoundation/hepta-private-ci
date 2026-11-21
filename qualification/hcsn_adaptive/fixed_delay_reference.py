"""Exact fixed-coefficient renewal reference with a genuinely fixed refractory time.

An active unit fires at exponential rate lambda, waits exactly d, then becomes
active again. The kth recorded event after an initially active cohort occurs at
Gamma(k, lambda) + (k-1)d. Finite sums give risk, counts, age density and value.
Initial waiting atoms are retained. A record stores the original cohorts and
elapsed clock, from which the full age distribution is reconstructed: an active
mean alone is not its state. This bounded scalar reference has no time-grid
error; special-function truncation/FP64 rounding remain. It does NOT implement
time-varying rates, arbitrary incoming age distributions or spatial diffusion.
"""

from dataclasses import dataclass, replace
import math


def _logsum(values):
    maximum = max(values, default=-math.inf)
    if maximum == -math.inf:
        return maximum
    return maximum + math.log(math.fsum(math.exp(v - maximum) for v in values))


def _log_erlang_cdf(shape, z):
    if z <= 0:
        return -math.inf
    if z >= shape:
        survival = -z + _logsum([k * math.log(z) - math.lgamma(k + 1) for k in range(shape)])
        return math.log(-math.expm1(survival))
    # Poisson upper tail, scaled by its first term; no 1-CDF cancellation.
    terms, term = [1.], 1.
    for k in range(shape + 1, shape + 4097):
        term *= z / k
        terms.append(term)
        remainder = term * z / (k + 1) / (1 - z / (k + 2))
        if remainder <= 2e-16 * math.fsum(terms):
            return -z + shape * math.log(z) - math.lgamma(shape + 1) + math.log(math.fsum(terms))
    raise ArithmeticError("Erlang CDF summation budget exhausted")


def _log_erlang_interval(shape, lower, upper):
    """Positive Poisson-increment sum for F(upper)-F(lower), including far tails."""
    if upper <= lower:
        return -math.inf
    if lower == 0:
        return _log_erlang_cdf(shape, upper)
    return _logsum([-lower + k * math.log(lower) - math.lgamma(k + 1)
                   + _log_erlang_cdf(shape - k, upper - lower) for k in range(shape)])


@dataclass(frozen=True)
class FixedDelayReference:
    rate: float
    delay_micros: int
    time_micros: int = 0
    cohorts: tuple = ((1., 0),)

    def __post_init__(self):
        if (not math.isfinite(self.rate) or self.rate <= 0
                or type(self.delay_micros) is not int or self.delay_micros < 1
                or type(self.time_micros) is not int or not 0 <= self.time_micros <= 127 * self.delay_micros
                or not isinstance(self.cohorts, tuple) or not 1 <= len(self.cohorts) <= 32
                or any(len(c) != 2 or not math.isfinite(c[0]) or c[0] < 0
                       or type(c[1]) is not int or not 0 <= c[1] <= self.delay_micros for c in self.cohorts)
                or not math.isclose(math.fsum(c[0] for c in self.cohorts), 1., rel_tol=0, abs_tol=1e-12)
                or not math.isfinite(self.rate * (self.delay_micros + self.time_micros) / 1e6)):
            raise ValueError("bounded fixed-rate law and normalized initial waiting cohorts required")

    @property
    def delay(self):
        return self.delay_micros / 1e6

    def _events(self, elapsed, discount=0.):
        if elapsed <= 0:
            return 0.
        beta = self.rate + discount
        return math.fsum(math.exp(-discount * (k - 1) * self.delay
                                  + k * (math.log(self.rate) - math.log(beta))
                                  + _log_erlang_cdf(k, beta * (elapsed - (k - 1) * self.delay)))
                         for k in range(1, math.floor(elapsed / self.delay) + 2))

    def _flux(self, elapsed):
        if elapsed < 0:
            return 0.
        terms = [self.rate * math.exp(-self.rate * elapsed)]
        for k in range(2, math.floor(elapsed / self.delay) + 2):
            age = elapsed - (k - 1) * self.delay
            if age > 0:
                terms.append(math.exp(k * math.log(self.rate) + (k - 1) * math.log(age)
                                      - self.rate * age - math.lgamma(k)))
        return math.fsum(terms)

    def summary(self):
        t = self.time_micros / 1e6
        count = math.fsum(w * self._events(t - r / 1e6) for w, r in self.cohorts)
        earlier = math.fsum(w * self._events(t - self.delay - r / 1e6) for w, r in self.cohorts)
        atoms = tuple((w, self.delay_micros - r + self.time_micros)
                      for w, r in self.cohorts if r > self.time_micros and w > 0)
        refractory = math.fsum(w for w, _ in atoms) + count - earlier
        first = math.fsum(w * -math.expm1(-self.rate * max(0., t - r / 1e6)) for w, r in self.cohorts)
        flux = math.fsum(w * self._flux(t - r / 1e6) for w, r in self.cohorts)
        return {"time_micros": self.time_micros, "active_mass": 1 - refractory,
                "refractory_mass": refractory, "waiting_atoms_mass_age_micros": atoms,
                "expected_events": count, "first_event_probability": first, "event_rate": flux}

    def age_density(self, age):
        """Continuous refractory age density; summary separately reports atoms."""
        if not math.isfinite(age) or not 0 <= age < self.delay:
            raise ValueError("refractory age must lie in [0,d)")
        return math.fsum(w * self._flux(self.time_micros / 1e6 - age - r / 1e6)
                         for w, r in self.cohorts)

    def discounted_events(self, discount, horizon="current"):
        if not math.isfinite(discount) or discount <= 0 or horizon not in ("current", "infinite"):
            raise ValueError("positive discount and current/infinite horizon required")
        if not math.isfinite((self.rate + discount) * (self.time_micros + self.delay_micros) / 1e6):
            raise ValueError("reference discount scale overflow")
        if horizon == "infinite":
            renewal = self.rate / (discount - self.rate * math.expm1(-discount * self.delay))
            return renewal * math.fsum(w * math.exp(-discount * r / 1e6) for w, r in self.cohorts)
        return math.fsum(w * math.exp(-discount * r / 1e6)
                         * self._events((self.time_micros - r) / 1e6, discount) for w, r in self.cohorts)

    def value(self, discount, running_reward, event_cost):
        """Future value of the CURRENT full age law; waiting has zero running reward."""
        if not all(map(math.isfinite, (discount, running_reward, event_cost))) or discount <= 0:
            raise ValueError("finite reward/cost and positive discount required")
        t, beta = self.time_micros / 1e6, self.rate + discount
        if not math.isfinite(beta * (t + self.delay)):
            raise ValueError("reference discount scale overflow")
        active_value = ((running_reward - self.rate * event_cost)
                        / (discount - self.rate * math.expm1(-discount * self.delay)))
        mass = [self.summary()["active_mass"]]
        for weight, residual in self.cohorts:
            if weight == 0:
                continue
            if residual > self.time_micros:
                mass.append(weight * math.exp(-discount * (residual - self.time_micros) / 1e6))
            elapsed = t - residual / 1e6
            for k in range(1, max(0, math.floor(elapsed / self.delay) + 1) + 1):
                offset = residual / 1e6 + (k - 1) * self.delay
                lower, upper = max(0., t - self.delay - offset), t - offset
                if upper > lower:
                    log_interval = _log_erlang_interval(k, beta * lower, beta * upper)
                    mass.append(math.exp(math.log(weight) - discount * (self.delay - t + offset)
                                         + k * (math.log(self.rate) - math.log(beta)) + log_interval))
        return active_value * math.fsum(mass)

    def advance(self, micros):
        if type(micros) is not int or micros <= 0:
            raise ValueError("positive integer microseconds required")
        return replace(self, time_micros=self.time_micros + micros)

    def to_record(self):
        return {"schema": "fixed-delay-single-clock-v1", "rate": self.rate,
                "delay_micros": self.delay_micros, "time_micros": self.time_micros,
                "cohorts": [list(c) for c in self.cohorts]}

    @classmethod
    def from_record(cls, record):
        if (set(record) != {"schema", "rate", "delay_micros", "time_micros", "cohorts"}
                or record["schema"] != "fixed-delay-single-clock-v1"):
            raise ValueError("fixed-delay cohort record required; Erlang phases are a different law")
        return cls(record["rate"], record["delay_micros"], record["time_micros"],
                   tuple(tuple(c) for c in record["cohorts"]))
