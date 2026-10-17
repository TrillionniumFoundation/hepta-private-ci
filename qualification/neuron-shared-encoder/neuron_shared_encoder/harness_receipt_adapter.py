"""Adapter from the registered Reader harness report to a pinned receipt.

The adapter records provenance; it never upgrades a local diagnostic to
REAL_SHADOW and never loads, scores, trains, selects, or activates a model.
"""
from __future__ import annotations
from typing import Any, Mapping
import hashlib
from .checkpoint_receipt import (PinnedCheckpointReceiptV1, INCOMPLETE, REAL_SHADOW,
                                 REAL_MODEL_LOCAL_QUALIFICATION, SYNTHETIC_SMOKE, HISTORICAL_REPLAY)

class HarnessReceiptAdapterError(ValueError): pass

def _str(m: Mapping[str,Any], *names):
    for n in names:
        v=m.get(n)
        if isinstance(v,str) and v: return v
    return None

def _bool(m: Mapping[str,Any], *names):
    for n in names:
        if n in m: return m[n]
    return None

def _digest_or_none(v): return v if isinstance(v,str) and len(v)==64 and all(c in '0123456789abcdef' for c in v) else None

def adapt_reader_report(report: Mapping[str,Any], *, candidate_id: str, task_id: str,
                        source_split: str, independent_new_source: bool = True) -> PinnedCheckpointReceiptV1:
    if not isinstance(report, Mapping): raise HarnessReceiptAdapterError("report must be a mapping")
    if report.get("production_selection_authority") not in (False, None): raise HarnessReceiptAdapterError("production authority is forbidden")
    if report.get("model_input_gold_visible") is True or report.get("current_run_mutation") is True:
        raise HarnessReceiptAdapterError("gold visibility or current-run mutation is forbidden")
    before=_str(report,"checkpoint_digest_before","model_snapshot_sha256_before")
    after=_str(report,"checkpoint_digest_after","model_snapshot_sha256_after","model_snapshot_sha256")
    if before and after and before != after: raise HarnessReceiptAdapterError("checkpoint changed during harness run")
    checkpoint_digest=_digest_or_none(after or _str(report,"checkpoint_digest"))
    values={
        "receipt_id": _str(report,"receipt_id") or f"harness.{candidate_id}.{task_id}",
        "candidate_id": candidate_id, "task_id": task_id, "source_split": source_split,
        "checkpoint_digest": checkpoint_digest,
        "model_digest": _digest_or_none(_str(report,"model_digest","model_snapshot_sha256")),
        "tokenizer_digest": _digest_or_none(_str(report,"tokenizer_digest")),
        "preprocessor_digest": _digest_or_none(_str(report,"preprocessor_digest")),
        "runtime_digest": _digest_or_none(_str(report,"runtime_digest")),
        "reader_manifest_digest": _digest_or_none(_str(report,"reader_manifest_digest","frozen_manifest_sha256")),
        "source_digest": _digest_or_none(_str(report,"source_digest","source_sha256")),
        "source_blob_digest": _str(report,"source_blob_digest","source_blob_sha"),
        "request_digest": _digest_or_none(_str(report,"request_digest")),
        "held_label_digest": _digest_or_none(_str(report,"held_label_digest","held_labels_digest")),
        "evidence_class": report.get("evidence_class") if report.get("evidence_class") in {REAL_SHADOW,REAL_MODEL_LOCAL_QUALIFICATION,SYNTHETIC_SMOKE,HISTORICAL_REPLAY} else INCOMPLETE,
        "checkpoint_loaded": _bool(report,"checkpoint_loaded") is True,
        "independent_new_source": independent_new_source,
        "model_input_gold_visible": False, "current_run_mutation": False,
        "authority":"DENY_ALL",
    }
    missing=[]
    for n in PinnedCheckpointReceiptV1._DIGEST_FIELDS:
        if values[n] is None: missing.append(n)
    if not values["checkpoint_loaded"]: missing.append("checkpoint_loaded")
    values["missing_fields"]=tuple(sorted(set(missing)))
    if missing:
        values["status"]="INCOMPLETE"; values["evidence_class"]=INCOMPLETE
    else:
        values["status"]="COMPLETE"
    return PinnedCheckpointReceiptV1(**values)

def require_real_shadow_from_report(report: Mapping[str,Any], **kwargs) -> PinnedCheckpointReceiptV1:
    receipt=adapt_reader_report(report, **kwargs)
    receipt.require_real_shadow()
    return receipt

__all__=["HarnessReceiptAdapterError","adapt_reader_report","require_real_shadow_from_report"]
