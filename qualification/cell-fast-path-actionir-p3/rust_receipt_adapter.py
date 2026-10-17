"""P3 shadow adapter for the existing Rust NeuronFeatureReceiptV1 boundary.

The adapter accepts only a previously verified source receipt. It does not
recompute the Rust canonical byte digest, run a model, call Guardian/TaskFlow,
or issue an owner capability. It records the source receipt digest and projects
its exact fields into the P2 Python shadow contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cell_fast_path_actionir import ActionIRV1, DENY_ALL, FastPathCandidateV1, _require_digest, _require_identifier, _require_nonnegative_int, canonical_digest
from owner_evidence_projection import GuardianEvidenceV1, NeuronFeatureReceiptProjectionV1, OwnerEvidenceProjectionV1, TaskFlowObserverReceiptV1, project_owner_shadow_evidence

SCHEMA = "hepta.cell.fast-path-rust-receipt-adapter.v1"
_STATUSES = frozenset({"Succeeded", "Failed", "Cancelled", "Indeterminate"})


@dataclass(frozen=True)
class RustNeuronReceiptViewV1:
    """Field-level view of a verified Rust receipt; source digest stays opaque."""

    source_commit_digest: str
    source_receipt_digest: str
    request_digest: str
    input_digest: str
    runtime_tuple_digest: str
    encoder_digest: str
    head_digest: str
    output_digest: str
    drive_vector_digest: str
    prediction_vector_digest: str
    status: str
    observed_memory_bytes: int
    transient_allocation_bytes: int
    queue_age_micros: int
    latency_micros: int
    authority: str = DENY_ALL
    source_verified: bool = False

    def __post_init__(self) -> None:
        for field in ("source_commit_digest", "source_receipt_digest", "request_digest", "input_digest", "runtime_tuple_digest", "encoder_digest", "head_digest", "output_digest", "drive_vector_digest", "prediction_vector_digest"):
            _require_digest(getattr(self, field), field)
        if self.status not in _STATUSES:
            raise ValueError("unsupported Rust terminal status")
        for field in ("observed_memory_bytes", "transient_allocation_bytes", "queue_age_micros", "latency_micros"):
            _require_nonnegative_int(getattr(self, field), field)
        if self.authority != DENY_ALL:
            raise ValueError("Rust receipt view cannot carry authority")
        if type(self.source_verified) is not bool:
            raise ValueError("source_verified must be bool")
        if self.status != "Succeeded" and (self.drive_vector_digest != "0" * 64 or self.prediction_vector_digest != "0" * 64):
            raise ValueError("non-succeeded Rust receipt must carry zero output-vector digests")

    def as_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA, **{field: getattr(self, field) for field in self.__dataclass_fields__}}


@dataclass(frozen=True)
class RustReceiptAdapterDecisionV1:
    status: str
    source_receipt_digest: str
    projection: OwnerEvidenceProjectionV1 | None
    reason_codes: tuple[str, ...]
    authority: str = DENY_ALL
    effect_admitted: bool = False

    def __post_init__(self) -> None:
        if self.status not in {"ADAPTED", "FALLBACK"}:
            raise ValueError("unsupported adapter decision")
        _require_digest(self.source_receipt_digest, "source_receipt_digest")
        object.__setattr__(self, "reason_codes", tuple(sorted(set(self.reason_codes))))
        if self.authority != DENY_ALL or self.effect_admitted:
            raise ValueError("P3 adapter cannot carry authority or admit effects")
        if self.status == "ADAPTED" and self.projection is None:
            raise ValueError("adapted result must carry a P2 projection")

    def as_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "status": self.status, "source_receipt_digest": self.source_receipt_digest, "projection": None if self.projection is None else self.projection.as_dict(), "reason_codes": list(self.reason_codes), "authority": self.authority, "effect_admitted": self.effect_admitted}


def adapt_verified_rust_receipt(
    candidate: FastPathCandidateV1,
    ir: ActionIRV1,
    rust: RustNeuronReceiptViewV1,
    guardian: GuardianEvidenceV1,
    taskflow: TaskFlowObserverReceiptV1,
    *,
    expected_request_digest: str,
    expected_input_digest: str,
    expected_scope_digest: str,
) -> RustReceiptAdapterDecisionV1:
    """Adapt only source-verified Rust evidence; no worker or owner calls."""
    _require_digest(expected_request_digest, "expected_request_digest")
    _require_digest(expected_input_digest, "expected_input_digest")
    _require_digest(expected_scope_digest, "expected_scope_digest")
    reasons: list[str] = []
    if not rust.source_verified:
        reasons.append("RUST_SOURCE_NOT_VERIFIED")
    if rust.request_digest != expected_request_digest:
        reasons.append("REQUEST_DIGEST_MISMATCH")
    if rust.input_digest != expected_input_digest:
        reasons.append("INPUT_DIGEST_MISMATCH")
    if rust.status != "Succeeded":
        reasons.append("RUST_NONTERMINAL_OR_FAILED")
    if reasons:
        return RustReceiptAdapterDecisionV1("FALLBACK", rust.source_receipt_digest, None, reasons)
    output_vector_digest = canonical_digest({"drive": rust.drive_vector_digest, "prediction": rust.prediction_vector_digest})
    projected = {
        "request_digest": rust.request_digest,
        "input_digest": rust.input_digest,
        "runtime_tuple_digest": rust.runtime_tuple_digest,
        "encoder_digest": rust.encoder_digest,
        "head_digest": rust.head_digest,
        "output_digest": rust.output_digest,
        "output_vector_digest": output_vector_digest,
        "status": "succeeded",
        "observed_memory_bytes": rust.observed_memory_bytes,
        "observed_transient_bytes": rust.transient_allocation_bytes,
        "observed_queue_age_ns": rust.queue_age_micros * 1000,
        "observed_latency_ns": rust.latency_micros * 1000,
        "model_id": "rust-neuron",
        "authority": DENY_ALL,
    }
    # The P2 projection receipt digest is canonical over its projected fields.
    payload = canonical_digest({"schema": "hepta.neuron.feature-receipt-projection.v1", **projected})
    projection_receipt = NeuronFeatureReceiptProjectionV1(receipt_digest=payload, **projected)
    projection = project_owner_shadow_evidence(candidate, ir, projection_receipt, guardian, taskflow, expected_request_digest=expected_request_digest, expected_input_digest=expected_input_digest, expected_scope_digest=expected_scope_digest)
    return RustReceiptAdapterDecisionV1("ADAPTED" if projection.status == "PROJECTED" else "FALLBACK", rust.source_receipt_digest, projection, projection.reason_codes)
