"""Validate one atomic future execution freeze without collecting evidence.

This source is intentionally non-numerical.  It neither selects a host nor
creates any of the originals that the admission contract requires.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone


SCHEMA = "hcsn-n256-uniformization-execution-freeze-v1"
PARENT_REQUEST_SHA256 = (
    "029402a1ac56d47c28939671ed083b1fec1780b4c60d3db4621a20fbd4a1eb13"
)
PROVIDER_SOURCE_SHA256 = (
    "602dcedd5827a35fbee81b51687a8e8bc3f4038f519a308eef3e884d088e2be2"
)
SHA256_RE = re.compile(r"[0-9a-f]{64}")
TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}")
RESOURCE_NAMES = (
    "runtime_profile",
    "host_snapshot",
    "ancestor_cgroup_snapshot",
    "allocation",
    "calendar",
)
EXTERNAL_NAMES = (
    "provider_author_identity_sha256",
    "external_reviewer_identity_sha256",
    "external_reviewer_custody_sha256",
    "external_review_artifact_sha256",
)


class ExecutionFreezeError(ValueError):
    """Raised before an incomplete or mixed-lineage freeze can be admitted."""


@dataclass(frozen=True)
class ExecutionFreezeResult:
    complete: bool
    resource_original_count: int
    external_original_count: int
    execution_key_bound: bool
    historical_negative_and_unknown_preserved: bool
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


def _require_hash(value, field):
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ExecutionFreezeError(f"missing or invalid SHA-256: {field}")


def _require_token(value, field):
    if not isinstance(value, str) or TOKEN_RE.fullmatch(value) is None:
        raise ExecutionFreezeError(f"missing or noncanonical token: {field}")


def _parse_utc(value, field):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ExecutionFreezeError(f"noncanonical UTC timestamp: {field}")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ExecutionFreezeError(
            f"noncanonical UTC timestamp: {field}"
        ) from error
    if parsed.tzinfo != timezone.utc or parsed.microsecond != 0:
        raise ExecutionFreezeError(f"noncanonical UTC timestamp: {field}")
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ExecutionFreezeError(f"noncanonical UTC timestamp: {field}")
    return parsed


def _top_level_fields():
    return {
        "schema",
        "parent_roster_resolved_request_sha256",
        "provider_source_sha256",
        "capture_session_id",
        "host_alias",
        "resource_originals",
        *EXTERNAL_NAMES,
        "execution_request_sha256",
        "execution_key",
        "execution_not_before_utc",
        "execution_not_after_utc",
        "external_reviewer_independence_certified",
        "historical_negative_and_unknown_preserved",
        "largegrid_qualification",
        "production_adoption",
        "freeze_sha256",
    }


def validate_future_execution_freeze(record):
    """Validate identities and time coverage for one future atomic freeze."""

    if not isinstance(record, dict) or set(record) != _top_level_fields():
        raise ExecutionFreezeError("execution freeze field set mismatch")
    if record["schema"] != SCHEMA:
        raise ExecutionFreezeError("execution freeze schema mismatch")
    if record["parent_roster_resolved_request_sha256"] != PARENT_REQUEST_SHA256:
        raise ExecutionFreezeError("roster-resolved parent identity mismatch")
    if record["provider_source_sha256"] != PROVIDER_SOURCE_SHA256:
        raise ExecutionFreezeError("provider source identity mismatch")
    _require_token(record["capture_session_id"], "capture_session_id")
    _require_token(record["host_alias"], "host_alias")
    _require_token(record["execution_key"], "execution_key")
    resources = record["resource_originals"]
    if not isinstance(resources, dict) or set(resources) != set(RESOURCE_NAMES):
        raise ExecutionFreezeError("resource original set mismatch")
    capture_times = []
    for name in RESOURCE_NAMES:
        original = resources[name]
        if not isinstance(original, dict) or set(original) != {
            "sha256",
            "capture_session_id",
            "host_alias",
            "captured_at_utc",
        }:
            raise ExecutionFreezeError(f"resource original field set mismatch: {name}")
        _require_hash(original["sha256"], f"resource_originals.{name}.sha256")
        if original["capture_session_id"] != record["capture_session_id"]:
            raise ExecutionFreezeError("resource originals span capture sessions")
        if original["host_alias"] != record["host_alias"]:
            raise ExecutionFreezeError("resource originals span host aliases")
        capture_times.append(
            _parse_utc(
                original["captured_at_utc"],
                f"resource_originals.{name}.captured_at_utc",
            )
        )
    for field in EXTERNAL_NAMES:
        _require_hash(record[field], field)
    _require_hash(record["execution_request_sha256"], "execution_request_sha256")
    if record["provider_author_identity_sha256"] == record[
        "external_reviewer_identity_sha256"
    ]:
        raise ExecutionFreezeError("provider author and external reviewer are not separated")
    if record["external_reviewer_identity_sha256"] == record[
        "external_reviewer_custody_sha256"
    ]:
        raise ExecutionFreezeError("external reviewer identity and custody are conflated")
    start = _parse_utc(record["execution_not_before_utc"], "execution_not_before_utc")
    end = _parse_utc(record["execution_not_after_utc"], "execution_not_after_utc")
    if start >= end:
        raise ExecutionFreezeError("execution interval is empty or reversed")
    if any(captured > start for captured in capture_times):
        raise ExecutionFreezeError("resource original was captured after execution admission")
    if record["external_reviewer_independence_certified"] is not True:
        raise ExecutionFreezeError("external reviewer independence is not certified")
    if record["historical_negative_and_unknown_preserved"] is not True:
        raise ExecutionFreezeError("historical negative or UNKNOWN state was not preserved")
    if record["largegrid_qualification"] is not False:
        raise ExecutionFreezeError("execution freeze cannot grant large-grid qualification")
    if record["production_adoption"] is not False:
        raise ExecutionFreezeError("execution freeze cannot grant production adoption")
    payload = dict(record)
    digest = payload.pop("freeze_sha256")
    _require_hash(digest, "freeze_sha256")
    if digest != hashlib.sha256(_canonical(payload)).hexdigest():
        raise ExecutionFreezeError("execution freeze digest mismatch")
    return ExecutionFreezeResult(
        complete=True,
        resource_original_count=len(RESOURCE_NAMES),
        external_original_count=len(EXTERNAL_NAMES),
        execution_key_bound=True,
        historical_negative_and_unknown_preserved=True,
    )


def require_current_hold(request):
    """Reject any attempt to call the protocol itself an execution freeze."""

    required_null = {
        "runtime_profile_sha256",
        "host_snapshot_sha256",
        "ancestor_cgroup_snapshot_sha256",
        "allocation_sha256",
        "calendar_sha256",
        *EXTERNAL_NAMES,
        "execution_request_sha256",
    }
    evidence = request.get("future_originals")
    if not isinstance(evidence, dict) or set(evidence) != required_null:
        raise ExecutionFreezeError("current HOLD future-original field set mismatch")
    if any(value is not None for value in evidence.values()):
        raise ExecutionFreezeError("current HOLD silently populated a future original")
    for field in (
        "capture_session_id",
        "host_alias",
        "execution_key",
        "execution_not_before_utc",
        "execution_not_after_utc",
        "future_freeze_sha256",
    ):
        if request.get(field) is not None:
            raise ExecutionFreezeError(f"current HOLD silently populated {field}")
    required_false = (
        "external_reviewer_independence_certified",
        "resource_bundle_admitted",
        "provider_admitted",
        "numerical_execution_allowed",
        "largegrid_qualification",
        "production_adoption",
        "all_closed",
    )
    if any(request.get(field) is not False for field in required_false):
        raise ExecutionFreezeError("current request does not preserve HOLD")
    if request.get("historical_negative_and_unknown_preserved") is not True:
        raise ExecutionFreezeError("current request erases negative or UNKNOWN state")
    return True
