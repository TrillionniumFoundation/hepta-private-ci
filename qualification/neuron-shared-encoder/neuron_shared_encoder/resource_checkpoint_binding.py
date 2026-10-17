"""Three-way binding for checkpoint, component resource, and matrix identity.

A scalar cost record must never be detached from the model checkpoint or from
its candidate/window. This module is a provenance join only: it does not run a
model, train, select, activate, or grant authority.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
import hashlib, json, re
from typing import Any

from .checkpoint_receipt import PinnedCheckpointReceiptV1, CheckpointReceiptError, REAL_SHADOW

SCHEMA = "hepta.prospective.checkpoint-resource-binding.v1"
_IDENT = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

class CheckpointResourceBindingError(ValueError):
    pass

def _require(ok: bool, message: str) -> None:
    if not ok:
        raise CheckpointResourceBindingError(message)

def _identifier(name: str, value: str) -> None:
    _require(isinstance(value, str) and _IDENT.fullmatch(value) is not None, f"{name} is not a stable identifier")

def _digest(name: str, value: str) -> None:
    _require(isinstance(value, str) and _HEX64.fullmatch(value) is not None, f"{name} must be lowercase sha256")

def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()

@dataclass(frozen=True)
class CheckpointResourceBindingV1:
    binding_id: str
    candidate_id: str
    window_id: str
    checkpoint_receipt_digest: str
    resource_receipt_digest: str
    budget_digest: str
    evidence_class: str = REAL_SHADOW
    authority: str = "DENY_ALL"
    current_run_mutation: bool = False
    next_snapshot_only: bool = True

    def __post_init__(self) -> None:
        _identifier("binding_id", self.binding_id)
        _identifier("candidate_id", self.candidate_id)
        _identifier("window_id", self.window_id)
        for name, value in (("checkpoint_receipt_digest", self.checkpoint_receipt_digest),
                            ("resource_receipt_digest", self.resource_receipt_digest),
                            ("budget_digest", self.budget_digest)):
            _digest(name, value)
        _require(self.evidence_class == REAL_SHADOW, "binding requires raw REAL_SHADOW evidence")
        _require(self.authority == "DENY_ALL", "binding authority is always DENY_ALL")
        _require(type(self.current_run_mutation) is bool and not self.current_run_mutation, "current run mutation is forbidden")
        _require(type(self.next_snapshot_only) is bool and self.next_snapshot_only, "binding is next-snapshot-only")

    @property
    def binding_digest(self) -> str:
        return _sha(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        result = {"schema": SCHEMA, **asdict(self)}
        if include_digest:
            result["binding_digest"] = self.binding_digest
        return result

def bind_checkpoint_resource(checkpoint: PinnedCheckpointReceiptV1, resource: Any, *, window_id: str,
                             binding_id: str | None = None) -> CheckpointResourceBindingV1:
    """Join a complete checkpoint receipt to one complete component receipt."""
    if not isinstance(checkpoint, PinnedCheckpointReceiptV1):
        raise CheckpointResourceBindingError("checkpoint must be PinnedCheckpointReceiptV1")
    _require(checkpoint.complete, "incomplete checkpoint cannot bind a resource receipt")
    _require(checkpoint.evidence_class == REAL_SHADOW, "only REAL_SHADOW checkpoint evidence can bind")
    _identifier("window_id", window_id)
    _require(getattr(resource, "complete", False), "incomplete resource cannot bind")
    _require(getattr(resource, "evidence_class", None) == REAL_SHADOW, "only REAL_SHADOW resource can bind")
    _require(getattr(resource, "candidate_id", None) == checkpoint.candidate_id, "candidate_id mismatch")
    for name in ("model_digest", "tokenizer_digest", "preprocessor_digest", "runtime_digest", "source_digest", "source_blob_digest"):
        _require(getattr(resource, name, None) == getattr(checkpoint, name), f"{name} mismatch")
    resource_digest = getattr(resource, "receipt_digest", None)
    _digest("resource_receipt_digest", resource_digest)
    budget_digest = getattr(resource, "budget_digest", None)
    _digest("budget_digest", budget_digest)
    return CheckpointResourceBindingV1(
        binding_id=binding_id or f"binding.{checkpoint.candidate_id}.{window_id}",
        candidate_id=checkpoint.candidate_id,
        window_id=window_id,
        checkpoint_receipt_digest=checkpoint.receipt_digest,
        resource_receipt_digest=resource_digest,
        budget_digest=budget_digest,
    )

__all__ = ["SCHEMA", "CheckpointResourceBindingError", "CheckpointResourceBindingV1", "bind_checkpoint_resource"]
