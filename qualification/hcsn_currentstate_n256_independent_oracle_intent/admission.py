"""Fail-closed admission for the independent N256 numerical oracle."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


class NumericalAdmissionRequired(RuntimeError):
    """Raised before any numerical dependency is imported."""


@dataclass(frozen=True)
class Admission:
    source_commit: str
    oracle_source_sha256: str
    candidate_source_sha256: str
    input_bundle_sha256: str
    roster_identity: str
    runtime_profile_sha256: str
    host_snapshot_sha256: str
    ancestor_cgroup_snapshot_sha256: str
    allocation_sha256: str
    calendar_sha256: str
    concurrency: int
    idempotency_key: str


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _lower_sha256(value, name):
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256")


def require_admission(request_path, admission_path):
    request = json.loads(Path(request_path).read_text())
    if request.get("numerical_execution_allowed") is not False:
        raise ValueError("oracle source intent must remain numerical HOLD")
    if request.get("execution_key") is not None:
        raise ValueError("oracle source intent must not contain an execution key")
    if any(value is not None for value in request["required_external_freeze"].values()):
        raise ValueError("external freeze values must remain unresolved in source intent")
    if admission_path is None or request.get("admission_sha256") is None:
        raise NumericalAdmissionRequired("independent N256 oracle numerical admission is not frozen")
    path = Path(admission_path)
    if _sha256(path) != request["admission_sha256"]:
        raise ValueError("admission SHA-256 mismatch")
    admission = Admission(**json.loads(path.read_bytes()))
    for name in (
        "source_commit", "oracle_source_sha256", "candidate_source_sha256",
        "input_bundle_sha256", "roster_identity", "runtime_profile_sha256",
        "host_snapshot_sha256", "ancestor_cgroup_snapshot_sha256",
        "allocation_sha256", "calendar_sha256",
    ):
        _lower_sha256(getattr(admission, name), name)
    if admission.concurrency != 1:
        raise ValueError("independent oracle admission requires concurrency one")
    if admission.candidate_source_sha256 != request["candidate_source_sha256"]:
        raise ValueError("candidate source mismatch")
    if admission.input_bundle_sha256 != request["input_bundle_sha256"]:
        raise ValueError("input bundle mismatch")
    if admission.roster_identity != request["roster_identity"]:
        raise ValueError("roster mismatch")
    if admission.idempotency_key != request["reserved_idempotency_key"]:
        raise ValueError("idempotency key mismatch")
    return admission
