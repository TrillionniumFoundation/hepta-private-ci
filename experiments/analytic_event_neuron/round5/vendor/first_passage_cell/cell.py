"""Exact segmented first-passage cell with renewal resets and replayable state.

The state owner is this research cell, not a hidden state in a prediction head.
Known internal voltage has physical units; barrier and reset gap are distinct.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.optimize import brentq

from .kernels import first_passage, killed_cdf

PROFILE = "hepta-first-passage-cell-v1"


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


@dataclass(frozen=True)
class CellParameters:
    """Selected immutable physical model; reset_gap is measured above barrier."""

    drift: float
    weights: tuple
    sigma: float
    barrier: float
    reset_gap: float
    refractory: float = 0.06
    interaction: float = 0.0

    def __post_init__(self):
        vals = (self.drift, *self.weights, self.sigma, self.barrier,
                self.reset_gap, self.refractory, self.interaction)
        if len(self.weights) != 2 or not all(math.isfinite(v) for v in vals):
            raise ValueError("Two finite input weights and finite coefficients required")
        if self.sigma <= 0 or self.reset_gap <= 0 or self.refractory <= 0:
            raise ValueError("Positive sigma, reset gap and refractory period required")
        if self.refractory < 1e-6:
            raise ValueError("Refractory period below the registered runtime floor")

    def mu(self, inputs):
        values = np.asarray(inputs, dtype=np.float64)
        if values.shape != (2,) or not np.isfinite(values).all():
            raise ValueError("Exactly two finite public inputs are required")
        result = float(self.drift + np.dot(self.weights, values)
                       + self.interaction * values[0] * values[1])
        if not math.isfinite(result):
            raise ValueError("Public input produced a non-finite drift")
        return result

    def digest(self):
        return hashlib.sha256(canonical_bytes(asdict(self))).hexdigest()


class CounterRandom:
    """Separate Philox stream per named draw, identified by a retained counter."""

    def __init__(self, seed, counter=0):
        if type(seed) is not int or type(counter) is not int or seed < 0 or counter < 0:
            raise ValueError("Nonnegative integer seed and counter required")
        self.seed = seed
        self.counter = counter

    def generator(self, label):
        raw = canonical_bytes([PROFILE, self.seed, self.counter, str(label)])
        key = int.from_bytes(hashlib.blake2b(raw, digest_size=16).digest(), "little")
        self.counter += 1
        return np.random.Generator(np.random.Philox(key))


def sample_hitting_time(distance, drift, sigma, rng):
    """Exact defective inverse-Gaussian law, including an atom at infinity.

    Positive drift has eventual-hit probability exp(-2*drift*distance/sigma**2).
    Conditional on a hit its time law equals that for negative absolute drift.
    This sampler does not call the analytic CDF used for training.
    """
    if not all(math.isfinite(v) for v in (distance, drift, sigma)) or sigma <= 0:
        raise ValueError("Finite distance/drift and positive finite sigma required")
    if distance <= 0:
        return 0.0
    log_x, log_sigma = math.log(distance), math.log(sigma)
    if drift > 0:
        log_exponent = math.log(2.0) + math.log(drift) + log_x - 2 * log_sigma
        eventual_hit = 0.0 if log_exponent > 7.0 else math.exp(-math.exp(log_exponent))
        if rng.random() >= eventual_hit:
            return math.inf
    z = abs(float(rng.standard_normal()))
    if drift == 0:
        if z == 0:
            raise ArithmeticError("Unrepresentable zero-normal Levy draw")
        log_time = 2 * (log_x - log_sigma - math.log(z))
    else:
        log_mean = log_x - math.log(abs(drift))
        # Rationalized Michael--Schucany--Haas root. numpy.wald subtracts
        # two large nearly equal values and can return a false t=0 atom as
        # drift tends to zero. log(D)=2*asinh(sqrt(y/2)) avoids subtraction.
        log_y = (-math.inf if z == 0 else
                 2 * log_sigma + 2 * math.log(z) - math.log(2.0)
                 - log_x - math.log(abs(drift)))
        log_denominator = (log_y + math.log(2.0) if log_y > 700 else
                           2 * math.asinh(math.exp(0.5 * (log_y - math.log(2.0)))))
        log_time = log_mean - log_denominator
        if rng.random() > 1 / (1 + math.exp(-log_denominator)):
            log_time = log_mean + log_denominator
    if not math.log(np.nextafter(0.0, 1.0)) <= log_time <= math.log(np.finfo(float).max):
        raise ArithmeticError("Hitting-time draw is outside representable positive time")
    result = math.exp(log_time)
    if not math.isfinite(result) or result <= 0:
        raise ArithmeticError("Hitting-time draw must be finite and strictly positive")
    return result


def sample_survivor(distance, drift, sigma, duration, rng):
    """Sample the terminal state conditional on no hit, by inverse killed CDF."""
    if duration == 0:
        return float(distance)
    survival = float(first_passage(distance, drift, sigma, duration)["S"])
    if not math.isfinite(survival) or survival <= 0:
        raise ArithmeticError("Survival endpoint has no representable positive mass")
    # Brownian-bridge rejection is exact and cheap on the ordinary operating
    # domain. Each accepted endpoint has density k_T / S. Quantile fallback
    # bounds work in the rare low-survival region; this is not Euler stepping.
    if survival >= 0.12:
        variance = sigma * sigma * duration
        for _ in range(64):
            proposal = float(rng.normal(distance + drift * duration, math.sqrt(variance)))
            if proposal > 0:
                bridge_survival = -math.expm1(-2 * distance * proposal / variance)
                if rng.random() < bridge_survival:
                    return proposal
    uniform = float(rng.random())
    uniform = min(max(uniform, np.finfo(float).eps), 1.0 - np.finfo(float).eps)
    target = uniform * survival
    if not 0 < target < survival:
        raise ArithmeticError("Conditional survival quantile is not representable")
    scale = sigma * math.sqrt(duration)
    upper = max(distance + drift * duration + 9 * scale, 9 * scale, distance, 1e-8)
    for _ in range(24):
        if float(killed_cdf(distance, upper, drift, sigma, duration)) >= target:
            break
        upper *= 2
    else:
        raise ArithmeticError("Could not bracket survival conditional quantile")
    result = float(brentq(
        lambda y: float(killed_cdf(distance, y, drift, sigma, duration)) - target,
        0.0, upper, xtol=1e-12, rtol=1e-12,
    ))
    if not math.isfinite(result) or result <= 0:
        raise ArithmeticError("Surviving endpoint must be finite and above the boundary")
    return result


class FirstPassageCell:
    """Known-state continuous cell, with exact local propagation and hard events."""

    def __init__(self, parameters, initial_level, seed, state=None):
        self.parameters = parameters
        if not math.isfinite(initial_level):
            raise ValueError("Finite initial level required")
        self.level = float(initial_level)
        self.time = 0.0
        self.refractory_remaining = 0.0
        self.event_count = 0
        self.rng = CounterRandom(seed)
        if state is not None:
            raise ValueError("Use from_checkpoint for versioned state restoration")

    def repair(self):
        """Explicit intervention, distinct from a naturally occurring spike."""
        self.level = self.parameters.barrier + self.parameters.reset_gap
        self.refractory_remaining = self.parameters.refractory

    def advance(self, duration, inputs):
        """Apply one supported segment atomically, including the random counter."""
        if not math.isfinite(duration) or not 0 <= duration <= 10:
            raise ValueError("Duration must be finite and in [0,10]")
        if math.ceil(duration / self.parameters.refractory) + 2 > 128:
            raise ValueError("Segment/refractory combination exceeds the 128-event bound")
        self.parameters.mu(inputs)
        previous = (self.level, self.time, self.refractory_remaining,
                    self.event_count, self.rng.counter)
        try:
            return self._advance_segment(duration, inputs)
        except Exception:
            (self.level, self.time, self.refractory_remaining,
             self.event_count, self.rng.counter) = previous
            raise

    def _advance_segment(self, duration, inputs):
        if not math.isfinite(duration) or not 0 <= duration <= 10:
            raise ValueError("Duration must be finite and in [0,10]")
        p = self.parameters
        drift = p.mu(inputs)
        begin = self.time
        remaining = float(duration)
        active = 0.0
        events = []
        max_events = int(math.ceil(duration / p.refractory)) + 2
        while remaining > 0 or (self.refractory_remaining == 0 and self.level <= p.barrier):
            if self.refractory_remaining > 0:
                consumed = min(remaining, self.refractory_remaining)
                self.refractory_remaining -= consumed
                remaining -= consumed
                self.time += consumed
                if remaining <= 1e-14:
                    remaining = 0.0
                    break
            distance = self.level - p.barrier
            hit = sample_hitting_time(distance, drift, p.sigma,
                                      self.rng.generator("hitting_time"))
            if hit <= remaining:
                self.time += hit
                remaining -= hit
                active += hit
                self.event_count += 1
                events.append({"time": self.time, "kind": "first_passage",
                               "ordinal": self.event_count})
                self.level = p.barrier + p.reset_gap
                self.refractory_remaining = p.refractory
                if len(events) > max_events:
                    raise ArithmeticError("Event count exceeds refractory bound")
            else:
                end_distance = sample_survivor(
                    distance, drift, p.sigma, remaining,
                    self.rng.generator("survival_endpoint"),
                )
                self.level = p.barrier + end_distance
                active += remaining
                self.time += remaining
                remaining = 0.0
        # Exact requested logical clock prevents split arithmetic from accumulating.
        self.time = begin + duration
        return {
            "profile": PROFILE, "model_digest": p.digest(),
            "start_time": begin, "time": self.time, "level": self.level,
            "elapsed_duration": duration, "active_duration": active,
            "refractory_remaining": self.refractory_remaining,
            "failure_count": len(events), "events": events,
            "random_counter": self.rng.counter,
        }

    def checkpoint(self):
        payload = {
            "profile": PROFILE, "parameters": asdict(self.parameters),
            "model_digest": self.parameters.digest(), "level": self.level,
            "time": self.time, "refractory_remaining": self.refractory_remaining,
            "event_count": self.event_count, "seed": self.rng.seed,
            "random_counter": self.rng.counter,
        }
        return {"payload": payload,
                "sha256": hashlib.sha256(canonical_bytes(payload)).hexdigest()}

    @classmethod
    def from_checkpoint(cls, checkpoint, expected_model_digest):
        if set(checkpoint) != {"payload", "sha256"}:
            raise ValueError("Malformed checkpoint envelope")
        value = checkpoint["payload"]
        if hashlib.sha256(canonical_bytes(value)).hexdigest() != checkpoint["sha256"]:
            raise ValueError("Checkpoint digest mismatch")
        required = {"profile", "parameters", "model_digest", "level", "time",
                    "refractory_remaining", "event_count", "seed", "random_counter"}
        if set(value) != required or value["profile"] != PROFILE:
            raise ValueError("Unsupported checkpoint fields or profile")
        data = dict(value["parameters"])
        data["weights"] = tuple(data["weights"])
        parameters = CellParameters(**data)
        if value["model_digest"] != expected_model_digest or parameters.digest() != expected_model_digest:
            raise ValueError("Selected model differs from checkpoint model")
        if not all(math.isfinite(value[k]) for k in ("level", "time", "refractory_remaining")):
            raise ValueError("Non-finite checkpoint state")
        if value["time"] < 0 or not 0 <= value["refractory_remaining"] <= parameters.refractory:
            raise ValueError("Invalid checkpoint time/refractory state")
        if (value["refractory_remaining"] > 0 and
                value["level"] != parameters.barrier + parameters.reset_gap):
            raise ValueError("Refractory state is not at the selected reset level")
        if type(value["event_count"]) is not int or value["event_count"] < 0:
            raise ValueError("Invalid event count")
        cell = cls(parameters, value["level"], value["seed"])
        cell.time = value["time"]
        cell.refractory_remaining = value["refractory_remaining"]
        cell.event_count = value["event_count"]
        cell.rng = CounterRandom(value["seed"], value["random_counter"])
        return cell

    def save_checkpoint(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = canonical_bytes(self.checkpoint()) + b"\n"
        with path.open("xb") as stream:
            stream.write(content)
        return hashlib.sha256(content).hexdigest()
