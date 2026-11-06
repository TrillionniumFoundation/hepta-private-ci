"""Exact pure-information gating reference; no random sampling or LLM calls."""
from dataclasses import dataclass
from fractions import Fraction as F
from functools import lru_cache
from math import isqrt

HALF = F(1, 2)


@dataclass(frozen=True)
class Contract:
    prepare_fee: F = F(2, 25)
    probe_fee: F = F(3, 25)
    time_price: F = F(1, 100)
    prepare_duration: int = 1
    probe_duration: int = 1
    deadline: int = 2

    def __post_init__(self):
        for value in (self.prepare_fee, self.probe_fee, self.time_price):
            if not isinstance(value, F) or value < 0:
                raise ValueError("nonnegative rational resource prices required")
        for value in (self.prepare_duration, self.probe_duration):
            if type(value) is not int or value <= 0:
                raise ValueError("positive integer durations required")
        if type(self.deadline) is not int or self.deadline < 0:
            raise ValueError("nonnegative integer deadline required")

    @property
    def prepare_cost(self):
        return self.prepare_fee + self.time_price * self.prepare_duration

    @property
    def probe_cost(self):
        return self.probe_fee + self.time_price * self.probe_duration

    @property
    def universally_stop(self):
        return (self.deadline < self.prepare_duration + self.probe_duration
                or self.prepare_cost + self.probe_cost >= HALF)


@dataclass(frozen=True)
class Law:
    readiness: F
    accuracy: F

    def __post_init__(self):
        if not isinstance(self.readiness, F) or not isinstance(self.accuracy, F):
            raise ValueError("exact rational laws required")
        if not 0 <= self.readiness <= 1 or not HALF <= self.accuracy <= 1:
            raise ValueError("readiness in [0,1], oriented accuracy in [1/2,1]")


def events(contract, law, hidden, ready, action, cap):
    duration = contract.prepare_duration if action == "prepare" else contract.probe_duration
    if cap < duration:
        return (((-2, cap, ready), F(1)),)
    if action == "prepare":
        probability = F(1) if ready else law.readiness
        return (((-1, duration, 1), probability), ((-1, duration, 0), 1 - probability))
    accuracy = law.accuracy if ready else HALF
    return tuple(((label, duration, ready), accuracy if label == hidden else 1 - accuracy)
                 for label in (0, 1))


def known_law_plan(contract, law, mode="dp"):
    """Belief DP over every action/cap; the law is an explicitly known-law input."""
    if mode not in ("dp", "myopic"):
        raise ValueError("unknown comparator")

    @lru_cache(None)
    def solve(belief, ready, remaining, depth):
        best, choice = max(belief, 1 - belief), ("stop", int(belief > HALF))
        if depth == 0 or remaining == 0:
            return best, choice
        for action, fee in (("prepare", contract.prepare_fee), ("probe", contract.probe_fee)):
            for cap in range(1, remaining + 1):
                zero = dict(events(contract, law, 0, ready, action, cap))
                one = dict(events(contract, law, 1, ready, action, cap))
                value = -fee
                for event in zero:
                    mass = (1 - belief) * zero[event] + belief * one[event]
                    if not mass:
                        continue
                    after = belief * one[event] / mass
                    future = solve(after, event[2], remaining - event[1], depth - 1)[0]
                    value += mass * (future - contract.time_price * event[1])
                if value > best:
                    best, choice = value, (action, cap)
        return best, choice

    return solve(HALF, 0, contract.deadline, 1 if mode == "myopic" else 2)


def gate_margin(contract, law):
    return law.readiness * (law.accuracy - HALF - contract.probe_cost) - contract.prepare_cost


def closed_form_value(contract, law):
    if contract.deadline < contract.prepare_duration + contract.probe_duration:
        return HALF
    return HALF + max(F(0), gate_margin(contract, law))


def score_estimate(contract, count, ready_count, correct_count):
    if any(type(x) is not int for x in (count, ready_count, correct_count)):
        raise ValueError("integer sample counts required")
    if not 0 <= correct_count <= ready_count <= count or count < 1:
        raise ValueError("complete-chain count ordering required")
    return (F(correct_count, count) - (HALF + contract.probe_cost) * F(ready_count, count)
            - contract.prepare_cost)


def structured_mle(count, ready_count, correct_count):
    if not 0 <= correct_count <= ready_count <= count or count < 1:
        raise ValueError("complete-chain count ordering required")
    accuracy = max(HALF, F(correct_count, ready_count)) if ready_count else HALF
    return Law(F(ready_count, count), accuracy)


def confidence_decision(contract, count, ready_count, correct_count, alpha, checkpoints=1):
    """Hoeffding certificate on a prespecified finite checkpoint grid; no oracle law."""
    alpha = F(str(alpha))
    if not 0 < alpha < 1 or type(checkpoints) is not int or checkpoints < 1:
        raise ValueError("valid total error budget and checkpoint count required")
    if contract.universally_stop:
        return {"decision": "stop", "reason": "known_contract", "radius_exact": "0"}
    estimate = score_estimate(contract, count, ready_count, correct_count)
    # log(x) <= ceil(log2(x)); no floating logarithm or square-root rounding enters admission.
    ratio, power, log_upper = 2 * checkpoints / alpha, 1, 0
    while power < ratio:
        power *= 2
        log_upper += 1
    denominator = 10 ** 6
    numerator = isqrt(log_upper * denominator * denominator // (2 * count))
    if 2 * count * numerator * numerator < log_upper * denominator * denominator:
        numerator += 1
    radius = F(numerator, denominator)
    decision = "prepare" if estimate > radius else "stop" if estimate + radius <= 0 else "unresolved"
    return {"decision": decision, "reason": "conservative_finite_checkpoint_band",
            "estimate": str(estimate), "radius_exact": str(radius), "natural_log_upper_integer": log_upper}
