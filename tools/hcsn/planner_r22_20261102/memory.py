"""Support-preserving active/recovery compression for the frozen R15 law.

Eight stored masses retain group--content dependence; phase shape is discarded.
The packed transition R exp(t Q) C is an approximation, not a semigroup.
"""

import hashlib
import json

import numpy as np

from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.planner import BeliefMemory as OriginalBeliefMemory, canonical
from ..support_retention_r16_20261101.compression import COLLECT, SPREAD, GROUP


def normalized_rows(p, tolerance):
    """Exact scalar-one, rtol-zero predicate after the original dtype checks."""
    return np.all(np.abs(p.sum(-1) - 1.) <= tolerance)


def _probability(value, size):
    p = np.asarray(value, dtype=float)
    if (p.ndim < 1 or p.shape[-1] != size or not np.isfinite(p).all()
            or np.any(p < 0) or not normalized_rows(p, 2e-11)):
        raise ValueError(f"Expected nonnegative normalized {size}-state probability")
    return p


def pack(p):
    """Return eight active/recovery by content masses, preserving leading axes."""
    return _probability(p, 40) @ COLLECT


def unpack(packed):
    """Uniform phase shape within each group; no probability floor or clipping."""
    packed = _probability(packed, 8)
    expanded = packed @ SPREAD
    if np.any((packed[..., GROUP] > 0) & (expanded == 0)):
        raise ValueError("Positive support is unrepresentable at this floating-point scale")
    return expanded


class BlockLaw(Law):
    """The original forty-state law plus a separately named block projection."""

    def _belief(self, belief):
        p = np.asarray(belief, dtype=float)
        if (p.ndim < 1 or p.shape[-1] != self.state_count or not np.isfinite(p).all()
                or np.any(p < -1e-13) or not normalized_rows(p, 2e-11)):
            raise ValueError("Belief must be normalized with final dimension 40")
        return p


    def project(self, p, mode="full"):
        if mode == "block":
            return unpack(pack(p))
        return super().project(p, mode)


class PackedBeliefMemory:
    """Four addresses storing 4 x 8 FP64 masses, with explicit temporary expansion.

    Model matrices, cached transitions and planner workspaces are not included in
    the 256-byte belief-storage count. Planning still uses the forty-state API.
    """

    def __init__(self, law, initial_values, projection="block", method="expm"):
        if projection != "block" or method != "expm":
            raise ValueError("Packed memory requires block projection and expm propagation")
        self.law = law
        self.packed = np.tile(pack(law.prior), (4, 1))
        self.clock = 0.
        self.operations = dict(propagations=0, observations=0, writes=0)
        self._transitions = {}
        self._emissions = {}
        for quality, emission in (("read", law.E_read), ("refresh", law.E_refresh)):
            reduced = SPREAD @ emission
            if not np.allclose(COLLECT @ reduced, emission, rtol=0, atol=2e-15):
                raise ValueError("Emission varies inside the declared phase group")
            self._emissions[quality] = reduced
        if len(initial_values) != 4:
            raise ValueError("Exactly four public initial writes are required")
        for key, value in enumerate(initial_values):
            self.write(key, value)

    @property
    def beliefs(self):
        """Temporary forty-state view; it is not the persistent memory."""
        return unpack(self.packed)

    def advance(self, dt):
        dt = self.law._duration(dt)
        if dt:
            if dt not in self._transitions:
                self._transitions[dt] = SPREAD @ self.law.transition(dt) @ COLLECT
            self.packed = _probability(self.packed @ self._transitions[dt], 8)
            self.clock += dt
            self.operations["propagations"] += 4

    def observe(self, key, token, quality):
        if quality not in self._emissions or not isinstance(key, (int, np.integer)) or not 0 <= key < 4:
            raise ValueError("Unknown observation quality or address")
        emission = self._emissions[quality]
        if not isinstance(token, (int, np.integer)) or not 0 <= token < emission.shape[1]:
            raise ValueError("Invalid observation token")
        unnormalized = self.packed[key] * emission[:, token]
        mass = float(unnormalized.sum())
        if mass <= 0:
            raise ValueError("Impossible observation")
        self.packed[key] = _probability(unnormalized / mass, 8)
        self.operations["observations"] += 1

    def write(self, key, value):
        if (not isinstance(key, (int, np.integer)) or not isinstance(value, (int, np.integer))
                or not 0 <= key < 4 or not 0 <= value < 4):
            raise ValueError("Invalid public typed write")
        masses = self.packed[key].reshape(2, 4).sum(1)
        self.packed[key] = 0.
        self.packed[key, [value, 4 + value]] = masses
        self.operations["writes"] += 1

    def checkpoint(self):
        body = dict(schema="hcsn-r16-packed-state-v1", model=self.law.identity,
                    clock=self.clock, packed=self.packed.tolist(), operations=self.operations.copy())
        body["sha256"] = hashlib.sha256(json.dumps(
            body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        return body

    @classmethod
    def restore(cls, law, payload):
        body = dict(payload)
        checksum = body.pop("sha256", None)
        expected = hashlib.sha256(json.dumps(
            body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        if checksum != expected or body.get("schema") != "hcsn-r16-packed-state-v1" or body.get("model") != law.identity:
            raise ValueError("Checkpoint identity mismatch")
        p = _probability(body["packed"], 8)
        if p.shape != (4, 8) or not np.isfinite(body["clock"]) or body["clock"] < 0:
            raise ValueError("Invalid checkpoint state")
        result = cls(law, [0, 0, 0, 0])
        result.packed, result.clock = p.copy(), float(body["clock"])
        result.operations = dict(body["operations"])
        return result


class AnchoredPackedMemory(PackedBeliefMemory):
    """Eight masses plus an event time per address, advancing without reprojection.

    This is an age-dependent compressed filter, not an eight-state CTMC.
    Propagation produces forty temporary probabilities. Only an actual observed
    token or public write discards the within-group phase shape again.
    """

    def __init__(self, law, initial_values, projection="block", method="expm"):
        self.anchor_times = np.zeros(4)
        super().__init__(law, initial_values, projection, method)

    def materialize(self, key):
        elapsed = self.clock - self.anchor_times[key]
        self.operations["propagations"] += 1
        return unpack(self.packed[key]) @ self.law.transition(elapsed)

    @property
    def beliefs(self):
        return np.stack([self.materialize(key) for key in range(4)])

    def advance(self, dt):
        self.clock += self.law._duration(dt)

    def observe(self, key, token, quality):
        if quality not in self._emissions or not isinstance(key, (int, np.integer)) or not 0 <= key < 4:
            raise ValueError("Unknown observation quality or address")
        emission = self.law.E_read if quality == "read" else self.law.E_refresh
        if not isinstance(token, (int, np.integer)) or not 0 <= token < emission.shape[1]:
            raise ValueError("Invalid observation token")
        unnormalized = self.materialize(key) * emission[:, token]
        mass = float(unnormalized.sum())
        if mass <= 0:
            raise ValueError("Impossible observation")
        self.packed[key] = pack(unnormalized / mass)
        self.anchor_times[key] = self.clock
        self.operations["observations"] += 1

    def write(self, key, value):
        if (not isinstance(key, (int, np.integer)) or not isinstance(value, (int, np.integer))
                or not 0 <= key < 4 or not 0 <= value < 4):
            raise ValueError("Invalid public typed write")
        masses = pack(self.materialize(key)).reshape(2, 4).sum(1)
        self.packed[key] = 0.
        self.packed[key, [value, 4 + value]] = masses
        self.anchor_times[key] = self.clock
        self.operations["writes"] += 1

    def checkpoint(self):
        body = dict(schema="hcsn-r16-anchored-state-v1", model=self.law.identity,
                    clock=self.clock, packed=self.packed.tolist(),
                    anchor_times=self.anchor_times.tolist(), operations=self.operations.copy())
        body["sha256"] = hashlib.sha256(json.dumps(
            body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        return body

    @classmethod
    def restore(cls, law, payload):
        body = dict(payload)
        checksum = body.pop("sha256", None)
        expected = hashlib.sha256(json.dumps(
            body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        if checksum != expected or body.get("schema") != "hcsn-r16-anchored-state-v1" or body.get("model") != law.identity:
            raise ValueError("Checkpoint identity mismatch")
        p = _probability(body["packed"], 8)
        anchors, clock = np.asarray(body["anchor_times"], dtype=float), float(body["clock"])
        if (p.shape != (4, 8) or anchors.shape != (4,) or not np.isfinite(anchors).all()
                or not np.isfinite(clock) or clock < 0 or np.any(anchors < 0) or np.any(anchors > clock)):
            raise ValueError("Invalid checkpoint state")
        result = cls(law, [0, 0, 0, 0])
        result.packed, result.anchor_times, result.clock = p.copy(), anchors.copy(), clock
        result.operations = dict(body["operations"])
        return result


class BeliefMemory(OriginalBeliefMemory):
    """Full state with unchanged restore checks and scalar-one mass predicate."""

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
                or not normalized_rows(p, 1e-11)
                or not np.isfinite(body["clock"]) or body["clock"] < 0):
            raise ValueError("Invalid checkpoint state")
        result = cls(law, [0, 0, 0, 0], body["projection"], body["method"])
        result.clock, result.beliefs = float(body["clock"]), p.copy()
        result.operations = dict(body["operations"])
        return result
