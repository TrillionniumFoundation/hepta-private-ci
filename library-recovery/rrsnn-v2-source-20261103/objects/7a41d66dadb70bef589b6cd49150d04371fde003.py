"""Stateful exact Brownian rollout for frozen piecewise-constant coefficients.

This adapter reuses the frozen v0 R1 first-hit and killed-kernel samplers. It
does not change v0. Independent components evolve exactly between observed
coefficient changes, with arbitrary repeat counts and carried deterministic
refractory clocks. Physical evidence Y obeys dY = drift dt + sigma dW and hits
the upper threshold. A model using distance drift mu must pass drift=-mu.

No claim is made that a nonlinear population-mean training feedback equals
sampled-path feedback. A fixed coefficient tape gives a law comparison. A
sampled closed loop must compute new coefficients from its own past outputs.
Continuous spike-triggered coupling requires the separate v0 network engine
or an explicitly implemented delayed event queue, not this independent adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np

from rrsnn_experiments.runtime.event_runtime import (
    sample_first_hit, sample_surviving_endpoint,
)


def _array(value, n, name):
    out = np.broadcast_to(np.asarray(value, dtype=float), (n,)).copy()
    if not np.isfinite(out).all():
        raise ValueError(f"{name} must be finite")
    return out


@dataclass(frozen=True)
class Emission:
    time: float
    component: int
    cause: str
    evidence_before: float


class ExactIndependentRollout:
    """Resume-capable K/S sampled state, with no synthetic initial dt.

    Causal usage at input time t:
        previous_interval_spikes = engine.advance_to(t)
        instantaneous_spikes = engine.observe(drift=..., threshold=..., kick=...)
    Observe never advances time. Advance never reads a future input.
    Coefficients are constant between successive observations.

    All components are independent conditional on supplied coefficient updates.
    Reset and refractory duration are fixed per component during a rollout.
    RNG streams are seed+i; a one-component run can be compared pathwise to v0.
    """

    def __init__(self, initial, *, drift=0.7, sigma=0.4, threshold=1.0,
                 reset=0.0, refractory=0.1, seed=101, initial_time=0.0):
        self.evidence = np.atleast_1d(np.asarray(initial, dtype=float)).copy()
        if self.evidence.ndim != 1 or not len(self.evidence):
            raise ValueError("initial must be a nonempty vector")
        self.n = len(self.evidence)
        self.drift = _array(drift, self.n, "drift")
        self.sigma = _array(sigma, self.n, "sigma")
        self.threshold = _array(threshold, self.n, "threshold")
        self.reset = _array(reset, self.n, "reset")
        self.refractory = _array(refractory, self.n, "refractory")
        self.time = float(initial_time)
        if not math.isfinite(self.time) or not np.isfinite(self.evidence).all():
            raise ValueError("Finite initial state and time required")
        if np.any(self.sigma < 0) or np.any(self.refractory <= 0):
            raise ValueError("Require sigma>=0 and refractory>0")
        if np.any(self.reset >= self.threshold) or np.any(self.evidence >= self.threshold):
            raise ValueError("Require initial and reset below the initial threshold")
        self.refractory_until = np.full(self.n, self.time)
        self.rng = [np.random.default_rng(int(seed)+i) for i in range(self.n)]
        self.count = np.zeros(self.n, dtype=np.int64)
        self.emissions = []
        self.stats = {"survival_proposals": 0, "survival_inversions": 0,
                      "first_hit_draws": 0, "survival_updates": 0,
                      "dropped_refractory_kicks": 0}

    def _fire(self, component, time, cause):
        event = Emission(float(time), int(component), cause, float(self.evidence[component]))
        self.evidence[component] = self.reset[component]
        self.refractory_until[component] = time+self.refractory[component]
        self.count[component] += 1
        self.emissions.append(event)
        return event

    def observe(self, *, drift=None, sigma=None, threshold=None, kick=None):
        """Apply observed inputs at the current clock, without elapsed time.

        Parameter changes remain during refractory periods; evidence kicks are
        discarded then. For active components, changed threshold/kick can cause
        an immediate event. Reset must remain strictly below any new threshold.
        """
        new_drift = self.drift if drift is None else _array(drift, self.n, "drift")
        new_sigma = self.sigma if sigma is None else _array(sigma, self.n, "sigma")
        new_threshold = self.threshold if threshold is None else _array(threshold, self.n, "threshold")
        kicks = np.zeros(self.n) if kick is None else _array(kick, self.n, "kick")
        if np.any(new_sigma < 0) or np.any(new_threshold <= self.reset):
            raise ValueError("Require sigma>=0 and threshold>reset")
        self.drift, self.sigma, self.threshold = new_drift, new_sigma, new_threshold
        new = []
        for i in range(self.n):
            if self.refractory_until[i] > self.time:
                self.stats["dropped_refractory_kicks"] += int(kicks[i] != 0)
                continue
            self.evidence[i] += kicks[i]
            if self.evidence[i] >= self.threshold[i]:
                new.append(self._fire(i, self.time, "input_or_parameter"))
        return new

    def advance_to(self, time, *, max_events_per_component=100000):
        """Advance under the existing coefficients; return actual timed spikes."""
        time = float(time)
        if not math.isfinite(time) or time < self.time:
            raise ValueError("Cannot advance backwards or to nonfinite time")
        if time == self.time:
            return []
        new = []
        for i in range(self.n):
            clock = self.time
            count = 0
            while clock < time:
                if self.refractory_until[i] > clock:
                    clock = min(time, float(self.refractory_until[i]))
                    continue
                distance = self.threshold[i]-self.evidence[i]
                hit = sample_first_hit(self.rng[i], distance, -self.drift[i], self.sigma[i])
                self.stats["first_hit_draws"] += 1
                hit_time = clock+hit
                if hit_time <= time:
                    clock = hit_time
                    self.evidence[i] = self.threshold[i]
                    new.append(self._fire(i, clock, "first_passage"))
                    count += 1
                    if count > max_events_per_component:
                        raise RuntimeError("Event limit exceeded; partial state must not be accepted")
                else:
                    endpoint = sample_surviving_endpoint(self.rng[i], distance,
                        time-clock, -self.drift[i], self.sigma[i], self.stats)
                    self.evidence[i] = self.threshold[i]-endpoint
                    self.stats["survival_updates"] += 1
                    clock = time
        self.time = time
        new.sort(key=lambda event: (event.time, event.component))
        return new

    def snapshot(self):
        return {"time": self.time, "evidence": self.evidence.copy(),
                "refractory_remaining": np.maximum(self.refractory_until-self.time, 0),
                "count": self.count.copy(), "drift": self.drift.copy(),
                "sigma": self.sigma.copy(), "threshold": self.threshold.copy()}

    def checkpoint(self):
        """JSON-safe complete physical/RNG state; PCG128 integers use strings."""
        random_states = []
        for rng in self.rng:
            state = rng.bit_generator.state
            assert state["bit_generator"] == "PCG64"
            random_states.append({"bit_generator": "PCG64",
                "state": {"state": str(state["state"]["state"]),
                          "inc": str(state["state"]["inc"])},
                "has_uint32": int(state["has_uint32"]),
                "uinteger": int(state["uinteger"])})
        return {"schema": "rrsnn.exact-independent-checkpoint.v1", "time": self.time,
                **{name: getattr(self, name).tolist() for name in
                   ("evidence", "refractory_until", "drift", "sigma", "threshold",
                    "reset", "refractory", "count")}, "rng": random_states}

    @classmethod
    def from_checkpoint(cls, state):
        """Restore future paths exactly under the same NumPy implementation."""
        if state["schema"] != "rrsnn.exact-independent-checkpoint.v1":
            raise ValueError("Unknown exact-rollout checkpoint schema")
        instance = cls(state["evidence"], drift=state["drift"], sigma=state["sigma"],
            threshold=state["threshold"], reset=state["reset"],
            refractory=state["refractory"], initial_time=state["time"])
        instance.refractory_until = _array(state["refractory_until"], instance.n,
                                           "refractory_until")
        count = np.asarray(state["count"])
        if count.shape != (instance.n,) or np.any(count < 0) or np.any(count != count.astype(np.int64)):
            raise ValueError("Invalid spike counts")
        instance.count = count.astype(np.int64)
        if len(state["rng"]) != instance.n:
            raise ValueError("One RNG state per component required")
        for rng, serialized in zip(instance.rng, state["rng"]):
            if serialized["bit_generator"] != "PCG64":
                raise ValueError("PCG64 random state required")
            rng.bit_generator.state = {"bit_generator": "PCG64",
                "state": {"state": int(serialized["state"]["state"]),
                          "inc": int(serialized["state"]["inc"])},
                "has_uint32": int(serialized["has_uint32"]),
                "uinteger": int(serialized["uinteger"])}
        return instance


def replay_coefficient_tape(initial, times, drifts, thresholds, *, sigma=0.4,
                            reset=0.0, refractory=0.1, kicks=None, seed=101):
    """Fixed learned-coefficient tape, with time0 coefficients observed at time0.

    times has length T+1, drifts and thresholds have shape [T,N] (or scalar
    component broadcasts), and returned counts are [T,N]. The final boundary
    applies no new parameters. All crossing times are retained.
    """
    times = np.asarray(times, dtype=float)
    drifts, thresholds = np.asarray(drifts), np.asarray(thresholds)
    if len(times) < 2 or np.any(np.diff(times) <= 0):
        raise ValueError("Strictly increasing interval boundaries required")
    if len(drifts) != len(times)-1 or len(thresholds) != len(times)-1:
        raise ValueError("One coefficient entry per interval required")
    engine = ExactIndependentRollout(initial, drift=drifts[0], threshold=thresholds[0],
        sigma=sigma, reset=reset, refractory=refractory, seed=seed, initial_time=times[0])
    interval_counts, interval_spikes = [], []
    for k in range(len(times)-1):
        before = engine.count.copy()
        current_kick = None if kicks is None else kicks[k]
        spikes = engine.observe(drift=drifts[k], threshold=thresholds[k], kick=current_kick)
        spikes += engine.advance_to(times[k+1])
        interval_counts.append(engine.count-before)
        interval_spikes.append(spikes)
    return {"counts": np.stack(interval_counts), "spikes": interval_spikes,
            "final": engine.snapshot(), "stats": engine.stats}
