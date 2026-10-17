"""Pinned checkpoint identity receipts for a future real transfer run.

This module is deliberately a provenance boundary.  It does not load a
checkpoint or evaluate a model.  A later harness adapter may construct the
receipt only after it has measured the exact checkpoint bundle and source
checkout.  The raw evidence class is retained; local qualification is never
silently promoted to a real shadow result.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from typing import Any, Mapping


SCHEMA_CHECKPOINT = "hepta.prospective.pinned-checkpoint-receipt.v1"
REAL_SHADOW = "REAL_SHADOW"
REAL_MODEL_LOCAL_QUALIFICATION = "REAL_MODEL_LOCAL_QUALIFICATION"
SYNTHETIC_SMOKE = "SYNTHETIC_SMOKE"
HISTORICAL_REPLAY = "HISTORICAL_REPLAY"
INCOMPLETE = "INCOMPLETE"
EVIDENCE_CLASSES = {
    REAL_SHADOW,
    REAL_MODEL_LOCAL_QUALIFICATION,
    SYNTHETIC_SMOKE,
    HISTORICAL_REPLAY,
    INCOMPLETE,
}
SOURCE_SPLITS = {"future", "ood"}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_IDENT = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")


class CheckpointReceiptError(ValueError):
    """Raised when a pinned checkpoint identity is not auditable."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckpointReceiptError(message)


def _digest(name: str, value: str) -> None:
    _require(isinstance(value, str) and _HEX64.fullmatch(value) is not None, f"{name} must be a lowercase sha256")


def _blob(name: str, value: str) -> None:
    _require(isinstance(value, str) and _HEX40.fullmatch(value) is not None, f"{name} must be a lowercase Git SHA-1")


def _identifier(name: str, value: str) -> None:
    _require(isinstance(value, str) and _IDENT.fullmatch(value) is not None, f"{name} is not a stable identifier")


def _boolean(name: str, value: Any) -> None:
    _require(type(value) is bool, f"{name} must be a boolean")


def _integer(name: str, value: Any, *, minimum: int = 0) -> None:
    _require(type(value) is int and value >= minimum, f"{name} must be an integer >= {minimum}")


def _canonical_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PinnedCheckpointReceiptV1:
    """Exact model/runtime/source identity for one frozen evaluation.

    ``COMPLETE`` means every identity field was observed by an external
    harness.  ``INCOMPLETE`` is retained for diagnosis and can never be
    converted into a transfer, OPE, System2, or split receipt.
    """

    receipt_id: str
    candidate_id: str
    task_id: str
    source_split: str
    checkpoint_digest: str | None
    model_digest: str | None
    tokenizer_digest: str | None
    preprocessor_digest: str | None
    runtime_digest: str | None
    reader_manifest_digest: str | None
    source_digest: str | None
    source_blob_digest: str | None
    request_digest: str | None
    held_label_digest: str | None
    evidence_class: str
    checkpoint_loaded: bool
    independent_new_source: bool
    model_input_gold_visible: bool = False
    current_run_mutation: bool = False
    authority: str = "DENY_ALL"
    status: str = "COMPLETE"
    missing_fields: tuple[str, ...] = ()

    _DIGEST_FIELDS = (
        "checkpoint_digest",
        "model_digest",
        "tokenizer_digest",
        "preprocessor_digest",
        "runtime_digest",
        "reader_manifest_digest",
        "source_digest",
        "source_blob_digest",
        "request_digest",
        "held_label_digest",
    )

    def __post_init__(self) -> None:
        _identifier("receipt_id", self.receipt_id)
        _identifier("candidate_id", self.candidate_id)
        _identifier("task_id", self.task_id)
        _require(self.source_split in SOURCE_SPLITS, "checkpoint evidence must use future or OOD source")
        _require(self.evidence_class in EVIDENCE_CLASSES, "unknown checkpoint evidence class")
        _require(self.status in {"COMPLETE", "INCOMPLETE"}, "status must be COMPLETE or INCOMPLETE")
        _boolean("checkpoint_loaded", self.checkpoint_loaded)
        _boolean("independent_new_source", self.independent_new_source)
        _boolean("model_input_gold_visible", self.model_input_gold_visible)
        _boolean("current_run_mutation", self.current_run_mutation)
        _require(self.independent_new_source, "checkpoint evidence requires an independent source")
        _require(not self.model_input_gold_visible, "gold cannot be model-visible")
        _require(not self.current_run_mutation, "checkpoint receipt cannot mutate the current run")
        _require(self.authority == "DENY_ALL", "checkpoint receipt authority is always DENY_ALL")

        actual_missing: list[str] = []
        for name in self._DIGEST_FIELDS:
            value = getattr(self, name)
            if value is None:
                actual_missing.append(name)
                continue
            if name == "source_blob_digest":
                _blob(name, value)
            else:
                _digest(name, value)
        if not self.checkpoint_loaded:
            actual_missing.append("checkpoint_loaded")
        actual_missing_tuple = tuple(sorted(set(actual_missing)))
        _require(tuple(sorted(self.missing_fields)) == self.missing_fields, "missing_fields must be sorted")
        _require(actual_missing_tuple == self.missing_fields, "missing_fields must exactly describe missing identity")
        if self.status == "COMPLETE":
            _require(not actual_missing_tuple, "complete checkpoint receipt has missing identity")
            _require(self.evidence_class != INCOMPLETE, "complete checkpoint receipt cannot use INCOMPLETE evidence")
        else:
            _require(bool(actual_missing_tuple), "incomplete checkpoint receipt must identify missing fields")
            _require(self.evidence_class == INCOMPLETE, "incomplete evidence must remain INCOMPLETE")

        # A real class is meaningful only when the harness actually loaded the
        # pinned bundle.  Synthetic/replay receipts may be complete as protocol
        # fixtures, but they cannot be adapted to the strict real gate.
        if self.evidence_class in {REAL_SHADOW, REAL_MODEL_LOCAL_QUALIFICATION}:
            _require(self.checkpoint_loaded, "real checkpoint evidence requires a loaded checkpoint")

    @property
    def complete(self) -> bool:
        return self.status == "COMPLETE" and not self.missing_fields

    @property
    def receipt_digest(self) -> str:
        return _canonical_digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        result = {"schema": SCHEMA_CHECKPOINT, **asdict(self)}
        result["missing_fields"] = list(self.missing_fields)
        if include_digest:
            result["receipt_digest"] = self.receipt_digest
        return result

    def require_real_shadow(self) -> None:
        """Require this exact receipt to be eligible for a strict shadow run."""
        _require(self.complete, "incomplete checkpoint receipt cannot enter a real gate")
        _require(self.evidence_class == REAL_SHADOW, "only raw REAL_SHADOW evidence can enter a strict shadow gate")

    def bind_identity(self, other: Any) -> None:
        """Check a component/resource receipt carries the same pinned identity."""
        _require(self.complete, "checkpoint receipt is incomplete")
        for name in (
            "model_digest",
            "tokenizer_digest",
            "preprocessor_digest",
            "runtime_digest",
            "source_digest",
            "source_blob_digest",
        ):
            _require(getattr(other, name, None) == getattr(self, name), f"{name} mismatch")


__all__ = [
    "CheckpointReceiptError",
    "EVIDENCE_CLASSES",
    "HISTORICAL_REPLAY",
    "INCOMPLETE",
    "PinnedCheckpointReceiptV1",
    "REAL_MODEL_LOCAL_QUALIFICATION",
    "REAL_SHADOW",
    "SCHEMA_CHECKPOINT",
    "SOURCE_SPLITS",
    "SYNTHETIC_SMOKE",
]
