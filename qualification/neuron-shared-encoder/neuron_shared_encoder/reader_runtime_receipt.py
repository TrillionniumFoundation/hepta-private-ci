"""Fail-closed Reader runtime and calibration receipts.

This module is a provenance boundary.  It records the fields required to join a
real Reader run to resource accounting and calibration evidence, but it never
runs a model, selects a Cell, grants authority, or upgrades local qualification
to REAL_SHADOW. Missing measurements or source-isolation declarations remain
INCOMPLETE; absence is never evidence of independence or hidden gold.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping

SCHEMA_RUNTIME = "hepta.sngr.reader-runtime-receipt.v1"
SCHEMA_CALIBRATION = "hepta.sngr.reader-calibration-receipt.v1"
REAL_SHADOW = "REAL_SHADOW"
REAL_MODEL_LOCAL_QUALIFICATION = "REAL_MODEL_LOCAL_QUALIFICATION"
INCOMPLETE = "INCOMPLETE"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENT = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")
_SPLITS = {"future", "ood"}


class ReaderRuntimeReceiptError(ValueError):
    pass


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise ReaderRuntimeReceiptError(message)


def _id(name: str, value: Any) -> None:
    _require(
        isinstance(value, str) and _IDENT.fullmatch(value) is not None,
        f"{name} is not a stable identifier",
    )


def _sha(name: str, value: Any) -> None:
    _require(
        isinstance(value, str) and _HEX64.fullmatch(value) is not None,
        f"{name} must be lowercase sha256",
    )


def _finite(name: str, value: Any) -> None:
    _require(
        type(value) in (int, float)
        and math.isfinite(float(value))
        and float(value) >= 0.0,
        f"{name} must be finite and non-negative",
    )


def _positive_int(name: str, value: Any) -> None:
    _require(type(value) is int and value > 0, f"{name} must be a positive integer")


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _missing(values: Mapping[str, Any], fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(name for name in fields if values.get(name) is None))


def _require_context_bindings(
    payload: Mapping[str, Any], *, candidate_id: str, source_split: str
) -> None:
    for name, expected in (
        ("candidate_id", candidate_id),
        ("source_split", source_split),
    ):
        if name in payload:
            _require(
                type(payload[name]) is str and payload[name] == expected,
                f"caller {name} must match payload evidence",
            )


@dataclass(frozen=True)
class ReaderRuntimeReceiptV1:
    """Device and end-to-end cost receipt for one Reader evaluation."""

    receipt_id: str
    candidate_id: str
    checkpoint_receipt_digest: str | None
    runtime_digest: str | None
    device_id: str | None
    device_digest: str | None
    device_kind: str | None
    precision: str | None
    device_count: int | None
    forward_calls: int | None
    input_tokens: int | None
    flops: float | None
    peak_memory_bytes: float | None
    p95_latency_ms: float | None
    energy_mj: float | None
    probability_digest: str | None
    sample_count: int | None
    source_split: str
    evidence_class: str
    raw_evidence_class: str | None = None
    independent_new_source: bool | None = None
    model_input_gold_visible: bool | None = None
    status: str = "COMPLETE"
    missing_fields: tuple[str, ...] = ()
    authority: str = "DENY_ALL"
    next_snapshot_only: bool = True

    _REQUIRED = (
        "checkpoint_receipt_digest",
        "runtime_digest",
        "device_id",
        "device_digest",
        "device_kind",
        "precision",
        "device_count",
        "forward_calls",
        "input_tokens",
        "flops",
        "peak_memory_bytes",
        "p95_latency_ms",
        "energy_mj",
        "probability_digest",
        "sample_count",
        "independent_new_source",
        "model_input_gold_visible",
    )

    def __post_init__(self) -> None:
        _id("receipt_id", self.receipt_id)
        _id("candidate_id", self.candidate_id)
        _require(self.source_split in _SPLITS, "source_split must be future or ood")
        _require(
            self.evidence_class
            in {REAL_SHADOW, REAL_MODEL_LOCAL_QUALIFICATION, INCOMPLETE},
            "unknown runtime evidence class",
        )
        _require(
            self.raw_evidence_class
            in {None, REAL_SHADOW, REAL_MODEL_LOCAL_QUALIFICATION, INCOMPLETE},
            "unknown raw runtime evidence class",
        )
        _require(
            self.status in {"COMPLETE", "INCOMPLETE"},
            "status must be COMPLETE or INCOMPLETE",
        )
        _require(
            self.authority == "DENY_ALL", "runtime receipt authority is always DENY_ALL"
        )
        _require(
            self.independent_new_source is None
            or (
                type(self.independent_new_source) is bool
                and self.independent_new_source
            ),
            "independent source must be explicitly true or unknown",
        )
        _require(
            self.model_input_gold_visible is None
            or (
                type(self.model_input_gold_visible) is bool
                and not self.model_input_gold_visible
            ),
            "model-visible gold must be explicitly false or unknown",
        )
        _require(
            type(self.next_snapshot_only) is bool and self.next_snapshot_only,
            "runtime receipt is next-snapshot-only",
        )
        for name in (
            "checkpoint_receipt_digest",
            "runtime_digest",
            "device_digest",
            "probability_digest",
        ):
            value = getattr(self, name)
            if value is not None:
                _sha(name, value)
        for name in ("device_id", "device_kind", "precision"):
            value = getattr(self, name)
            if value is not None:
                _require(
                    isinstance(value, str) and bool(value), f"{name} must be non-empty"
                )
        for name in ("device_count", "forward_calls", "input_tokens", "sample_count"):
            value = getattr(self, name)
            if value is not None:
                _positive_int(name, value)
        for name in ("flops", "peak_memory_bytes", "p95_latency_ms", "energy_mj"):
            value = getattr(self, name)
            if value is not None:
                _finite(name, value)
        actual = _missing(asdict(self), self._REQUIRED)
        _require(
            tuple(sorted(self.missing_fields)) == self.missing_fields,
            "missing_fields must be sorted",
        )
        _require(
            actual == self.missing_fields,
            "missing_fields must exactly describe missing runtime fields",
        )
        if self.status == "COMPLETE":
            _require(not actual, "complete runtime receipt has missing fields")
            _require(
                self.evidence_class != INCOMPLETE,
                "complete runtime receipt cannot be INCOMPLETE",
            )
        else:
            _require(
                bool(actual), "incomplete runtime receipt must identify missing fields"
            )
            _require(
                self.evidence_class == INCOMPLETE,
                "incomplete runtime evidence must remain INCOMPLETE",
            )

    @property
    def complete(self) -> bool:
        return self.status == "COMPLETE" and not self.missing_fields

    @property
    def receipt_digest(self) -> str:
        return _digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        result = {"schema": SCHEMA_RUNTIME, **asdict(self)}
        result["missing_fields"] = list(self.missing_fields)
        if include_digest:
            result["receipt_digest"] = self.receipt_digest
        return result


@dataclass(frozen=True)
class CalibrationReceiptV1:
    """Independent held-out calibration evidence; invalid/absent data is incomplete."""

    calibration_id: str
    candidate_id: str
    source_split: str
    heldout: bool
    sample_count: int | None
    probability_digest: str | None
    metric_digest: str | None
    brier: float | None
    ece: float | None
    evidence_class: str
    raw_evidence_class: str | None = None
    independent_new_source: bool | None = None
    status: str = "COMPLETE"
    missing_fields: tuple[str, ...] = ()
    authority: str = "DENY_ALL"
    next_snapshot_only: bool = True

    _REQUIRED = (
        "sample_count",
        "probability_digest",
        "metric_digest",
        "brier",
        "ece",
        "independent_new_source",
    )

    def __post_init__(self) -> None:
        _id("calibration_id", self.calibration_id)
        _id("candidate_id", self.candidate_id)
        _require(
            self.source_split in _SPLITS,
            "calibration source_split must be future or ood",
        )
        _require(type(self.heldout) is bool, "heldout must be a boolean")
        _require(
            self.evidence_class
            in {REAL_SHADOW, REAL_MODEL_LOCAL_QUALIFICATION, INCOMPLETE},
            "unknown calibration evidence class",
        )
        _require(
            self.raw_evidence_class
            in {None, REAL_SHADOW, REAL_MODEL_LOCAL_QUALIFICATION, INCOMPLETE},
            "unknown raw calibration evidence class",
        )
        _require(
            self.status in {"COMPLETE", "INCOMPLETE"},
            "status must be COMPLETE or INCOMPLETE",
        )
        _require(
            self.authority == "DENY_ALL", "calibration authority is always DENY_ALL"
        )
        _require(
            self.independent_new_source is None
            or (
                type(self.independent_new_source) is bool
                and self.independent_new_source
            ),
            "calibration independence must be explicitly true or unknown",
        )
        _require(
            type(self.next_snapshot_only) is bool and self.next_snapshot_only,
            "calibration is next-snapshot-only",
        )
        for name in ("probability_digest", "metric_digest"):
            value = getattr(self, name)
            if value is not None:
                _sha(name, value)
        if self.sample_count is not None:
            _positive_int("sample_count", self.sample_count)
        for name in ("brier", "ece"):
            value = getattr(self, name)
            if value is not None:
                _finite(name, value)
                _require(float(value) <= 1.0, f"{name} must be <= 1")
        actual_list = list(_missing(asdict(self), self._REQUIRED))
        if not self.heldout:
            actual_list.append("heldout")
        actual = tuple(sorted(set(actual_list)))
        _require(
            tuple(sorted(self.missing_fields)) == self.missing_fields,
            "missing_fields must be sorted",
        )
        _require(
            actual == self.missing_fields,
            "missing_fields must exactly describe missing calibration fields",
        )
        if self.status == "COMPLETE":
            _require(
                not actual and self.heldout,
                "complete calibration receipt must be held out",
            )
            _require(
                self.evidence_class != INCOMPLETE,
                "complete calibration receipt cannot be INCOMPLETE",
            )
        else:
            _require(
                bool(actual),
                "incomplete calibration receipt must identify missing fields",
            )
            _require(
                self.evidence_class == INCOMPLETE,
                "incomplete calibration evidence must remain INCOMPLETE",
            )

    @property
    def complete(self) -> bool:
        return self.status == "COMPLETE" and not self.missing_fields

    @property
    def receipt_digest(self) -> str:
        return _digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        result = {"schema": SCHEMA_CALIBRATION, **asdict(self)}
        result["missing_fields"] = list(self.missing_fields)
        if include_digest:
            result["receipt_digest"] = self.receipt_digest
        return result


def adapt_runtime_receipt(
    payload: Mapping[str, Any],
    *,
    candidate_id: str,
    source_split: str,
    checkpoint_receipt_digest: str | None = None,
) -> ReaderRuntimeReceiptV1:
    """Preserve reported identity; a caller may supply a missing checkpoint join.

    Candidate and split fields, when present, must corroborate the caller's
    context. An external checkpoint binding cannot replace a reported digest.
    Runtime digest aliases must agree when both are present, including nulls.
    Neither a supplied join nor matching context authenticates the evidence.
    """
    if not isinstance(payload, Mapping):
        raise ReaderRuntimeReceiptError("runtime payload must be a mapping")
    _require_context_bindings(
        payload, candidate_id=candidate_id, source_split=source_split
    )
    if checkpoint_receipt_digest is not None:
        _sha("caller checkpoint_receipt_digest", checkpoint_receipt_digest)
        reported_checkpoint = payload.get("checkpoint_receipt_digest")
        _require(
            reported_checkpoint is None
            or reported_checkpoint == checkpoint_receipt_digest,
            "caller checkpoint_receipt_digest must match payload evidence",
        )
    for name in ("runtime_digest", "runtime_receipt_digest"):
        if name in payload and payload[name] is not None:
            _sha(name, payload[name])
    if "runtime_digest" in payload and "runtime_receipt_digest" in payload:
        _require(
            payload["runtime_digest"] == payload["runtime_receipt_digest"],
            "runtime digest aliases must match payload evidence",
        )
    raw = payload.get("evidence_class")
    raw_class = (
        raw
        if raw in {REAL_SHADOW, REAL_MODEL_LOCAL_QUALIFICATION, INCOMPLETE}
        else INCOMPLETE
    )
    values = {name: payload.get(name) for name in ReaderRuntimeReceiptV1._REQUIRED}
    values["checkpoint_receipt_digest"] = (
        checkpoint_receipt_digest
        if checkpoint_receipt_digest is not None
        else payload.get("checkpoint_receipt_digest")
    )
    values["runtime_digest"] = (
        payload["runtime_digest"]
        if "runtime_digest" in payload
        else payload.get("runtime_receipt_digest")
    )
    values["device_id"] = payload.get("device_id")
    values["device_digest"] = payload.get("device_digest")
    values["device_kind"] = payload.get("device_kind")
    values["precision"] = payload.get("precision")
    values["device_count"] = payload.get("device_count")
    values["forward_calls"] = payload.get("forward_calls", payload.get("calls"))
    values["input_tokens"] = payload.get(
        "input_tokens", payload.get("charged_input_tokens")
    )
    values["flops"] = payload.get("flops")
    values["peak_memory_bytes"] = payload.get(
        "peak_memory_bytes", payload.get("memory_bytes")
    )
    values["p95_latency_ms"] = payload.get("p95_latency_ms", payload.get("latency_ms"))
    values["energy_mj"] = payload.get("energy_mj")
    values["probability_digest"] = payload.get("probability_digest")
    values["sample_count"] = payload.get("sample_count")
    missing = _missing(values, ReaderRuntimeReceiptV1._REQUIRED)
    return ReaderRuntimeReceiptV1(
        receipt_id=str(payload.get("receipt_id") or "runtime." + candidate_id),
        candidate_id=candidate_id,
        source_split=source_split,
        evidence_class=raw_class if not missing else INCOMPLETE,
        raw_evidence_class=raw_class,
        status="COMPLETE" if not missing else "INCOMPLETE",
        missing_fields=missing,
        authority="DENY_ALL",
        next_snapshot_only=True,
        **values,
    )


def adapt_calibration_receipt(
    payload: Mapping[str, Any] | None,
    *,
    candidate_id: str,
    source_split: str,
    raw_evidence_class: str | None = None,
) -> CalibrationReceiptV1:
    """Require caller context and class to corroborate reported evidence."""
    data = payload if isinstance(payload, Mapping) else {}
    _require_context_bindings(
        data, candidate_id=candidate_id, source_split=source_split
    )
    raw = data.get("evidence_class")
    classes = {REAL_SHADOW, REAL_MODEL_LOCAL_QUALIFICATION, INCOMPLETE}
    _require(
        raw is None or (type(raw) is str and raw in classes),
        "payload calibration evidence class is invalid",
    )
    if raw_evidence_class is not None:
        _require(
            type(raw_evidence_class) is str and raw_evidence_class in classes,
            "caller calibration evidence class is invalid",
        )
        _require(
            raw_evidence_class == raw,
            "caller calibration evidence class must match payload evidence",
        )
    raw_class = raw if raw in classes else INCOMPLETE
    vals = {name: data.get(name) for name in CalibrationReceiptV1._REQUIRED}
    missing = _missing(vals, CalibrationReceiptV1._REQUIRED)
    if data.get("heldout") is not True:
        missing = tuple(sorted(set((*missing, "heldout"))))
    # NaN/Inf and non-positive sample counts are treated as missing evidence.
    for name in ("brier", "ece"):
        if vals[name] is not None and (
            type(vals[name]) not in (int, float)
            or not math.isfinite(float(vals[name]))
            or float(vals[name]) < 0.0
            or float(vals[name]) > 1.0
        ):
            vals[name] = None
    if vals["sample_count"] is not None and (
        type(vals["sample_count"]) is not int or vals["sample_count"] <= 0
    ):
        vals["sample_count"] = None
    missing = _missing(vals, CalibrationReceiptV1._REQUIRED)
    if data.get("heldout") is not True:
        missing = tuple(sorted(set((*missing, "heldout"))))
    return CalibrationReceiptV1(
        calibration_id=str(data.get("calibration_id") or "calibration." + candidate_id),
        candidate_id=candidate_id,
        source_split=source_split,
        heldout=data.get("heldout", False),
        evidence_class=raw_class
        if not missing and data.get("heldout") is True
        else INCOMPLETE,
        raw_evidence_class=raw_class,
        status="COMPLETE" if not missing else "INCOMPLETE",
        missing_fields=missing,
        authority="DENY_ALL",
        next_snapshot_only=True,
        **vals,
    )


__all__ = [
    "CalibrationReceiptV1",
    "INCOMPLETE",
    "REAL_MODEL_LOCAL_QUALIFICATION",
    "REAL_SHADOW",
    "ReaderRuntimeReceiptError",
    "ReaderRuntimeReceiptV1",
    "SCHEMA_CALIBRATION",
    "SCHEMA_RUNTIME",
    "adapt_calibration_receipt",
    "adapt_runtime_receipt",
]
