"""Positive forward equation with a complete deterministic-recovery checkpoint.

The discretization carries a full active-position law and an age-advection
queue. Checkpoints preserve the fixed lattice; a new observation does not
reinitialize the dynamics or rebuild its time grid. This is a numerical
reference process, not a neural content model.
"""

import hashlib
import json
import math
from pathlib import Path

import numpy as np


def digest(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


class AgePDE:
    """Fixed-coefficient absorbing diffusion plus delayed reset and age state."""

    schema = "hcsn.r13.age-pde.checkpoint.v1"

    def __init__(self, case, spacing, upper=8.0, cfl=0.4):
        names = ("x", "mu", "sigma", "horizon", "reset", "refractory")
        if set(case) != set(names):
            raise ValueError("A complete six-parameter process identity is required")
        self.case = {name: float(case[name]) for name in names}
        if not all(math.isfinite(v) for v in self.case.values()):
            raise ValueError("Finite process parameters required")
        if min(self.case[n] for n in names if n != "mu") <= 0:
            raise ValueError("Positive interior, noise, horizon, reset and refractory required")
        if not all(math.isfinite(v) and v > 0 for v in (spacing, upper, cfl)):
            raise ValueError("Finite positive grid specification required")
        self.upper, self.cfl = float(upper), float(cfl)
        intervals = int(round(upper / spacing))
        if intervals < 3:
            raise ValueError("Spatial grid requires at least two interior nodes")
        self.h = upper / intervals
        self.positions = np.arange(1, intervals) * self.h
        d, sigma = self.case["refractory"], self.case["sigma"]
        self.age_steps = int(math.ceil(d * sigma * sigma / (cfl * self.h**2)))
        self.dt = d / self.age_steps
        periods = self.case["horizon"] / d
        if abs(periods - round(periods)) > 1e-12:
            raise ValueError("This reference requires an integral number of refractory periods")
        self.total_steps = round(periods) * self.age_steps
        diffusion = sigma * sigma / 2
        self.up = diffusion / self.h**2 + self.case["mu"] / (2 * self.h)
        self.down = diffusion / self.h**2 - self.case["mu"] / (2 * self.h)
        if min(self.up, self.down) < 0 or self.dt * (self.up + self.down) > 1:
            raise ArithmeticError("Positivity/CFL violation; rates are never clipped")
        self.active = self._atom(self.case["x"])
        self.reset_law = self._atom(self.case["reset"])
        self.queue = np.zeros(self.age_steps)
        self.cursor = 0
        self.step = 0
        self.count = 0.0
        self.upper_loss = 0.0
        self.minimum = 0.0
        self.identity = {
            "case": self.case,
            "spacing": self.h,
            "upper": self.upper,
            "cfl": self.cfl,
            "dt": self.dt,
            "age_steps": self.age_steps,
            "total_steps": self.total_steps,
            "interior_nodes": len(self.positions),
            "up_rate": self.up,
            "down_rate": self.down,
            "queue_layout": "cursor releases oldest next; cursor-1 is youngest",
        }
        self.identity_hash = digest(self.identity)

    def _atom(self, position):
        coordinate = position / self.h - 1
        left = math.floor(coordinate)
        if left < 0 or left + 1 >= len(self.positions):
            raise ValueError("Initial/reset location must lie inside spatial grid")
        law = np.zeros_like(self.positions)
        law[left:left + 2] = [left + 1 - coordinate, coordinate - left]
        return law

    @property
    def time(self):
        return self.step * self.dt

    def advance_to_step(self, target):
        if isinstance(target, bool) or not isinstance(target, int):
            raise ValueError("An integer step is required")
        if target < self.step or target > self.total_steps:
            raise ValueError("Requested step outside the remaining fixed horizon")
        while self.step < target:
            hit = self.dt * self.down * self.active[0]
            loss = self.dt * self.up * self.active[-1]
            release = self.queue[self.cursor]
            updated = (1 - self.dt * (self.up + self.down)) * self.active
            updated[1:] += self.dt * self.up * self.active[:-1]
            updated[:-1] += self.dt * self.down * self.active[1:]
            updated += release * self.reset_law
            self.queue[self.cursor] = hit
            self.cursor = (self.cursor + 1) % self.age_steps
            self.active = updated
            self.count += hit
            self.upper_loss += loss
            self.minimum = min(self.minimum, float(updated.min()), float(hit))
            self.step += 1

    def advance_to_time(self, target):
        if not math.isfinite(target):
            raise ValueError("Finite physical time required")
        coordinate = target / self.dt
        step = round(coordinate)
        if abs(coordinate - step) > 32 * np.finfo(float).eps * max(1, abs(coordinate)):
            raise ValueError("Time does not align with this checkpoint's fixed lattice")
        self.advance_to_step(step)

    def age_law(self):
        """Return ascending-age bin mass; do not discard recovery history."""
        indices = (self.cursor - 1 - np.arange(self.age_steps)) % self.age_steps
        return self.queue[indices]

    def observables(self, active_edges, age_edges):
        active_bins = []
        for lo, hi in zip(active_edges[:-1], active_edges[1:]):
            overlap = np.maximum(0.0, np.minimum(self.positions + self.h / 2, hi)
                                 - np.maximum(self.positions - self.h / 2, lo)) / self.h
            active_bins.append(float(self.active @ overlap))
        ages = np.arange(self.age_steps) * self.dt
        age_law = self.age_law()
        age_bins = []
        for lo, hi in zip(age_edges[:-1], age_edges[1:]):
            overlap = np.maximum(0.0, np.minimum(ages + self.dt, hi)
                                 - np.maximum(ages, lo)) / self.dt
            age_bins.append(float(age_law @ overlap))
        age_moments = [float(age_law.sum()), float(age_law @ (ages + self.dt / 2)),
                       float(age_law @ (ages * ages + ages * self.dt + self.dt**2 / 3))]
        return {
            "time": self.time,
            "step": self.step,
            "event_count": self.count,
            "active_moments": [float(self.active.sum()), float(self.active @ self.positions),
                               float(self.active @ (self.positions * self.positions))],
            "active_bins": active_bins,
            "age_moments": age_moments,
            "age_bins": age_bins,
            "accounted_mass": float(self.active.sum() + self.queue.sum()) + self.upper_loss,
            "upper_loss": self.upper_loss,
            "minimum_probability": self.minimum,
        }

    def checkpoint(self):
        payload = {
            "schema": self.schema,
            "identity": self.identity,
            "identity_sha256": self.identity_hash,
            "step": self.step,
            "physical_time": self.time,
            "active_probability": self.active.tolist(),
            "refractory_queue": self.queue.tolist(),
            "queue_cursor": self.cursor,
            "event_count": float(self.count),
            "upper_loss": float(self.upper_loss),
            "minimum_probability": float(self.minimum),
        }
        return {"payload": payload, "payload_sha256": digest(payload)}

    def write_checkpoint(self, path):
        with Path(path).open("x") as stream:
            json.dump(self.checkpoint(), stream, sort_keys=True, allow_nan=False)

    @classmethod
    def restore(cls, document, expected_identity):
        if set(document) != {"payload", "payload_sha256"}:
            raise ValueError("Incomplete checkpoint envelope")
        payload = document["payload"]
        if digest(payload) != document["payload_sha256"]:
            raise ValueError("Checkpoint payload hash mismatch")
        fields = {"schema", "identity", "identity_sha256", "step", "physical_time",
                  "active_probability", "refractory_queue", "queue_cursor", "event_count",
                  "upper_loss", "minimum_probability"}
        if set(payload) != fields or payload["schema"] != cls.schema:
            raise ValueError("Incomplete or unsupported physical-state checkpoint")
        identity = payload["identity"]
        state = cls(identity["case"], identity["spacing"], identity["upper"], identity["cfl"])
        if (state.identity != identity or state.identity_hash != payload["identity_sha256"]
                or state.identity_hash != expected_identity):
            raise ValueError("Process or grid identity mismatch")
        step, cursor = payload["step"], payload["queue_cursor"]
        if (type(step) is not int or type(cursor) is not int
                or not 0 <= step <= state.total_steps or not 0 <= cursor < state.age_steps
                or cursor != step % state.age_steps):
            raise ValueError("Inconsistent clock or recovery cursor")
        if payload["physical_time"] != step * state.dt:
            raise ValueError("Physical clock differs from fixed-lattice clock")
        active = np.asarray(payload["active_probability"], dtype=float)
        queue = np.asarray(payload["refractory_queue"], dtype=float)
        if active.shape != state.active.shape or queue.shape != state.queue.shape:
            raise ValueError("Incomplete state-array shape")
        scalars = [payload[key] for key in ("event_count", "upper_loss", "minimum_probability")]
        if (not np.all(np.isfinite(active)) or not np.all(np.isfinite(queue))
                or not all(math.isfinite(v) for v in scalars)
                or min(float(active.min()), float(queue.min()), scalars[0], scalars[1]) < 0):
            raise ValueError("Nonfinite or negative physical probability/count")
        if abs(float(active.sum() + queue.sum()) + payload["upper_loss"] - 1) > 2e-10:
            raise ValueError("Checkpoint probability mass is incomplete")
        state.active, state.queue = active, queue
        state.step, state.cursor = step, cursor
        state.count, state.upper_loss, state.minimum = scalars
        return state
