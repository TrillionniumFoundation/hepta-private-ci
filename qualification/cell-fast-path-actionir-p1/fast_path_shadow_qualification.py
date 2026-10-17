"""P1 shadow qualification for a typed Cell FastPath candidate.

The qualifier is pure policy evaluation.  It does not execute ActionIR, call
Guardian, claim a TaskFlow operation, mint a grant, or commit an effect.  It
only decides whether a candidate is eligible for shadow observation under an
already-resolved authorization envelope and returns a deterministic fallback
decision when the candidate is stale, unsafe, or over budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from cell_fast_path_actionir import (
    ActionIRV1,
    DENY_ALL,
    FastPathCandidateV1,
    FastPathRuntimeReceiptV1,
    _require_digest,
    _require_identifier,
    _require_nonnegative_int,
    build_shadow_receipt,
    canonical_digest,
)


QUALIFICATION_SCHEMA = "hepta.cell.fast-path-shadow-qualification.v1"
_MODES = frozenset({"shadow", "cpu_non_effect"})
_EFFECT_OPS = frozenset(
    {"click", "key", "type_text", "scroll", "focus_window", "clipboard_write"}
)
_REASON_PRIORITY = (
    "APP_IDENTITY_MISMATCH",
    "STALE_AUTHORIZATION",
    "EXPIRED",
    "REVOKED_CAPABILITY",
    "FUTURE_REVOCATION_EPOCH",
    "GENERATION_STALE",
    "FUTURE_GENERATION_REJECTED",
    "STEM_MISMATCH",
    "HEAD_MISMATCH",
    "OBJECTIVE_MISMATCH",
    "ARTIFACT_MISMATCH",
    "RUNTIME_TUPLE_MISMATCH",
    "SNAPSHOT_MISMATCH",
    "ABI_MISMATCH",
    "ARTIFACT_TARGET_MISMATCH",
    "CAPABILITY_SCOPE_MISMATCH",
    "POLICY_SCOPE_MISMATCH",
    "PRECONDITION_FAILED",
    "BUDGET_EXCEEDED",
    "EFFECT_REQUIRES_GUARDIAN",
    "DUPLICATE_REPLAY",
    "REPLAY_CONFLICT",
)


def _unique_sorted(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def _positive(value: int, field: str, upper: int | None = None) -> int:
    _require_nonnegative_int(value, field, upper=upper)
    if value == 0:
        raise ValueError(f"{field} must be positive")
    return value


@dataclass(frozen=True)
class GuardianAuthorizationVersionV1:
    history_version: int
    user_message_count: int
    root_history_version: int
    root_user_message_count: int

    def __post_init__(self) -> None:
        for field in (
            "history_version",
            "user_message_count",
            "root_history_version",
            "root_user_message_count",
        ):
            _require_nonnegative_int(getattr(self, field), field)

    def as_dict(self) -> dict[str, int]:
        return {
            "history_version": self.history_version,
            "user_message_count": self.user_message_count,
            "root_history_version": self.root_history_version,
            "root_user_message_count": self.root_user_message_count,
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.as_dict())


@dataclass(frozen=True)
class AuthorizationEnvelopeV1:
    app_identity: str
    authorization_version: str
    capability_ids: tuple[str, ...]
    capability_scope_digest: str
    policy_digest: str
    body_generation: int
    revocation_epoch: int
    issued_at_ms: int
    expires_at_ms: int
    authority: str = DENY_ALL
    shadow_only: bool = True

    def __post_init__(self) -> None:
        _require_identifier(self.app_identity, "app_identity")
        _require_digest(self.authorization_version, "authorization_version")
        caps = tuple(_require_identifier(cap, "capability_ids[]") for cap in self.capability_ids)
        if len(set(caps)) != len(caps):
            raise ValueError("capability_ids must be unique")
        object.__setattr__(self, "capability_ids", _unique_sorted(caps))
        _require_digest(self.capability_scope_digest, "capability_scope_digest")
        _require_digest(self.policy_digest, "policy_digest")
        _require_nonnegative_int(self.body_generation, "body_generation")
        _require_nonnegative_int(self.revocation_epoch, "revocation_epoch")
        _require_nonnegative_int(self.issued_at_ms, "issued_at_ms")
        _positive(self.expires_at_ms, "expires_at_ms")
        if self.issued_at_ms >= self.expires_at_ms:
            raise ValueError("authorization envelope must have a positive validity interval")
        if self.authority != DENY_ALL:
            raise ValueError("authorization envelope cannot carry execution authority")
        if type(self.shadow_only) is not bool or not self.shadow_only:
            raise ValueError("P1 authorization envelopes must be shadow-only")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "hepta.cell.authorization-envelope.v1",
            "app_identity": self.app_identity,
            "authorization_version": self.authorization_version,
            "capability_ids": list(self.capability_ids),
            "capability_scope_digest": self.capability_scope_digest,
            "policy_digest": self.policy_digest,
            "body_generation": self.body_generation,
            "revocation_epoch": self.revocation_epoch,
            "issued_at_ms": self.issued_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "authority": self.authority,
            "shadow_only": self.shadow_only,
        }


@dataclass(frozen=True)
class ResourceBudgetV1:
    max_ops: int
    deadline_ms: int
    max_memory_bytes: int
    max_cpu_ns: int
    max_gpu_ns: int
    max_bytes_touched: int

    def __post_init__(self) -> None:
        for field, upper in (
            ("max_ops", 256),
            ("deadline_ms", 60_000),
            ("max_memory_bytes", 1 << 30),
            ("max_cpu_ns", 60_000_000_000),
            ("max_gpu_ns", 60_000_000_000),
            ("max_bytes_touched", 1 << 34),
        ):
            _positive(getattr(self, field), field, upper=upper)

    def as_dict(self) -> dict[str, int]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}


@dataclass(frozen=True)
class ResourceObservationV1:
    observed_ops: int
    elapsed_ms: int
    cpu_ns: int
    gpu_ns: int
    peak_memory_bytes: int
    bytes_touched: int

    def __post_init__(self) -> None:
        for field in self.__dataclass_fields__:
            _require_nonnegative_int(getattr(self, field), field)

    def over_budget(self, budget: ResourceBudgetV1) -> bool:
        return any(
            value > limit
            for value, limit in (
                (self.observed_ops, budget.max_ops),
                (self.elapsed_ms, budget.deadline_ms),
                (self.cpu_ns, budget.max_cpu_ns),
                (self.gpu_ns, budget.max_gpu_ns),
                (self.peak_memory_bytes, budget.max_memory_bytes),
                (self.bytes_touched, budget.max_bytes_touched),
            )
        )

    def as_dict(self) -> dict[str, int]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}


@dataclass(frozen=True)
class GenerationBindingV1:
    stem_digest: str
    head_digest: str
    objective_digest: str
    artifact_digest: str
    runtime_tuple_digest: str
    abi: str
    target: str
    body_generation: int
    snapshot_id: str

    def __post_init__(self) -> None:
        for field in (
            "stem_digest",
            "head_digest",
            "objective_digest",
            "artifact_digest",
            "runtime_tuple_digest",
        ):
            _require_digest(getattr(self, field), field)
        _require_identifier(self.abi, "abi")
        if self.target not in {"cpu", "gpu"}:
            raise ValueError("target must be cpu or gpu")
        _require_nonnegative_int(self.body_generation, "body_generation")
        _require_identifier(self.snapshot_id, "snapshot_id")

    def as_dict(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}


@dataclass(frozen=True)
class PreconditionCheckV1:
    op_idempotency_key: str
    expected_digest: str
    observed_observation_digest: str
    passed: bool
    checked_at_ms: int
    reason_code: str = "OK"

    def __post_init__(self) -> None:
        _require_identifier(self.op_idempotency_key, "op_idempotency_key")
        _require_digest(self.expected_digest, "expected_digest")
        _require_digest(self.observed_observation_digest, "observed_observation_digest")
        if type(self.passed) is not bool:
            raise ValueError("passed must be a bool")
        _require_nonnegative_int(self.checked_at_ms, "checked_at_ms")
        _require_identifier(self.reason_code, "reason_code")

    def as_dict(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}


@dataclass(frozen=True)
class ParentFallbackV1:
    parent_candidate_id: str
    parent_action_ir_digest: str
    parent_artifact_digest: str
    parent_body_generation: int
    parent_stem_digest: str
    parent_app_identity: str
    parent_objective_digest: str
    reason_code: str
    fallback_count: int = 0

    def __post_init__(self) -> None:
        _require_identifier(self.parent_candidate_id, "parent_candidate_id")
        _require_digest(self.parent_action_ir_digest, "parent_action_ir_digest")
        _require_digest(self.parent_artifact_digest, "parent_artifact_digest")
        _require_nonnegative_int(self.parent_body_generation, "parent_body_generation")
        _require_digest(self.parent_stem_digest, "parent_stem_digest")
        _require_identifier(self.parent_app_identity, "parent_app_identity")
        _require_digest(self.parent_objective_digest, "parent_objective_digest")
        _require_identifier(self.reason_code, "reason_code")
        _require_nonnegative_int(self.fallback_count, "fallback_count", upper=1)

    def as_dict(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}


@dataclass(frozen=True)
class ReplayIndexV1:
    entries: Mapping[str, str]

    def __post_init__(self) -> None:
        for key, value in self.entries.items():
            _require_digest(key, "replay_key")
            _require_digest(value, "replay_payload_digest")
        object.__setattr__(self, "entries", dict(self.entries))

    def lookup(self, replay_key: str, payload_digest: str) -> str | None:
        _require_digest(replay_key, "replay_key")
        _require_digest(payload_digest, "payload_digest")
        prior = self.entries.get(replay_key)
        if prior is None:
            return None
        return "DUPLICATE_REPLAY" if prior == payload_digest else "REPLAY_CONFLICT"

    def record(self, replay_key: str, payload_digest: str) -> "ReplayIndexV1":
        _require_digest(replay_key, "replay_key")
        _require_digest(payload_digest, "payload_digest")
        values = dict(self.entries)
        values.setdefault(replay_key, payload_digest)
        return ReplayIndexV1(values)


@dataclass(frozen=True)
class ShadowQualificationContextV1:
    envelope: AuthorizationEnvelopeV1
    binding: GenerationBindingV1
    budget: ResourceBudgetV1
    capability_scope_digest: str
    policy_digest: str
    target_handle_digest: str
    window_tree_digest: str
    mode: str = "shadow"

    def __post_init__(self) -> None:
        _require_digest(self.capability_scope_digest, "capability_scope_digest")
        _require_digest(self.policy_digest, "policy_digest")
        _require_digest(self.target_handle_digest, "target_handle_digest")
        _require_digest(self.window_tree_digest, "window_tree_digest")
        if self.mode not in _MODES:
            raise ValueError("unsupported shadow qualification mode")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": QUALIFICATION_SCHEMA,
            "envelope": self.envelope.as_dict(),
            "binding": self.binding.as_dict(),
            "budget": self.budget.as_dict(),
            "capability_scope_digest": self.capability_scope_digest,
            "policy_digest": self.policy_digest,
            "target_handle_digest": self.target_handle_digest,
            "window_tree_digest": self.window_tree_digest,
            "mode": self.mode,
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.as_dict())


@dataclass(frozen=True)
class ShadowQualificationDecisionV1:
    candidate_id: str
    status: str
    reason_codes: tuple[str, ...]
    context_digest: str
    fallback_required: bool
    parent_fallback: ParentFallbackV1 | None
    receipt: FastPathRuntimeReceiptV1
    effect_admitted: bool = False
    authority: str = DENY_ALL

    def __post_init__(self) -> None:
        _require_identifier(self.candidate_id, "candidate_id")
        _require_identifier(self.status, "status")
        _require_digest(self.context_digest, "context_digest")
        if type(self.fallback_required) is not bool:
            raise ValueError("fallback_required must be a bool")
        if type(self.effect_admitted) is not bool or self.effect_admitted:
            raise ValueError("shadow qualification cannot admit effects")
        if self.authority != DENY_ALL:
            raise ValueError("shadow qualification cannot carry authority")
        object.__setattr__(self, "reason_codes", tuple(_unique_sorted(self.reason_codes)))

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": QUALIFICATION_SCHEMA,
            "candidate_id": self.candidate_id,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "context_digest": self.context_digest,
            "fallback_required": self.fallback_required,
            "parent_fallback": None if self.parent_fallback is None else self.parent_fallback.as_dict(),
            "receipt": self.receipt.as_dict(),
            "effect_admitted": self.effect_admitted,
            "authority": self.authority,
        }


@dataclass(frozen=True)
class ShadowQualificationResultV1:
    decision: ShadowQualificationDecisionV1
    replay_index: ReplayIndexV1


def _replay_key(
    candidate: FastPathCandidateV1,
    ir: ActionIRV1,
    envelope: AuthorizationEnvelopeV1,
    pre_observation_digest: str,
) -> str:
    return canonical_digest(
        {
            "candidate_id": candidate.candidate_id,
            "action_ir_digest": ir.digest,
            "artifact_digest": candidate.artifact_digest,
            "authorization_version": envelope.authorization_version,
            "revocation_epoch": envelope.revocation_epoch,
            "pre_observation_digest": pre_observation_digest,
            "idempotency_keys": [op.idempotency_key for op in ir.ops],
        }
    )


def _payload_digest(
    candidate: FastPathCandidateV1,
    ir: ActionIRV1,
    precondition_checks: Mapping[str, PreconditionCheckV1],
    observation: ResourceObservationV1,
) -> str:
    return canonical_digest(
        {
            "candidate": candidate.as_dict(),
            "ir": ir.as_dict(),
            "preconditions": {key: value.as_dict() for key, value in sorted(precondition_checks.items())},
            "observation": observation.as_dict(),
        }
    )


def _parent_is_valid(
    parent: ParentFallbackV1 | None,
    candidate: FastPathCandidateV1,
    ir: ActionIRV1,
    context: ShadowQualificationContextV1,
) -> bool:
    if parent is None:
        return False
    return (
        parent.parent_candidate_id != candidate.candidate_id
        and parent.parent_body_generation < context.envelope.body_generation
        and parent.parent_stem_digest == ir.stem_digest == context.binding.stem_digest
        and parent.parent_objective_digest == ir.objective_digest == context.binding.objective_digest
        and parent.parent_app_identity == context.envelope.app_identity
        and parent.fallback_count <= 1
    )


def _ordered_reasons(reasons: Sequence[str]) -> tuple[str, ...]:
    unique = set(reasons)
    return tuple(reason for reason in _REASON_PRIORITY if reason in unique)


def qualify_shadow_candidate(
    candidate: FastPathCandidateV1,
    ir: ActionIRV1,
    context: ShadowQualificationContextV1,
    *,
    now_ms: int,
    pre_observation_digest: str,
    post_observation_digest: str,
    precondition_checks: Mapping[str, PreconditionCheckV1],
    observation: ResourceObservationV1,
    replay_index: ReplayIndexV1,
    parent_fallback: ParentFallbackV1 | None = None,
) -> ShadowQualificationResultV1:
    """Return a fail-closed shadow decision and an immutable replay index."""

    _require_nonnegative_int(now_ms, "now_ms")
    _require_digest(pre_observation_digest, "pre_observation_digest")
    _require_digest(post_observation_digest, "post_observation_digest")
    reasons: list[str] = []
    envelope = context.envelope
    binding = context.binding

    if candidate.app_identity != envelope.app_identity or ir.app_identity != envelope.app_identity:
        reasons.append("APP_IDENTITY_MISMATCH")
    if candidate.authorization_version != envelope.authorization_version:
        reasons.append("STALE_AUTHORIZATION")
    if not (envelope.issued_at_ms <= now_ms < envelope.expires_at_ms):
        reasons.append("EXPIRED")
    if candidate.revocation_epoch < envelope.revocation_epoch:
        reasons.append("REVOKED_CAPABILITY")
    elif candidate.revocation_epoch > envelope.revocation_epoch:
        reasons.append("FUTURE_REVOCATION_EPOCH")
    if candidate.body_generation < envelope.body_generation:
        reasons.append("GENERATION_STALE")
    elif candidate.body_generation > envelope.body_generation:
        reasons.append("FUTURE_GENERATION_REJECTED")
    if candidate.action_ir_digest != ir.digest:
        reasons.append("ARTIFACT_MISMATCH")
    if ir.stem_digest != binding.stem_digest:
        reasons.append("STEM_MISMATCH")
    if ir.head_digest != binding.head_digest:
        reasons.append("HEAD_MISMATCH")
    if ir.objective_digest != binding.objective_digest:
        reasons.append("OBJECTIVE_MISMATCH")
    if candidate.artifact_digest != binding.artifact_digest:
        reasons.append("ARTIFACT_MISMATCH")
    if candidate.runtime_tuple_digest != binding.runtime_tuple_digest:
        reasons.append("RUNTIME_TUPLE_MISMATCH")
    if candidate.snapshot_id != binding.snapshot_id:
        reasons.append("SNAPSHOT_MISMATCH")
    if candidate.policy_digest != context.policy_digest:
        reasons.append("POLICY_SCOPE_MISMATCH")
    if candidate.abi != binding.abi or ir.abi != binding.abi:
        reasons.append("ABI_MISMATCH")
    expected_target = "gpu" if candidate.backend == "cuda_graph" else "cpu"
    if candidate.target != expected_target or candidate.target != binding.target:
        reasons.append("ARTIFACT_TARGET_MISMATCH")
    if candidate.body_generation != ir.body_generation or candidate.revocation_epoch != ir.revocation_epoch:
        reasons.append("GENERATION_STALE")
    if candidate.capability_manifest_digest != context.capability_scope_digest:
        reasons.append("CAPABILITY_SCOPE_MISMATCH")
    if not set(ir.required_capabilities).issubset(set(envelope.capability_ids)):
        reasons.append("CAPABILITY_SCOPE_MISMATCH")
    if envelope.capability_scope_digest != context.capability_scope_digest or envelope.policy_digest != context.policy_digest:
        reasons.append("POLICY_SCOPE_MISMATCH")
    if set(candidate.resource_limits) != {"max_ops", "deadline_ms", "max_memory_bytes"}:
        reasons.append("BUDGET_EXCEEDED")
    else:
        if (
            candidate.resource_limits["max_ops"] > context.budget.max_ops
            or candidate.resource_limits["deadline_ms"] > context.budget.deadline_ms
            or candidate.resource_limits["max_memory_bytes"] > context.budget.max_memory_bytes
            or observation.over_budget(context.budget)
            or observation.observed_ops > candidate.resource_limits["max_ops"]
            or observation.elapsed_ms > candidate.resource_limits["deadline_ms"]
            or observation.peak_memory_bytes > candidate.resource_limits["max_memory_bytes"]
        ):
            reasons.append("BUDGET_EXCEEDED")
    op_keys = {op.idempotency_key for op in ir.ops}
    if set(precondition_checks) != op_keys:
        reasons.append("PRECONDITION_FAILED")
    else:
        for op in ir.ops:
            check = precondition_checks[op.idempotency_key]
            if check.expected_digest != op.precondition_digest or not check.passed:
                reasons.append("PRECONDITION_FAILED")
    if context.mode == "cpu_non_effect" and any(op.op in _EFFECT_OPS for op in ir.ops):
        reasons.append("EFFECT_REQUIRES_GUARDIAN")

    replay_key = _replay_key(candidate, ir, envelope, pre_observation_digest)
    payload_digest = _payload_digest(candidate, ir, precondition_checks, observation)
    replay_status = replay_index.lookup(replay_key, payload_digest)
    if replay_status is not None:
        reasons.append(replay_status)

    ordered = _ordered_reasons(reasons)
    if not ordered:
        status = "ADMIT_SHADOW"
        fallback_required = False
        next_replay = replay_index.record(replay_key, payload_digest)
        receipt_outcome = "shadow"
    else:
        status = ordered[0]
        fallback_required = True
        next_replay = replay_index
        receipt_outcome = "rejected"

    valid_parent = _parent_is_valid(parent_fallback, candidate, ir, context)
    if fallback_required:
        if valid_parent:
            status = "FALLBACK_PARENT"
        elif parent_fallback is None:
            status = "NO_SAFE_FALLBACK"

    receipt = build_shadow_receipt(
        candidate,
        app_identity=candidate.app_identity,
        pre_observation_digest=pre_observation_digest,
        post_observation_digest=post_observation_digest,
        capability_ids=tuple(sorted(set(ir.required_capabilities).intersection(envelope.capability_ids))),
        outcome=receipt_outcome,
    )
    decision = ShadowQualificationDecisionV1(
        candidate_id=candidate.candidate_id,
        status=status,
        reason_codes=ordered,
        context_digest=context.digest,
        fallback_required=fallback_required,
        parent_fallback=parent_fallback if valid_parent else None,
        receipt=receipt,
    )
    return ShadowQualificationResultV1(decision=decision, replay_index=next_replay)
