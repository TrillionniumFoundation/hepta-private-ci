"""Bounded, non-authorizing contracts for the CPU joint-generation experiment."""

from dataclasses import dataclass
import hashlib
import json
import re

import numpy as np


class ContractError(ValueError):
    pass


class UnsupportedModality(ContractError):
    pass


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ContractError("missing or unknown fields")


def _integer(value, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ContractError("integer outside bounds")
    return value


def digest(value):
    return hashlib.sha256(value).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


@dataclass(frozen=True)
class Budget:
    compute_units: int
    output_bytes: int


@dataclass(frozen=True)
class RunSpec:
    objective_id: str
    run_id: str
    artifact_sha256: str
    modalities: tuple
    budget: Budget
    deadline_ns: int

    @classmethod
    def parse(cls, value, *, now_ns):
        _keys(value, ("objective_id", "run_id", "artifact_sha256", "modalities", "budget", "deadline_ns"))
        for field in ("objective_id", "run_id"):
            if not isinstance(value[field], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._/-]{0,127}", value[field]):
                raise ContractError("invalid identity")
        if not isinstance(value["artifact_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["artifact_sha256"]):
            raise ContractError("invalid selected artifact")
        modes = value["modalities"]
        if not isinstance(modes, (list, tuple)) or not modes or len(modes) > 4:
            raise ContractError("invalid modalities")
        for mode in modes:
            if not isinstance(mode, str) or mode not in ("text", "image"):
                raise UnsupportedModality(mode)
        if len(set(modes)) != len(modes):
            raise ContractError("duplicate modality")
        _keys(value["budget"], ("compute_units", "output_bytes"))
        limits = Budget(_integer(value["budget"]["compute_units"], 1, 10**9), _integer(value["budget"]["output_bytes"], 1, 2**20))
        deadline = _integer(value["deadline_ns"], 1, 2**63 - 1)
        if deadline <= _integer(now_ns, 0, 2**63 - 1):
            raise ContractError("deadline expired")
        return cls(value["objective_id"], value["run_id"], value["artifact_sha256"], tuple(modes), limits, deadline)

    def payload(self):
        return {"objective_id": self.objective_id, "run_id": self.run_id,
                "artifact_sha256": self.artifact_sha256, "modalities": list(self.modalities),
                "budget": vars(self.budget), "deadline_ns": self.deadline_ns}


def validate_tensor(modality, value):
    if modality not in ("text", "image"):
        raise UnsupportedModality(modality)
    array = np.asarray(value)
    valid_shape = (array.ndim == 1 and 1 <= array.size <= 4096) if modality == "text" else (
        array.ndim == 3 and 1 <= array.shape[0] <= 64 and 1 <= array.shape[1] <= 64 and array.shape[2] == 3)
    if not valid_shape or array.dtype.kind not in "fiu" or not np.isfinite(array).all():
        raise ContractError("invalid tensor shape or values")
    return array.copy()


class RunSession:
    """Append-only delivery and charged work; checkpoints are not authority receipts."""

    def __init__(self, spec):
        if not isinstance(spec, RunSpec):
            raise ContractError("RunSpec required")
        self._spec = RunSpec.parse(spec.payload(), now_ns=0)
        self._spent = {"controller": 0, "generator": 0}
        self._prefixes = {mode: b"" for mode in spec.modalities}
        self._cancelled = False

    @property
    def spec(self):
        return self._spec

    def _live(self, now_ns):
        if self._cancelled or _integer(now_ns, 0, 2**63 - 1) >= self.spec.deadline_ns:
            raise ContractError("cancelled or expired")

    def charge(self, source, compute_units, *, now_ns):
        self._live(now_ns)
        if source not in self._spent:
            raise ContractError("unknown work source")
        units = _integer(compute_units, 0, self.spec.budget.compute_units)
        if sum(self._spent.values()) + units > self.spec.budget.compute_units:
            raise ContractError("compute budget exceeded")
        self._spent[source] += units

    @property
    def spent(self):
        return {**self._spent, "output_bytes": sum(map(len, self._prefixes.values()))}

    def prefix(self, modality):
        if modality not in self._prefixes:
            raise UnsupportedModality(modality)
        return self._prefixes[modality]

    def publish(self, modality, chunk, *, expected_prefix_sha256, now_ns):
        self._live(now_ns)
        prefix = self.prefix(modality)
        if type(chunk) is not bytes or not chunk or digest(prefix) != expected_prefix_sha256:
            raise ContractError("invalid chunk or predecessor")
        if self.spent["output_bytes"] + len(chunk) > self.spec.budget.output_bytes:
            raise ContractError("output budget exceeded")
        self._prefixes[modality] = prefix + chunk

    def cancel(self):
        self._cancelled = True

    def checkpoint(self):
        payload = {"spec": self.spec.payload(), "spent": self._spent.copy(),
                   "prefixes": {key: value.hex() for key, value in self._prefixes.items()}, "cancelled": self._cancelled}
        return {"payload": payload, "sha256": digest(_json(payload))}

    @classmethod
    def restore(cls, checkpoint, *, expected_artifact_sha256, now_ns):
        _keys(checkpoint, ("payload", "sha256"))
        data = checkpoint["payload"]
        _keys(data, ("spec", "spent", "prefixes", "cancelled"))
        if digest(_json(data)) != checkpoint["sha256"]:
            raise ContractError("corrupt checkpoint")
        spec = RunSpec.parse(data["spec"], now_ns=now_ns)
        if spec.artifact_sha256 != expected_artifact_sha256 or type(data["cancelled"]) is not bool:
            raise ContractError("incompatible checkpoint")
        _keys(data["spent"], ("controller", "generator"))
        _keys(data["prefixes"], spec.modalities)
        session = cls(spec)
        for source, units in data["spent"].items():
            session.charge(source, units, now_ns=now_ns)
        for mode, encoded in data["prefixes"].items():
            if not isinstance(encoded, str) or len(encoded) > 2 * spec.budget.output_bytes:
                raise ContractError("invalid encoded prefix")
            try:
                prefix = bytes.fromhex(encoded)
            except ValueError as error:
                raise ContractError("invalid encoded prefix") from error
            if prefix:
                session.publish(mode, prefix, expected_prefix_sha256=digest(b""), now_ns=now_ns)
        session._cancelled = data["cancelled"]
        return session
