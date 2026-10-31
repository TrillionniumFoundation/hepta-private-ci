"""Incremental ownership of the frozen v1 cell law, with fair state caching.

This changes the implementation, not the generator, task policy or fitted weights.
Ordinary, distribution and sampled cells all retain their current state. Training
parameter changes require constructing a new owner and replaying causal history.
Snapshots are integrity-checked checkpoints, not hostile-process attestations.
"""
from collections import OrderedDict
import copy
import hashlib
import json
import threading

import numpy as np
from scipy.linalg import expm
from scipy.special import expit

from ..task_value_factorial_20261030.cells import initial, physical
from ..task_value_factorial_20261030.propagation import flow, generator


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class CellOwner:
    """One model identity, stream sequence and RNG per independently owned cell."""

    def __init__(self, family, parameters, mode="distribution", seed=0):
        parameters = np.array(parameters, dtype="<f8", copy=True)
        if (family not in ("ordinary", "analytic") or mode not in ("distribution", "sampled")
                or (family == "ordinary" and mode != "distribution")
                or parameters.shape != (11,) or not np.all(np.isfinite(parameters))
                or np.any(np.abs(parameters) > 3.)):
            raise ValueError("Outside the frozen v1 model family/parameter domain")
        parameters.flags.writeable = False
        self.family, self.mode, self._parameters = family, mode, parameters
        self.parameters_sha256 = hashlib.sha256(parameters.tobytes()).hexdigest()
        self._lock, self._kernels = threading.RLock(), OrderedDict()
        self.sequence, self.elapsed, self.latent_event_count = 0, 0., 0.
        self._rng = np.random.default_rng(seed)
        self._origin = initial(physical(parameters, 0.)) if family == "analytic" else np.array([.5, .5])
        self._state = self._origin.copy()
        self._index = int(self._rng.choice(5, p=self._origin)) if mode == "sampled" else None

    @staticmethod
    def _domain(driver, duration, positive=False):
        if (not np.isfinite(driver) or not np.isfinite(duration) or abs(driver) > 1.
                or duration < 0 or duration > 128 or (positive and duration == 0)):
            raise ValueError("Require |driver|<=1 and finite duration in [0,128]")

    def _kernel(self, driver, duration):
        key = (float(driver), float(duration))
        if key not in self._kernels:
            cell = physical(self._parameters, driver)
            transition, expected, _, _ = flow((cell,), duration)
            q, rates, _, _ = generator((cell,))
            killed = q.copy()
            killed[2, 4] -= rates[2, 0]
            survival = expm(duration*killed)@np.ones(5)
            self._kernels[key] = (transition, expected[:, 0], survival, q)
            if len(self._kernels) > 128:
                self._kernels.popitem(last=False)
        else:
            self._kernels.move_to_end(key)
        return self._kernels[key]

    def query(self, driver, horizon):
        """Return features and the sequence they belong to, without consuming RNG."""
        self._domain(driver, horizon, positive=True)
        with self._lock:
            if self.family == "ordinary":
                rates = np.logaddexp(0., self._parameters[:6].reshape(2, 3)@np.array([1., driver, driver*driver]))
                raw = np.r_[self._state, -np.expm1(-rates*horizon)]
            else:
                _, expected, survival, _ = self._kernel(driver, horizon)
                p = np.eye(5)[self._index] if self.mode == "sampled" else self._state
                count, hit = float(p@expected), 1-float(p@survival)
                if not -2e-11 <= hit <= 1+2e-11 or count+2e-11 < hit:
                    raise ArithmeticError("First-event and repeated-event contract violated")
                raw = np.array([float(p[:3]@np.array([1/6, .5, 5/6])),
                                float(p[3:].sum()), count/(1+count), hit])
            return np.r_[raw, float(expit(raw@self._parameters[6:10]+self._parameters[10]))], self.sequence

    def advance(self, sequence, driver, duration, reset=False):
        """Consume one causal interval exactly once; task reset occurs at its end."""
        self._domain(driver, duration)
        if type(sequence) is not int or type(reset) is not bool:
            raise ValueError("Sequence and reset types must be explicit")
        with self._lock:
            if sequence != self.sequence+1:
                raise ValueError("Duplicate, stale or out-of-order interval")
            if not np.isfinite(self.elapsed+duration):
                raise ValueError("Elapsed time overflow")
            jumps, count = [], 0.
            if self.family == "ordinary":
                rates = np.logaddexp(0., self._parameters[:6].reshape(2, 3)@np.array([1., driver, driver*driver]))
                retain = np.exp(-rates*duration)
                target = np.array([float(expit(2*driver)), driver*driver])
                successor = retain*self._state+(1-retain)*target
                self._state = self._origin.copy() if reset else successor
            elif self.mode == "distribution":
                transition, expected, _, _ = self._kernel(driver, duration)
                count = float(self._state@expected)
                successor = self._state@transition
                if abs(float(successor.sum())-1) > 2e-10 or successor.min() < -2e-12:
                    raise ArithmeticError("State flow lost probability mass")
                self._state = self._origin.copy() if reset else successor
            else:
                # Copy RNG first: a failed interval must not partly consume it.
                rng = np.random.default_rng()
                rng.bit_generator.state = copy.deepcopy(self._rng.bit_generator.state)
                _, _, _, q = self._kernel(driver, duration)
                index, elapsed = self._index, 0.
                while True:
                    holding = float(rng.exponential(1/(-q[index, index])))
                    if elapsed+holding > duration:
                        break
                    elapsed += holding
                    probability = q[index].copy()
                    probability[index] = 0.
                    probability /= probability.sum()
                    next_index = int(rng.choice(5, p=probability))
                    fired = index == 2 and next_index == 4
                    count += int(fired)
                    jumps.append(dict(time=elapsed, before=index, after=next_index, fired=fired))
                    index = next_index
                if reset:
                    index = int(rng.choice(5, p=self._origin))
                self._index, self._rng = index, rng
            self.sequence, self.elapsed = sequence, self.elapsed+duration
            self.latent_event_count += count
            return dict(sequence=sequence, duration=duration, reset=reset, event_count=count,
                        jumps=jumps, state=None if self.mode == "sampled" else self._state.tolist(),
                        sampled_index=self._index)

    def snapshot(self):
        with self._lock:
            rng_state = None
            if self.mode == "sampled":
                rng_state = copy.deepcopy(self._rng.bit_generator.state)
                # PCG64 uses unsigned 128-bit fields. Decimal strings survive
                # JSON consumers whose numeric representation is IEEE float64.
                for name in ("state", "inc"):
                    rng_state["state"][name] = str(rng_state["state"][name])
            record = dict(schema="hcsn.incremental-cell-owner.v2", family=self.family,
                mode=self.mode, parameters_sha256=self.parameters_sha256,
                sequence=self.sequence, elapsed=self.elapsed, latent_event_count=self.latent_event_count,
                state=None if self.mode == "sampled" else self._state.tolist(), sampled_index=self._index,
                rng_state=rng_state)
            return dict(record=record, sha256=hashlib.sha256(canonical_bytes(record)).hexdigest())

    def restore(self, snapshot):
        candidate = copy.deepcopy(snapshot)
        if set(candidate) != {"record", "sha256"}:
            raise ValueError("Checkpoint envelope schema mismatch")
        record = candidate["record"]
        if hashlib.sha256(canonical_bytes(record)).hexdigest() != candidate["sha256"]:
            raise ValueError("Checkpoint byte identity mismatch")
        with self._lock:
            current = self.snapshot()["record"]
            if set(record) != set(current) or any(record[k] != current[k] for k in
                ("schema", "family", "mode", "parameters_sha256")):
                raise ValueError("Checkpoint belongs to another model or contract")
            if (type(record["sequence"]) is not int or record["sequence"] < 0
                    or not np.isfinite(record["elapsed"]) or record["elapsed"] < 0
                    or not np.isfinite(record["latent_event_count"]) or record["latent_event_count"] < -1e-12):
                raise ValueError("Invalid checkpoint clock or event count")
            if self.mode == "sampled":
                if (record["state"] is not None or type(record["sampled_index"]) is not int
                        or not 0 <= record["sampled_index"] < 5):
                    raise ValueError("Invalid sampled state")
                rng = np.random.default_rng()
                rng_state = copy.deepcopy(record["rng_state"])
                if rng_state.get("bit_generator") != "PCG64":
                    raise ValueError("Unknown RNG checkpoint contract")
                for name in ("state", "inc"):
                    value = rng_state["state"][name]
                    if not isinstance(value, str) or not value.isdigit() or not 0 <= int(value) < 2**128:
                        raise ValueError("Invalid PCG64 128-bit state")
                    rng_state["state"][name] = int(value)
                rng.bit_generator.state = rng_state
                self._rng, self._index = rng, record["sampled_index"]
            else:
                state = np.asarray(record["state"], float)
                shape = (2,) if self.family == "ordinary" else (5,)
                if (record["sampled_index"] is not None or record["rng_state"] is not None
                        or state.shape != shape or not np.all(np.isfinite(state))
                        or state.min() < -2e-12 or state.max() > 1+2e-10
                        or (self.family == "analytic" and abs(float(state.sum())-1) > 2e-10)):
                    raise ValueError("Invalid distribution or gate state")
                self._state = state.copy()
            self.sequence, self.elapsed = record["sequence"], record["elapsed"]
            self.latent_event_count = record["latent_event_count"]
            self._kernels.clear()
