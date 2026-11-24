"""Research-only contracts for a typed Cell fast path.

This module deliberately stops at an inspectable, shadow-only boundary.  A
Cell may propose a typed ActionIR program and a deterministic artifact cache
key, but it cannot execute code, mint capabilities, or commit an external
effect.  The existing Guardian/TaskFlow/effect-owner path remains the only
place where an authorized effect may be admitted.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence


SCHEMA_ACTION_IR = "hepta.cell.action-ir.v1"
SCHEMA_CANDIDATE = "hepta.cell.fast-path-candidate.v1"
SCHEMA_RECEIPT = "hepta.cell.fast-path-receipt.v1"
DENY_ALL = "DENY_ALL"

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,127}$")
_ALLOWED_OPS = frozenset(
    {
        "observe_ax",
        "observe_screen",
        "locate",
        "assert",
        "click",
        "key",
        "type_text",
        "scroll",
        "focus_window",
        "clipboard_read",
        "clipboard_write",
        "wait",
        "emit",
    }
)
_ALLOWED_BACKENDS = frozenset({"wasm_aot", "native_precompiled", "cuda_graph"})
_ALLOWED_TARGETS = frozenset({"cpu", "gpu"})
_ALLOWED_DETERMINISM = frozenset({"strict", "bounded_nondeterminism"})
_ALLOWED_OUTCOMES = frozenset({"shadow", "rejected", "expired"})
_FORBIDDEN_KEYS = frozenset(
    {
        "address",
        "binary",
        "bytes",
        "code",
        "fd",
        "machine_code",
        "memory_address",
        "opcode",
        "pointer",
        "ptx",
        "raw_pointer",
        "rwx",
        "shell",
        "syscall",
    }
)
_SHADOW_EVIDENCE_KEYS = frozenset({"lane", "source", "observation_digest", "build_id"})


def _require_identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"{field} must be a bounded identifier")
    return value


def _require_digest(value: str, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase sha256 digest")
    return value


def _require_bool(value: bool, field: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field} must be a bool")
    return value


def _require_nonnegative_int(value: int, field: str, upper: int | None = None) -> int:
    if type(value) is not int or value < 0 or (upper is not None and value > upper):
        raise ValueError(f"{field} must be an integer in [0, {upper}]" if upper is not None else f"{field} must be non-negative")
    return value


def _json_value(value: Any, field: str, depth: int = 0) -> Any:
    """Accept JSON data while rejecting executable or pointer-shaped payloads."""

    if depth > 8:
        raise ValueError(f"{field} is nested too deeply")
    if value is None or type(value) is bool or type(value) is int or isinstance(value, str):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{field} contains a non-finite number")
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise ValueError(f"{field} cannot contain raw bytes")
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{field} keys must be strings")
            if key.lower() in _FORBIDDEN_KEYS or any(token in key.lower() for token in ("pointer", "syscall", "machine", "opcode", "ptx")):
                raise ValueError(f"{field} contains forbidden executable key {key!r}")
            result[key] = _json_value(item, f"{field}.{key}", depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_value(item, f"{field}[{index}]", depth + 1) for index, item in enumerate(value)]
    raise ValueError(f"{field} must contain JSON-compatible values")


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _shadow_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _json_value(dict(value), "evidence")
    if not isinstance(normalized, dict) or not set(normalized).issubset(_SHADOW_EVIDENCE_KEYS):
        raise ValueError("shadow evidence may contain only lane, source, observation_digest, and build_id")
    return normalized


@dataclass(frozen=True)
class ActionOpV1:
    op: str
    target: str
    args: Mapping[str, Any]
    capability_id: str
    idempotency_key: str
    precondition_digest: str
    postcondition_digest: str
    reversible: bool

    def __post_init__(self) -> None:
        if self.op not in _ALLOWED_OPS:
            raise ValueError(f"unsupported typed ActionIR op: {self.op!r}")
        _require_identifier(self.target, "target")
        _require_identifier(self.capability_id, "capability_id")
        _require_identifier(self.idempotency_key, "idempotency_key")
        if not isinstance(self.args, Mapping):
            raise ValueError("args must be a mapping")
        object.__setattr__(self, "args", _json_value(dict(self.args), "args"))
        _require_digest(self.precondition_digest, "precondition_digest")
        _require_digest(self.postcondition_digest, "postcondition_digest")
        _require_bool(self.reversible, "reversible")

    def as_dict(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "target": self.target,
            "args": dict(self.args),
            "capability_id": self.capability_id,
            "idempotency_key": self.idempotency_key,
            "precondition_digest": self.precondition_digest,
            "postcondition_digest": self.postcondition_digest,
            "reversible": self.reversible,
        }


@dataclass(frozen=True)
class ActionIRV1:
    cell_id: str
    stem_digest: str
    head_digest: str
    objective_digest: str
    app_identity: str
    body_generation: int
    revocation_epoch: int
    abi: str
    ops: tuple[ActionOpV1, ...]
    required_capabilities: tuple[str, ...]
    max_ops: int
    deadline_ms: int
    max_memory_bytes: int
    determinism: str
    authority: str = DENY_ALL
    physical_effect: bool = False

    def __post_init__(self) -> None:
        _require_identifier(self.cell_id, "cell_id")
        for field in ("stem_digest", "head_digest", "objective_digest"):
            _require_digest(getattr(self, field), field)
        _require_identifier(self.app_identity, "app_identity")
        _require_nonnegative_int(self.body_generation, "body_generation")
        _require_nonnegative_int(self.revocation_epoch, "revocation_epoch")
        _require_identifier(self.abi, "abi")
        if not isinstance(self.ops, tuple) or not self.ops:
            raise ValueError("ops must be a non-empty tuple")
        if not all(isinstance(op, ActionOpV1) for op in self.ops):
            raise ValueError("ops must contain ActionOpV1 values")
        _require_nonnegative_int(self.max_ops, "max_ops", upper=256)
        if self.max_ops == 0 or len(self.ops) > self.max_ops:
            raise ValueError("ops exceed max_ops")
        _require_nonnegative_int(self.deadline_ms, "deadline_ms", upper=60_000)
        if self.deadline_ms == 0:
            raise ValueError("deadline_ms must be positive")
        _require_nonnegative_int(self.max_memory_bytes, "max_memory_bytes", upper=1 << 30)
        if self.max_memory_bytes == 0:
            raise ValueError("max_memory_bytes must be positive")
        if self.determinism not in _ALLOWED_DETERMINISM:
            raise ValueError("unsupported determinism mode")
        if self.authority != DENY_ALL:
            raise ValueError("ActionIR cannot mint or carry execution authority")
        if _require_bool(self.physical_effect, "physical_effect"):
            raise ValueError("ActionIR is advisory and cannot claim a physical effect")
        caps = tuple(_require_identifier(cap, "required_capabilities[]") for cap in self.required_capabilities)
        if len(set(caps)) != len(caps):
            raise ValueError("required_capabilities must be unique")
        object.__setattr__(self, "required_capabilities", caps)
        op_caps = {op.capability_id for op in self.ops}
        if not op_caps.issubset(set(caps)):
            raise ValueError("every ActionIR op capability must be declared in required_capabilities")
        keys = [op.idempotency_key for op in self.ops]
        if len(set(keys)) != len(keys):
            raise ValueError("ActionIR idempotency keys must be unique")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_ACTION_IR,
            "cell_id": self.cell_id,
            "stem_digest": self.stem_digest,
            "head_digest": self.head_digest,
            "objective_digest": self.objective_digest,
            "app_identity": self.app_identity,
            "body_generation": self.body_generation,
            "revocation_epoch": self.revocation_epoch,
            "abi": self.abi,
            "ops": [op.as_dict() for op in self.ops],
            "required_capabilities": list(self.required_capabilities),
            "max_ops": self.max_ops,
            "deadline_ms": self.deadline_ms,
            "max_memory_bytes": self.max_memory_bytes,
            "determinism": self.determinism,
            "authority": self.authority,
            "physical_effect": self.physical_effect,
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.as_dict())


@dataclass(frozen=True)
class FastPathCandidateV1:
    candidate_id: str
    cell_id: str
    app_identity: str
    action_ir_digest: str
    artifact_digest: str
    capability_manifest_digest: str
    runtime_tuple_digest: str
    policy_digest: str
    snapshot_id: str
    authorization_version: str
    revocation_epoch: int
    body_generation: int
    backend: str
    target: str
    abi: str
    resource_limits: Mapping[str, int]
    evidence_digest: str
    signed: bool = False
    production_activation: bool = False
    authority: str = DENY_ALL

    def __post_init__(self) -> None:
        _require_identifier(self.candidate_id, "candidate_id")
        _require_identifier(self.cell_id, "cell_id")
        _require_identifier(self.app_identity, "app_identity")
        for field in (
            "action_ir_digest",
            "artifact_digest",
            "capability_manifest_digest",
            "runtime_tuple_digest",
            "policy_digest",
            "evidence_digest",
        ):
            _require_digest(getattr(self, field), field)
        _require_identifier(self.snapshot_id, "snapshot_id")
        _require_identifier(self.authorization_version, "authorization_version")
        _require_nonnegative_int(self.revocation_epoch, "revocation_epoch")
        _require_nonnegative_int(self.body_generation, "body_generation")
        if self.backend not in _ALLOWED_BACKENDS:
            raise ValueError("unsupported fast-path backend")
        if self.target not in _ALLOWED_TARGETS:
            raise ValueError("unsupported fast-path target")
        _require_identifier(self.abi, "abi")
        if not isinstance(self.resource_limits, Mapping):
            raise ValueError("resource_limits must be a mapping")
        limits = {str(key): _require_nonnegative_int(value, f"resource_limits.{key}") for key, value in self.resource_limits.items()}
        if set(limits) != {"max_ops", "deadline_ms", "max_memory_bytes"}:
            raise ValueError("resource_limits must contain exactly max_ops, deadline_ms, max_memory_bytes")
        if limits["max_ops"] == 0 or limits["deadline_ms"] == 0 or limits["max_memory_bytes"] == 0:
            raise ValueError("resource limits must be positive")
        object.__setattr__(self, "resource_limits", limits)
        _require_bool(self.signed, "signed")
        if _require_bool(self.production_activation, "production_activation"):
            raise ValueError("research fast-path candidates cannot activate production")
        if self.authority != DENY_ALL:
            raise ValueError("fast-path candidate cannot carry execution authority")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_CANDIDATE,
            "candidate_id": self.candidate_id,
            "cell_id": self.cell_id,
            "app_identity": self.app_identity,
            "action_ir_digest": self.action_ir_digest,
            "artifact_digest": self.artifact_digest,
            "capability_manifest_digest": self.capability_manifest_digest,
            "runtime_tuple_digest": self.runtime_tuple_digest,
            "policy_digest": self.policy_digest,
            "snapshot_id": self.snapshot_id,
            "authorization_version": self.authorization_version,
            "revocation_epoch": self.revocation_epoch,
            "body_generation": self.body_generation,
            "backend": self.backend,
            "target": self.target,
            "abi": self.abi,
            "resource_limits": dict(self.resource_limits),
            "evidence_digest": self.evidence_digest,
            "signed": self.signed,
            "production_activation": self.production_activation,
            "authority": self.authority,
        }


@dataclass(frozen=True)
class FastPathRuntimeReceiptV1:
    candidate_id: str
    action_ir_digest: str
    artifact_digest: str
    app_identity: str
    body_generation: int
    revocation_epoch: int
    capability_ids: tuple[str, ...]
    pre_observation_digest: str
    post_observation_digest: str
    outcome: str
    cpu_ns: int
    gpu_ns: int
    bytes_touched: int
    executed: bool = False
    effect_committed: bool = False
    authority: str = DENY_ALL

    def __post_init__(self) -> None:
        _require_identifier(self.candidate_id, "candidate_id")
        _require_digest(self.action_ir_digest, "action_ir_digest")
        _require_digest(self.artifact_digest, "artifact_digest")
        _require_identifier(self.app_identity, "app_identity")
        _require_nonnegative_int(self.body_generation, "body_generation")
        _require_nonnegative_int(self.revocation_epoch, "revocation_epoch")
        caps = tuple(_require_identifier(cap, "capability_ids[]") for cap in self.capability_ids)
        if len(set(caps)) != len(caps):
            raise ValueError("capability_ids must be unique")
        object.__setattr__(self, "capability_ids", caps)
        _require_digest(self.pre_observation_digest, "pre_observation_digest")
        _require_digest(self.post_observation_digest, "post_observation_digest")
        if self.outcome not in _ALLOWED_OUTCOMES:
            raise ValueError("shadow receipt has an unsupported outcome")
        _require_nonnegative_int(self.cpu_ns, "cpu_ns")
        _require_nonnegative_int(self.gpu_ns, "gpu_ns")
        _require_nonnegative_int(self.bytes_touched, "bytes_touched")
        if _require_bool(self.executed, "executed"):
            raise ValueError("shadow receipt cannot claim execution")
        if _require_bool(self.effect_committed, "effect_committed"):
            raise ValueError("shadow receipt cannot commit an effect")
        if self.authority != DENY_ALL:
            raise ValueError("receipt cannot carry execution authority")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_RECEIPT,
            "candidate_id": self.candidate_id,
            "action_ir_digest": self.action_ir_digest,
            "artifact_digest": self.artifact_digest,
            "app_identity": self.app_identity,
            "body_generation": self.body_generation,
            "revocation_epoch": self.revocation_epoch,
            "capability_ids": list(self.capability_ids),
            "pre_observation_digest": self.pre_observation_digest,
            "post_observation_digest": self.post_observation_digest,
            "outcome": self.outcome,
            "cpu_ns": self.cpu_ns,
            "gpu_ns": self.gpu_ns,
            "bytes_touched": self.bytes_touched,
            "executed": self.executed,
            "effect_committed": self.effect_committed,
            "authority": self.authority,
        }


def compile_shadow_candidate(
    action_ir: ActionIRV1,
    *,
    candidate_id: str,
    capability_manifest_digest: str,
    runtime_tuple_digest: str,
    policy_digest: str,
    snapshot_id: str,
    authorization_version: str,
    backend: str,
    target: str,
    evidence: Mapping[str, Any],
) -> FastPathCandidateV1:
    """Derive a cache key and candidate metadata without compiling or executing code."""

    evidence_value = _shadow_evidence(evidence)
    _require_digest(capability_manifest_digest, "capability_manifest_digest")
    _require_digest(runtime_tuple_digest, "runtime_tuple_digest")
    _require_digest(policy_digest, "policy_digest")
    _require_identifier(snapshot_id, "snapshot_id")
    artifact_digest = canonical_digest(
        {
            "ir": action_ir.as_dict(),
            "backend": backend,
            "target": target,
            "abi": action_ir.abi,
            "capability_manifest_digest": capability_manifest_digest,
            "runtime_tuple_digest": runtime_tuple_digest,
            "policy_digest": policy_digest,
            "snapshot_id": snapshot_id,
        }
    )
    evidence_digest = canonical_digest({"evidence": evidence_value, "artifact_digest": artifact_digest})
    return FastPathCandidateV1(
        candidate_id=candidate_id,
        cell_id=action_ir.cell_id,
        app_identity=action_ir.app_identity,
        action_ir_digest=action_ir.digest,
        artifact_digest=artifact_digest,
        capability_manifest_digest=capability_manifest_digest,
        runtime_tuple_digest=runtime_tuple_digest,
        policy_digest=policy_digest,
        snapshot_id=snapshot_id,
        authorization_version=authorization_version,
        revocation_epoch=action_ir.revocation_epoch,
        body_generation=action_ir.body_generation,
        backend=backend,
        target=target,
        abi=action_ir.abi,
        resource_limits={
            "max_ops": action_ir.max_ops,
            "deadline_ms": action_ir.deadline_ms,
            "max_memory_bytes": action_ir.max_memory_bytes,
        },
        evidence_digest=evidence_digest,
    )


def build_shadow_receipt(
    candidate: FastPathCandidateV1,
    *,
    app_identity: str,
    pre_observation_digest: str,
    post_observation_digest: str,
    capability_ids: Sequence[str] = (),
    outcome: str = "shadow",
) -> FastPathRuntimeReceiptV1:
    """Record a non-executing observation of a candidate."""

    if app_identity != candidate.app_identity:
        raise ValueError("receipt app_identity must match candidate app_identity")
    return FastPathRuntimeReceiptV1(
        candidate_id=candidate.candidate_id,
        action_ir_digest=candidate.action_ir_digest,
        artifact_digest=candidate.artifact_digest,
        app_identity=app_identity,
        body_generation=candidate.body_generation,
        revocation_epoch=candidate.revocation_epoch,
        capability_ids=tuple(capability_ids),
        pre_observation_digest=pre_observation_digest,
        post_observation_digest=post_observation_digest,
        outcome=outcome,
        cpu_ns=0,
        gpu_ns=0,
        bytes_touched=0,
    )
