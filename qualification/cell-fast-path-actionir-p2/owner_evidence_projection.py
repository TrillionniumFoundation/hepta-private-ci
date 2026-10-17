"""P2 shadow projection for exact Neuron/Guardian/TaskFlow owner evidence.

This module is deliberately a pure, research-only adapter contract.  It does
not call Guardian, TaskFlow, Agentd, a model worker, a GPU driver, or any
external provider.  It projects already authenticated evidence into a
candidate-bound receipt and fails closed on tuple, input, authorization, or
terminal-status drift.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from cell_fast_path_actionir import (
    ActionIRV1,
    DENY_ALL,
    FastPathCandidateV1,
    _require_digest,
    _require_identifier,
    _require_nonnegative_int,
    canonical_digest,
)

SCHEMA = "hepta.cell.fast-path-owner-evidence-projection.v1"
_MODEL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "indeterminate"})
_GUARDIAN_DECISIONS = frozenset({"eligible", "fallback"})


@dataclass(frozen=True)
class NeuronFeatureReceiptProjectionV1:
    """Read-only projection of the Rust NeuronFeatureReceiptV1 boundary."""

    request_digest: str
    input_digest: str
    runtime_tuple_digest: str
    encoder_digest: str
    head_digest: str
    output_digest: str | None
    status: str
    observed_memory_bytes: int
    observed_transient_bytes: int
    observed_queue_age_ns: int
    observed_latency_ns: int
    receipt_digest: str
    output_vector_digest: str | None = None
    model_id: str = "shadow-model"
    authority: str = DENY_ALL

    def __post_init__(self) -> None:
        for field in ("request_digest", "input_digest", "runtime_tuple_digest", "encoder_digest", "head_digest", "receipt_digest"):
            _require_digest(getattr(self, field), field)
        for field in ("output_digest", "output_vector_digest"):
            value = getattr(self, field)
            if value is not None:
                _require_digest(value, field)
        if self.status not in _MODEL_STATUSES:
            raise ValueError("unsupported Neuron feature status")
        for field in ("observed_memory_bytes", "observed_transient_bytes", "observed_queue_age_ns", "observed_latency_ns"):
            _require_nonnegative_int(getattr(self, field), field)
        _require_identifier(self.model_id, "model_id")
        if self.authority != DENY_ALL:
            raise ValueError("Neuron projection cannot carry authority")
        if self.status == "succeeded":
            if self.output_digest is None or self.output_vector_digest is None:
                raise ValueError("succeeded receipt must carry output digests")
        elif self.output_digest is not None or self.output_vector_digest is not None:
            raise ValueError("nonterminal or failed receipt cannot carry output vectors")
        expected = self._receipt_payload_digest()
        if self.receipt_digest != expected:
            raise ValueError("receipt_digest does not bind the exact receipt payload")

    def _receipt_payload_digest(self) -> str:
        return canonical_digest({
            "schema": "hepta.neuron.feature-receipt-projection.v1",
            "request_digest": self.request_digest,
            "input_digest": self.input_digest,
            "runtime_tuple_digest": self.runtime_tuple_digest,
            "encoder_digest": self.encoder_digest,
            "head_digest": self.head_digest,
            "output_digest": self.output_digest,
            "output_vector_digest": self.output_vector_digest,
            "status": self.status,
            "observed_memory_bytes": self.observed_memory_bytes,
            "observed_transient_bytes": self.observed_transient_bytes,
            "observed_queue_age_ns": self.observed_queue_age_ns,
            "observed_latency_ns": self.observed_latency_ns,
            "model_id": self.model_id,
            "authority": self.authority,
        })

    def as_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA, **{field: getattr(self, field) for field in self.__dataclass_fields__}}


@dataclass(frozen=True)
class GuardianEvidenceV1:
    """Observer evidence; eligibility is not an authorization grant."""

    enabled: bool
    scope_digest: str
    authorization_version: str
    score_fresh: bool
    newer_failed_classification: bool
    action_risk: float
    risk_threshold: float
    decision: str
    evidence_digest: str
    authority: str = DENY_ALL

    def __post_init__(self) -> None:
        for field in ("scope_digest", "authorization_version", "evidence_digest"):
            _require_digest(getattr(self, field), field)
        for field in ("enabled", "score_fresh", "newer_failed_classification"):
            if type(getattr(self, field)) is not bool:
                raise ValueError(f"{field} must be bool")
        if not (isinstance(self.action_risk, (int, float)) and self.action_risk == self.action_risk and self.action_risk >= 0):
            raise ValueError("action_risk must be finite and nonnegative")
        if not (isinstance(self.risk_threshold, (int, float)) and self.risk_threshold == self.risk_threshold and self.risk_threshold > 0):
            raise ValueError("risk_threshold must be finite and positive")
        if self.decision not in _GUARDIAN_DECISIONS:
            raise ValueError("unsupported Guardian evidence decision")
        if self.authority != DENY_ALL:
            raise ValueError("Guardian evidence cannot carry authority")
        expected_eligible = self.enabled and self.score_fresh and not self.newer_failed_classification and self.action_risk < self.risk_threshold
        if (self.decision == "eligible") != expected_eligible:
            raise ValueError("Guardian decision does not match freshness/risk predicates")
        expected_digest = canonical_digest({
            "schema": "hepta.guardian.fast-decision-evidence.v1",
            "enabled": self.enabled,
            "scope_digest": self.scope_digest,
            "authorization_version": self.authorization_version,
            "score_fresh": self.score_fresh,
            "newer_failed_classification": self.newer_failed_classification,
            "action_risk": self.action_risk,
            "risk_threshold": self.risk_threshold,
            "decision": self.decision,
            "authority": self.authority,
        })
        if self.evidence_digest != expected_digest:
            raise ValueError("Guardian evidence digest drift")

    def as_dict(self) -> dict[str, Any]:
        return {"schema": "hepta.guardian.fast-decision-evidence.v1", **{field: getattr(self, field) for field in self.__dataclass_fields__}}


@dataclass(frozen=True)
class TaskFlowObserverReceiptV1:
    """TaskFlow observation only; it cannot assert a terminal effect."""

    intent_digest: str
    payload_digest: str
    fence_digest: str
    event_seq: int
    observed: bool
    final_outcome: str | None = None
    terminal_claim: bool = False
    authority: str = DENY_ALL

    def __post_init__(self) -> None:
        for field in ("intent_digest", "payload_digest", "fence_digest"):
            _require_digest(getattr(self, field), field)
        _require_nonnegative_int(self.event_seq, "event_seq")
        if type(self.observed) is not bool:
            raise ValueError("observed must be bool")
        if type(self.terminal_claim) is not bool or self.terminal_claim:
            raise ValueError("TaskFlow observer cannot claim terminal effect")
        if self.final_outcome is not None:
            _require_identifier(self.final_outcome, "final_outcome")
        if self.authority != DENY_ALL:
            raise ValueError("TaskFlow observer cannot carry authority")

    @property
    def digest(self) -> str:
        return canonical_digest({"schema": "hepta.taskflow.observer-receipt.v1", **{field: getattr(self, field) for field in self.__dataclass_fields__}})

    def as_dict(self) -> dict[str, Any]:
        return {"schema": "hepta.taskflow.observer-receipt.v1", **{field: getattr(self, field) for field in self.__dataclass_fields__}}


@dataclass(frozen=True)
class OwnerEvidenceProjectionV1:
    candidate_id: str
    app_identity: str
    action_ir_digest: str
    runtime_tuple_digest: str
    snapshot_id: str
    neuron_receipt_digest: str
    guardian_evidence_digest: str
    taskflow_observer_digest: str
    status: str
    reason_codes: tuple[str, ...]
    projection_digest: str
    effect_admitted: bool = False
    authority: str = DENY_ALL

    def __post_init__(self) -> None:
        for field in ("candidate_id", "app_identity", "snapshot_id"):
            _require_identifier(getattr(self, field), field)
        for field in ("action_ir_digest", "runtime_tuple_digest", "neuron_receipt_digest", "guardian_evidence_digest", "taskflow_observer_digest", "projection_digest"):
            _require_digest(getattr(self, field), field)
        _require_identifier(self.status, "status")
        object.__setattr__(self, "reason_codes", tuple(sorted(set(self.reason_codes))))
        if type(self.effect_admitted) is not bool or self.effect_admitted:
            raise ValueError("owner projection cannot admit effects")
        if self.authority != DENY_ALL:
            raise ValueError("owner projection cannot carry authority")

    def as_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA, **{field: getattr(self, field) for field in self.__dataclass_fields__}}


def project_owner_shadow_evidence(
    candidate: FastPathCandidateV1,
    ir: ActionIRV1,
    neuron: NeuronFeatureReceiptProjectionV1,
    guardian: GuardianEvidenceV1,
    taskflow: TaskFlowObserverReceiptV1,
    *,
    expected_input_digest: str,
    expected_scope_digest: str,
) -> OwnerEvidenceProjectionV1:
    """Project exact owner evidence; never admits an effect or calls an owner."""
    _require_digest(expected_input_digest, "expected_input_digest")
    _require_digest(expected_scope_digest, "expected_scope_digest")
    reasons: list[str] = []
    if candidate.action_ir_digest != ir.digest:
        reasons.append("ACTION_IR_MISMATCH")
    if candidate.app_identity != ir.app_identity:
        reasons.append("APP_IDENTITY_MISMATCH")
    if neuron.input_digest != expected_input_digest:
        reasons.append("INPUT_DIGEST_MISMATCH")
    if neuron.runtime_tuple_digest != candidate.runtime_tuple_digest:
        reasons.append("RUNTIME_TUPLE_MISMATCH")
    if guardian.scope_digest != expected_scope_digest:
        reasons.append("GUARDIAN_SCOPE_MISMATCH")
    if guardian.authorization_version != candidate.authorization_version:
        reasons.append("AUTHORIZATION_MISMATCH")
    if neuron.status != "succeeded":
        reasons.append("NEURON_NONTERMINAL_OR_FAILED")
    if guardian.decision != "eligible":
        reasons.append("GUARDIAN_FALLBACK")
    if taskflow.terminal_claim:
        reasons.append("TASKFLOW_TERMINAL_CLAIM")
    status = "PROJECTED" if not reasons else "FALLBACK"
    payload = {
        "candidate_id": candidate.candidate_id,
        "app_identity": candidate.app_identity,
        "action_ir_digest": ir.digest,
        "runtime_tuple_digest": candidate.runtime_tuple_digest,
        "snapshot_id": candidate.snapshot_id,
        "neuron_receipt_digest": neuron.receipt_digest,
        "guardian_evidence_digest": guardian.evidence_digest,
        "taskflow_observer_digest": taskflow.digest,
        "status": status,
        "reason_codes": sorted(set(reasons)),
        "effect_admitted": False,
        "authority": DENY_ALL,
    }
    projection_digest = canonical_digest({"schema": SCHEMA, **payload})
    return OwnerEvidenceProjectionV1(projection_digest=projection_digest, **payload)
