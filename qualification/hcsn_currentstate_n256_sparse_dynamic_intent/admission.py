"""Fail-closed admission for the frozen N256 sparse numerical candidate."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


class NumericalAdmissionRequired(RuntimeError):
    """Raised until an independently frozen resource allocation is available."""


@dataclass(frozen=True)
class Admission:
    source_commit: str
    source_tree_sha256: str
    input_bundle_sha256: str
    roster_identity: str
    runtime_profile_sha256: str
    host_snapshot_sha256: str
    ancestor_cgroup_snapshot_sha256: str
    allocation_sha256: str
    concurrency: int
    calendar_start_utc: str
    calendar_end_utc: str
    idempotency_key: str


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require_admission(request_path, admission_path):
    request = json.loads(Path(request_path).read_text())
    if request.get("execution_key") is not None:
        raise ValueError("source intent must not contain an execution key")
    if request.get("numerical_execution_allowed") is not False:
        raise ValueError("source intent must remain numerical HOLD")
    required = request.get("required_external_freeze", {})
    if not required or any(value is not None for value in required.values()):
        raise ValueError("source request must leave every external freeze unresolved")
    if admission_path is None:
        raise NumericalAdmissionRequired("N256 numerical admission is not frozen")
    payload = Path(admission_path)
    raw = payload.read_bytes()
    admission_sha256 = _digest(payload)
    expected = request.get("admission_sha256")
    if expected is None:
        raise NumericalAdmissionRequired(
            "no independently reviewed admission SHA-256 is bound to this source"
        )
    if admission_sha256 != expected:
        raise ValueError("admission SHA-256 mismatch")
    record = json.loads(raw)
    admission = Admission(**record)
    if admission.concurrency not in (1, 2):
        raise ValueError("bounded concurrency")
    if not admission.calendar_start_utc or not admission.calendar_end_utc:
        raise ValueError("calendar reservation")
    for name in (
        "source_commit",
        "source_tree_sha256",
        "input_bundle_sha256",
        "roster_identity",
        "runtime_profile_sha256",
        "host_snapshot_sha256",
        "ancestor_cgroup_snapshot_sha256",
        "allocation_sha256",
    ):
        value = getattr(admission, name)
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError(f"{name} must be a lowercase SHA-256")
    if admission.input_bundle_sha256 != request["input_bundle_sha256"]:
        raise ValueError("input bundle mismatch")
    if admission.roster_identity != request["roster_identity"]:
        raise ValueError("roster mismatch")
    if admission.idempotency_key != request["reserved_idempotency_key"]:
        raise ValueError("idempotency key mismatch")
    return admission
