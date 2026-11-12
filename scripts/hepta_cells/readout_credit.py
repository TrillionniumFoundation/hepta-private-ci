"""Bounded delayed readout teaching; no recurrent-gradient or adoption claim.

The decision-time eligibility is the linear sensitivity (features, 1), recorded
before labels exist. Routed and shuffled arms use a common pre-label reference
prediction to obtain identical teaching vectors. That is a frozen-reference
teaching experiment, not the exact gradient of each evolving candidate. Replay
SGD recomputes the candidate's current prediction on the same retained features.
Caller clock/owner declarations are consistency bindings, not authentication.
"""

import copy
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import time

import numpy as np

from .semantic import LocalHead, LocalObjective


ARMS = ("frozen", "replay_sgd", "scalar", "routed", "shuffled")
MAX_BYTES = 16 * 1024 * 1024


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _token(value):
    if type(value) is not str or not 1 <= len(value) <= 128:
        raise ValueError("bounded string identity required")


def _time(value):
    if type(value) is not int or not 0 <= value < 2**63:
        raise ValueError("nonnegative integer microseconds required")


def _vector(value, size):
    result = np.asarray(value, dtype=np.float64)
    if result.shape != (size,) or not np.isfinite(result).all():
        raise ValueError("finite vector of declared width required")
    if (np.abs(result) > 1e6).any():
        raise ValueError("readout input magnitude exceeds bound")
    return result


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate checkpoint key")
        result[key] = value
    return result


class ReadoutCredit:
    """Immutable transitions over linear readouts and bounded pending traces.

    One output column is one named Cell's scalar readout. Only MSE is supported;
    this is not a classifier or arbitrary recurrent eligibility implementation.
    All arms retain the same feature and reference-prediction memory opportunity.
    Returned candidates must be persisted by the caller before publication.
    """

    def __init__(
        self, head, objective, *, cell_ids, owner_id, version, clock_id, arm,
        tau_us=1_000_000, learning_rate=0.01, max_pending=64,
        max_decisions=4096, seed=0,
    ):
        if (not isinstance(head, LocalHead) or head.second is not None
                or not isinstance(objective, LocalObjective)
                or objective.kind != "mse" or objective.output_dim != len(head.bias)
                or not 1 <= head.first.shape[0] <= 256
                or type(cell_ids) is not tuple or not 2 <= len(cell_ids) <= 64
                or len(cell_ids) != objective.output_dim
                or len(set(cell_ids)) != len(cell_ids) or arm not in ARMS):
            raise ValueError("bounded linear multi-Cell MSE readout required")
        for value in (*cell_ids, owner_id, version, clock_id):
            _token(value)
        for value in (tau_us, seed, max_pending, max_decisions):
            _time(value)
        if (tau_us == 0 or not 1 <= max_pending <= 128
                or not max_pending <= max_decisions <= 4096
                or type(learning_rate) not in (int, float)
                or not 0 < learning_rate <= 1):
            raise ValueError("invalid bounded credit settings")
        self.head, self.objective = head, objective
        self._contract = dict(
            cell_ids=list(cell_ids), owner_id=owner_id, version=version,
            clock_id=clock_id, arm=arm, tau_us=tau_us,
            learning_rate=float(learning_rate), max_pending=max_pending,
            max_decisions=max_decisions, seed=seed, objective=asdict(objective),
            initial_head_sha256=head.digest, feature_dim=head.first.shape[0],
        )
        self._pending, self._settled = {}, {}
        self._rng = np.random.default_rng(seed)
        self.last_us, self.updates = 0, 0

    @property
    def contract(self):
        return copy.deepcopy(self._contract)

    @property
    def binding(self):
        return {k: self._contract[k] for k in ("owner_id", "version", "clock_id")}

    def _fork(self):
        result = copy.deepcopy(self)
        # NumPy deepcopy makes arrays writable; retain the original bytes-backed
        # immutable LocalHead until a real gradient step creates another one.
        result.head = self.head
        return result

    def decide(self, decision_id, features, *, reference_logits, mask, at_us):
        """Record pre-label features, prediction and public group mask once."""
        _token(decision_id)
        _time(at_us)
        if (at_us < self.last_us or decision_id in self._pending
                or decision_id in self._settled):
            raise ValueError("decision identity reused or clock regressed")
        if (len(self._pending) >= self._contract["max_pending"]
                or len(self._pending) + len(self._settled)
                >= self._contract["max_decisions"]):
            raise ValueError("retained credit capacity exhausted")
        count = len(self.head.bias)
        x = _vector(features, self._contract["feature_dim"])
        reference = _vector(reference_logits, count)
        if (type(mask) not in (list, tuple) or len(mask) != count
                or any(type(v) is not bool for v in mask) or sum(mask) < 2):
            raise ValueError("at least two visible groups required for derangement")
        row = dict(
            decision_id=decision_id, at_us=at_us, features=x.tolist(),
            reference_logits=reference.tolist(), mask=list(mask),
            prediction=_vector(self.head.predict(x[None])[0], count).tolist(),
            head_sha256=self.head.digest, binding=self.binding,
            cell_ids=self._contract["cell_ids"],
        )
        result = self._fork()
        result._pending[decision_id] = row
        result.last_us = at_us
        return result, dict(decision_sha256=_sha(row), **copy.deepcopy(row))

    def feedback(
        self, decision_id, targets, *, decision_sha256, binding,
        outcome_us, available_us, now_us,
    ):
        """Apply one visible feedback; exact retry returns the original receipt.

        Eligibility decays to the actual update time, including processing lag.
        Future payload values are not inspected before the availability check.
        An exception leaves this parent and its pending opportunity unchanged.
        """
        wall, cpu = time.perf_counter(), time.process_time()
        if type(binding) is not dict or binding != self.binding:
            raise ValueError("feedback owner, version or clock mismatch")
        for value in (outcome_us, available_us, now_us):
            _time(value)
        if not outcome_us <= available_us <= now_us:
            raise ValueError("feedback is future or has invalid chronology")
        _token(decision_id)
        target = _vector(targets, len(self.head.bias))
        request = dict(
            decision_id=decision_id, targets=target.tolist(),
            decision_sha256=decision_sha256, binding=binding,
            outcome_us=outcome_us, available_us=available_us, now_us=now_us,
        )
        fingerprint = _sha(request)
        if decision_id in self._settled:
            previous = self._settled[decision_id]
            if previous["request_sha256"] != fingerprint:
                raise ValueError("feedback retry differs from settled original")
            return self, copy.deepcopy(previous["receipt"])
        row = self._pending.get(decision_id)
        if (row is None or decision_sha256 != _sha(row)
                or row["at_us"] > outcome_us or now_us < self.last_us):
            raise ValueError("unknown decision, changed binding or regressed clock")
        result = self._fork()
        x = np.asarray(row["features"], dtype=np.float64)[None]
        reference = np.asarray(row["reference_logits"], dtype=np.float64)[None]
        mask = np.asarray(row["mask"], dtype=bool)
        loss, gradient = self.objective.loss_and_gradient(reference, target[None])
        teaching = gradient[0] * mask
        vector = teaching.copy()
        arm = self._contract["arm"]
        decay = math.exp(-(now_us - row["at_us"]) / self._contract["tau_us"])
        permutation = np.arange(len(vector))
        if arm == "shuffled":
            active = np.flatnonzero(mask)
            shift = int(result._rng.integers(1, len(active)))
            permutation[active] = np.roll(active, shift)
            vector = vector[permutation]
        elif arm == "scalar":
            vector[mask] = teaching[mask].mean()
        elif arm == "replay_sgd":
            _, current = self.objective.loss_and_gradient(
                self.head.predict(x), target[None]
            )
            vector = current[0] * mask
        applied = vector * (1.0 if arm == "replay_sgd" else decay)
        if arm != "frozen":
            result.head = self.head.gradient_step(
                x, applied[None], self._contract["learning_rate"]
            )
            result.updates += 1
        else:
            applied[:] = 0
        result.last_us = now_us
        del result._pending[decision_id]
        receipt = dict(
            schema="hepta.readout-credit-receipt.v1", arm=arm,
            decision_sha256=decision_sha256, request_sha256=fingerprint,
            parent_head_sha256=self.head.digest, candidate_head_sha256=result.head.digest,
            reference_loss=loss, teaching_vector=teaching.tolist(),
            teaching_sha256=_sha(dict(reference=row["reference_logits"],
                                      targets=target.tolist(), mask=row["mask"])),
            permutation=permutation.tolist(), applied_vector=applied.tolist(),
            delay_us=now_us-row["at_us"], decay=decay, updates=result.updates,
            feature_trace_scalars=len(row["features"])+1,
            work=dict(reference_loss_scalars=len(vector),
                      replay_forward_mac=int(x.size * len(vector)) if arm == "replay_sgd" else 0,
                      update_scalars=int(self.head.first.size+self.head.bias.size) if arm != "frozen" else 0),
            wall_seconds=time.perf_counter()-wall, cpu_seconds=time.process_time()-cpu,
            full_cost_known=False, owner_authenticated=False, adoption_authorized=False,
        )
        result._settled[decision_id] = dict(request_sha256=fingerprint, receipt=receipt)
        return result, copy.deepcopy(receipt)

    def record(self):
        return copy.deepcopy(dict(
            schema="hepta.readout-credit-checkpoint.v1", contract=self._contract,
            head=dict(first=self.head.first.tolist(), bias=self.head.bias.tolist()),
            optimizer=dict(kind="sgd-no-momentum", updates=self.updates),
            rng=self._rng.bit_generator.state, last_us=self.last_us,
            pending=self._pending, settled=self._settled,
        ))

    def checkpoint(self, path):
        """Save all training/trace/RNG state; caller must retain the returned pin."""
        raw = _json(self.record()).encode()
        if len(raw) > MAX_BYTES:
            raise ValueError("checkpoint exceeds retained byte bound")
        with Path(path).open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        return hashlib.sha256(raw).hexdigest()

    @classmethod
    def restore_checkpoint(cls, path, *, expected_sha256, expected_contract):
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_BYTES+1)
        if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValueError("checkpoint byte pin mismatch")
        data = json.loads(raw, object_pairs_hook=_unique)
        if (set(data) != {"schema", "contract", "head", "optimizer", "rng", "last_us", "pending", "settled"}
                or data["schema"] != "hepta.readout-credit-checkpoint.v1"
                or data["contract"] != expected_contract):
            raise ValueError("checkpoint contract mismatch; migration unsupported")
        c = copy.deepcopy(data["contract"])
        initial = c.pop("initial_head_sha256")
        width = c.pop("feature_dim")
        objective = LocalObjective(**c.pop("objective"))
        c["cell_ids"] = tuple(c["cell_ids"])
        if set(data["head"]) != {"first", "bias"}:
            raise ValueError("checkpoint head schema mismatch")
        result = cls(LocalHead(**data["head"]), objective, **c)
        if result.head.first.shape[0] != width:
            raise ValueError("checkpoint feature width mismatch")
        result._contract["initial_head_sha256"] = initial
        _time(data["last_us"])
        optimizer = data["optimizer"]
        if set(optimizer) != {"kind", "updates"} or optimizer["kind"] != "sgd-no-momentum":
            raise ValueError("checkpoint optimizer mismatch")
        _time(optimizer["updates"])
        pending, settled = data["pending"], data["settled"]
        if (type(pending) is not dict or type(settled) is not dict
                or set(pending) & set(settled) or len(pending) > c["max_pending"]
                or len(pending)+len(settled) > c["max_decisions"]
                or optimizer["updates"] != (0 if c["arm"] == "frozen" else len(settled))):
            raise ValueError("checkpoint retained ledger bounds or counts mismatch")
        for key, row in pending.items():
            _token(key)
            _time(row["at_us"])
            if (set(row) != {"decision_id", "at_us", "features", "reference_logits", "mask", "prediction", "head_sha256", "binding", "cell_ids"}
                    or row["decision_id"] != key or row["binding"] != result.binding
                    or row["cell_ids"] != list(c["cell_ids"]) or row["at_us"] > data["last_us"]):
                raise ValueError("checkpoint pending identity mismatch")
            _vector(row["features"], width)
            for field in ("reference_logits", "prediction"):
                _vector(row[field], len(c["cell_ids"]))
            if (type(row["mask"]) is not list or len(row["mask"]) != len(c["cell_ids"])
                    or any(type(v) is not bool for v in row["mask"]) or sum(row["mask"]) < 2):
                raise ValueError("checkpoint pending mask mismatch")
        for key, row in settled.items():
            _token(key)
            if (set(row) != {"request_sha256", "receipt"}
                    or row["receipt"]["request_sha256"] != row["request_sha256"]
                    or row["receipt"]["arm"] != c["arm"]):
                raise ValueError("checkpoint settlement mismatch")
        result._pending, result._settled = pending, settled
        result.last_us, result.updates = data["last_us"], optimizer["updates"]
        result._rng.bit_generator.state = data["rng"]
        return result
