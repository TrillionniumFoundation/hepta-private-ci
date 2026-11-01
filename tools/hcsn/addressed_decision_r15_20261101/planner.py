"""Shared addressed state and exact finite-deadline action enumeration.

The controller is optimal only for the current query under its supplied model,
three public time slots, and READ/WAIT/REFRESH/STOP action set. It does not
optimize the value of retaining information for the later five queries.
"""

import hashlib
import json
import time

import numpy as np


ACTIONS = ("STOP", "WAIT", "READ", "REFRESH")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class BeliefMemory:
    """Four explicit public addresses; each core owns its own state estimate."""

    def __init__(self, law, initial_values, projection="full", method="expm"):
        self.law, self.projection, self.method = law, projection, method
        self.beliefs = np.tile(law.prior, (4, 1))
        self.clock = 0.
        self.operations = dict(propagations=0, observations=0, writes=0)
        if len(initial_values) != 4:
            raise ValueError("Exactly four public initial writes are required")
        for key, value in enumerate(initial_values):
            self.write(key, int(value))

    def advance(self, dt):
        if not np.isfinite(dt) or dt < 0:
            raise ValueError("Time must be finite and nonnegative")
        if dt:
            self.beliefs = self.law.project(
                self.beliefs @ self.law.transition(float(dt), method=self.method),
                self.projection)
            self.clock += float(dt)
            self.operations["propagations"] += 4

    def observe(self, key, token, quality):
        if quality not in ("read", "refresh") or not 0 <= key < 4:
            raise ValueError("Unknown observation quality or address")
        emission = self.law.E_read if quality == "read" else self.law.E_refresh
        if not isinstance(token, (int, np.integer)) or not 0 <= token < emission.shape[1]:
            raise ValueError("Invalid observation token")
        unnormalized = self.beliefs[key] * emission[:, token]
        mass = float(unnormalized.sum())
        if mass <= 0:
            raise ValueError("Impossible observation")
        self.beliefs[key] = self.law.project(unnormalized / mass, self.projection)
        self.operations["observations"] += 1

    def write(self, key, value):
        if not 0 <= key < 4 or not 0 <= value < 4:
            raise ValueError("Invalid public typed write")
        phase = self.beliefs[key].reshape(10, 4).sum(axis=1)
        joint = np.zeros((10, 4))
        joint[:, value] = phase
        self.beliefs[key] = joint.ravel()
        self.operations["writes"] += 1

    def checkpoint(self):
        body = dict(schema="hcsn-r15-addressed-state-v1", model=self.law.identity,
                    clock=self.clock, beliefs=self.beliefs.tolist(),
                    projection=self.projection, method=self.method,
                    operations=self.operations.copy())
        body["sha256"] = hashlib.sha256(canonical(body).encode()).hexdigest()
        return body

    @classmethod
    def restore(cls, law, payload):
        body = dict(payload)
        digest = body.pop("sha256", None)
        if digest != hashlib.sha256(canonical(body).encode()).hexdigest():
            raise ValueError("Checkpoint checksum mismatch")
        if body["schema"] != "hcsn-r15-addressed-state-v1" or body["model"] != law.identity:
            raise ValueError("Checkpoint model/schema mismatch")
        p = np.asarray(body["beliefs"], dtype=float)
        if (p.shape != (4, 40) or not np.isfinite(p).all() or p.min() < -1e-13
                or not np.allclose(p.sum(axis=1), 1, rtol=0, atol=1e-11)
                or not np.isfinite(body["clock"]) or body["clock"] < 0):
            raise ValueError("Invalid checkpoint state")
        result = cls(law, [0, 0, 0, 0], body["projection"], body["method"])
        result.clock, result.beliefs = float(body["clock"]), p.copy()
        result.operations = dict(body["operations"])
        return result


class Planner:
    """Same finite-deadline value controller for every causal state estimator."""

    def __init__(self, law, dt, read_cost=.025, refresh_cost=.07, time_price=.003,
                 projection="full", method="expm"):
        if not np.isfinite([dt, read_cost, refresh_cost, time_price]).all() or dt <= 0:
            raise ValueError("Invalid public prices or interval")
        if min(read_cost, refresh_cost, time_price) < 0:
            raise ValueError("Costs must be nonnegative")
        self.law, self.dt, self.projection, self.method = law, float(dt), projection, method
        self.read_cost, self.refresh_cost, self.time_price = read_cost, refresh_cost, time_price
        started = time.process_time()
        self.P = {h: law.transition(h * self.dt, method=method) for h in range(4)}
        self.reward_at = {h: matrix @ law.reward for h, matrix in self.P.items()}
        self.preparation_cpu = time.process_time() - started
        self.calls = 0
        self.belief_evaluations = 0

    def _values(self, p, remaining):
        p = np.asarray(p, dtype=float).reshape(-1, 40)
        self.belief_evaluations += len(p)
        stop = np.max(p @ self.reward_at[remaining], axis=1)
        result = np.full((len(p), 4), -np.inf)
        result[:, 0] = stop
        if remaining == 0:
            return result
        propagated = self.law.project(p @ self.P[1], self.projection)
        result[:, 1] = np.max(self._values(propagated, remaining - 1), axis=1) - self.time_price * self.dt
        for column, slots, emission, fee in (
                (2, 1, self.law.E_read, self.read_cost),
                (3, 2, self.law.E_refresh, self.refresh_cost)):
            if slots > remaining:
                continue
            before = self.law.project(p @ self.P[slots], self.projection)
            joint = before[:, None, :] * emission.T[None, :, :]
            likelihood = joint.sum(axis=-1)
            posterior = np.divide(joint, likelihood[..., None], out=np.zeros_like(joint),
                                  where=likelihood[..., None] > 0)
            impossible = likelihood <= 0
            posterior[impossible] = self.law.prior
            posterior = self.law.project(posterior, self.projection)
            successor = np.max(self._values(posterior.reshape(-1, 40), remaining - slots), axis=1)
            expected = np.sum(likelihood * successor.reshape(likelihood.shape), axis=1)
            result[:, column] = expected - fee - slots * self.dt * self.time_price
        return result

    def values(self, p, remaining):
        if not isinstance(remaining, (int, np.integer)) or not 0 <= remaining <= 3:
            raise ValueError("Remaining slots must be 0..3")
        self.calls += 1
        values = self._values(np.asarray(p)[None, :], int(remaining))[0]
        return {action: float(value) for action, value in zip(ACTIONS, values) if np.isfinite(value)}

    def choose(self, p, remaining):
        values = self.values(p, remaining)
        # Fixed tie priority, never a candidate-specific tolerance or rule.
        return max(values, key=values.get)

    def answer(self, p, remaining):
        return int(np.argmax(np.asarray(p) @ self.reward_at[int(remaining)]))


def features(law, p, dt, remaining, read_cost, refresh_cost):
    """Public causal controller features; no target, future token or latent state."""
    p = np.asarray(p)
    classes = p.reshape(10, 4).sum(axis=0)
    sorted_p = np.sort(classes)
    mean_phase = float(p.reshape(10, 4).sum(axis=1) @ np.arange(10)) / 9
    remaining_time = float(dt * remaining)
    continue_value = float(np.max(p @ law.transition(remaining_time) @ law.reward))
    risk = float(law.first_hit(p, remaining_time))
    entropy = -float(np.sum(classes * np.log(np.maximum(classes, 1e-300))))
    return np.array([1., mean_phase, sorted_p[-1], sorted_p[-1] - sorted_p[-2],
                     remaining_time, read_cost, refresh_cost, entropy, continue_value, risk])
