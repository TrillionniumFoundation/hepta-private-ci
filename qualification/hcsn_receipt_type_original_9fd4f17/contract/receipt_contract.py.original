"""Bind a future N256 result to its admitted execution interval.

This module validates metadata only.  It does not allocate an execution key,
invoke the provider, open result payloads, or grant scientific qualification.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from qualification.hcsn_currentstate_n256_execution_admission_bridge import (
    admission_bridge,
)


SCHEMA = "hcsn-n256-uniformization-execution-receipt-v1"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
FIELDS = {
    "schema",
    "provider_admission_sha256",
    "execution_freeze_sha256",
    "result_manifest_sha256",
    "execution_key",
    "capture_session_id",
    "host_alias",
    "execution_started_at_utc",
    "execution_completed_at_utc",
    "process_exit_code",
    "execution_complete",
    "historical_negative_and_unknown_preserved",
    "largegrid_qualification",
    "production_adoption",
    "receipt_sha256",
}


class ExecutionReceiptError(ValueError):
    """Raised before accepting an unbound or out-of-window execution receipt."""


@dataclass(frozen=True)
class ExecutionReceiptResult:
    receipt_valid: bool
    manifest_bound: bool
    execution_key_bound: bool
    host_bound: bool
    interval_bound: bool
    provider_calls: int = 0
    dynamic_calls: int = 0
    matrix_exponential_calls: int = 0
    oracle_calls: int = 0
    model_calls: int = 0
    torch_calls: int = 0
    optimizer_calls: int = 0
    training_calls: int = 0
    largegrid_qualification: bool = False
    production_adoption: bool = False


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _require_sha256(value, field):
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ExecutionReceiptError(f"missing or invalid SHA-256: {field}")


def _parse_utc(value, field):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ExecutionReceiptError(f"noncanonical UTC timestamp: {field}")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ExecutionReceiptError(f"noncanonical UTC timestamp: {field}") from error
    if parsed.tzinfo != timezone.utc or parsed.microsecond != 0:
        raise ExecutionReceiptError(f"noncanonical UTC timestamp: {field}")
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ExecutionReceiptError(f"noncanonical UTC timestamp: {field}")
    return parsed


def validate_future_execution_receipt(receipt, admission, freeze, manifest):
    """Validate one immutable receipt against the exact pre/post records."""

    if not isinstance(receipt, dict) or set(receipt) != FIELDS:
        raise ExecutionReceiptError("execution receipt field set mismatch")
    if receipt["schema"] != SCHEMA:
        raise ExecutionReceiptError("execution receipt schema mismatch")
    post = admission_bridge.validate_postexecution_bundle(admission, freeze, manifest)
    for field in (
        "provider_admission_sha256",
        "execution_freeze_sha256",
        "result_manifest_sha256",
        "receipt_sha256",
    ):
        _require_sha256(receipt[field], field)
    expected_manifest = hashlib.sha256(_canonical(manifest)).hexdigest()
    if receipt["result_manifest_sha256"] != expected_manifest:
        raise ExecutionReceiptError("result manifest is not byte-canonically bound")
    if receipt["provider_admission_sha256"] != post.preexecution.admission_sha256:
        raise ExecutionReceiptError("provider admission is not cross-bound")
    if receipt["execution_freeze_sha256"] != post.preexecution.execution_freeze_sha256:
        raise ExecutionReceiptError("execution freeze is not cross-bound")
    if receipt["execution_key"] != post.preexecution.execution_key:
        raise ExecutionReceiptError("execution key is not cross-bound")
    if receipt["capture_session_id"] != freeze["capture_session_id"]:
        raise ExecutionReceiptError("capture session is not cross-bound")
    if receipt["host_alias"] != freeze["host_alias"]:
        raise ExecutionReceiptError("host alias is not cross-bound")
    started = _parse_utc(receipt["execution_started_at_utc"], "execution_started_at_utc")
    completed = _parse_utc(
        receipt["execution_completed_at_utc"], "execution_completed_at_utc"
    )
    not_before = _parse_utc(freeze["execution_not_before_utc"], "execution_not_before_utc")
    not_after = _parse_utc(freeze["execution_not_after_utc"], "execution_not_after_utc")
    if started < not_before or completed > not_after or started > completed:
        raise ExecutionReceiptError("execution is outside the frozen interval")
    if receipt["process_exit_code"] != 0 or receipt["execution_complete"] is not True:
        raise ExecutionReceiptError("execution did not complete successfully")
    if receipt["historical_negative_and_unknown_preserved"] is not True:
        raise ExecutionReceiptError("historical negative or UNKNOWN state was erased")
    if receipt["largegrid_qualification"] is not False:
        raise ExecutionReceiptError("execution receipt cannot grant qualification")
    if receipt["production_adoption"] is not False:
        raise ExecutionReceiptError("execution receipt cannot grant production adoption")
    payload = dict(receipt)
    digest = payload.pop("receipt_sha256")
    if digest != hashlib.sha256(_canonical(payload)).hexdigest():
        raise ExecutionReceiptError("execution receipt digest mismatch")
    return ExecutionReceiptResult(
        receipt_valid=True,
        manifest_bound=True,
        execution_key_bound=True,
        host_bound=True,
        interval_bound=True,
    )
