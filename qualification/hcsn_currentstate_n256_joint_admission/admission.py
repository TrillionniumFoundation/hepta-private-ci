"""Fail-closed joint admission for all N256 numerical lanes."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class JointAdmissionRequired(RuntimeError):
    """Raised until one independently frozen joint execution envelope exists."""


@dataclass(frozen=True)
class JointAdmission:
    candidate_source_sha256: str
    oracle_source_sha256: str
    serializer_source_sha256: str
    input_bundle_sha256: str
    roster_identity: str
    resource_snapshot_source_freeze_sha256: str
    runtime_profile_sha256: str
    host_snapshot_sha256: str
    ancestor_cgroup_snapshot_sha256: str
    allocation_sha256: str
    calendar_sha256: str
    candidate_admission_sha256: str
    oracle_admission_sha256: str
    serializer_admission_sha256: str
    concurrency: int
    calendar_start_utc: str
    calendar_end_utc: str
    candidate_idempotency_key: str
    oracle_idempotency_key: str
    serializer_idempotency_key: str


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _lower_sha256(value, name):
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256")


def _utc(value, name):
    if not value.endswith("Z"):
        raise ValueError(f"{name} must be UTC")
    try:
        return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise ValueError(f"{name} must be ISO-8601 UTC") from error


def validate_record(request, admission):
    sha_fields = (
        "candidate_source_sha256",
        "oracle_source_sha256",
        "serializer_source_sha256",
        "input_bundle_sha256",
        "roster_identity",
        "resource_snapshot_source_freeze_sha256",
        "runtime_profile_sha256",
        "host_snapshot_sha256",
        "ancestor_cgroup_snapshot_sha256",
        "allocation_sha256",
        "calendar_sha256",
        "candidate_admission_sha256",
        "oracle_admission_sha256",
        "serializer_admission_sha256",
    )
    for name in sha_fields:
        _lower_sha256(getattr(admission, name), name)
    for name in (
        "candidate_source_sha256",
        "oracle_source_sha256",
        "serializer_source_sha256",
        "input_bundle_sha256",
        "roster_identity",
        "resource_snapshot_source_freeze_sha256",
    ):
        if getattr(admission, name) != request[name]:
            raise ValueError(f"{name} mismatch")
    if admission.concurrency != 1:
        raise ValueError("joint N256 admission requires concurrency one")
    if _utc(admission.calendar_start_utc, "calendar_start_utc") >= _utc(
        admission.calendar_end_utc, "calendar_end_utc"
    ):
        raise ValueError("calendar end must follow start")
    key_bindings = {
        "candidate_idempotency_key": "candidate_reserved_idempotency_key",
        "oracle_idempotency_key": "oracle_reserved_idempotency_key",
        "serializer_idempotency_key": "serializer_reserved_idempotency_key",
    }
    for admission_name, request_name in key_bindings.items():
        if getattr(admission, admission_name) != request[request_name]:
            raise ValueError(f"{admission_name} mismatch")
    return admission


def require_joint_admission(request_path, admission_path):
    request = json.loads(Path(request_path).read_text())
    if request.get("numerical_execution_allowed") is not False:
        raise ValueError("joint source intent must remain numerical HOLD")
    if request.get("execution_key") is not None:
        raise ValueError("joint source intent must not contain an execution key")
    required = request.get("required_external_freeze", {})
    if not required or any(value is not None for value in required.values()):
        raise ValueError("joint source request must leave every external freeze unresolved")
    if admission_path is None or request.get("joint_admission_sha256") is None:
        raise JointAdmissionRequired("one joint N256 numerical admission is not frozen")
    path = Path(admission_path)
    if _digest(path) != request["joint_admission_sha256"]:
        raise ValueError("joint admission SHA-256 mismatch")
    admission = JointAdmission(**json.loads(path.read_bytes()))
    return validate_record(request, admission)
