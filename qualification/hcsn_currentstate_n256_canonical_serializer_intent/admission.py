"""Fail-closed N256 serializer admission checked before reading a state packet."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


class SerializerAdmissionRequired(RuntimeError):
    """Raised until exact serializer resources and sources are frozen."""


@dataclass(frozen=True)
class Admission:
    source_commit: str
    serializer_source_sha256: str
    candidate_source_sha256: str
    oracle_source_sha256: str
    input_bundle_sha256: str
    roster_identity: str
    host_snapshot_sha256: str
    ancestor_cgroup_snapshot_sha256: str
    allocation_sha256: str
    calendar_sha256: str
    max_packet_bytes: int
    idempotency_key: str


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sha256(value, name):
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256")


def require_admission(request_path, admission_path):
    request = json.loads(Path(request_path).read_text())
    if request["n256_serializer_execution_allowed"] is not False or request["execution_key"] is not None:
        raise ValueError("serializer source intent must remain HOLD")
    if any(value is not None for value in request["required_external_freeze"].values()):
        raise ValueError("serializer external freeze must remain unresolved")
    if admission_path is None or request["admission_sha256"] is None:
        raise SerializerAdmissionRequired("N256 serializer admission is not frozen")
    path = Path(admission_path)
    if _digest(path) != request["admission_sha256"]:
        raise ValueError("serializer admission SHA-256 mismatch")
    admission = Admission(**json.loads(path.read_bytes()))
    for name in (
        "source_commit", "serializer_source_sha256", "candidate_source_sha256",
        "oracle_source_sha256", "input_bundle_sha256", "roster_identity",
        "host_snapshot_sha256", "ancestor_cgroup_snapshot_sha256",
        "allocation_sha256", "calendar_sha256",
    ):
        _sha256(getattr(admission, name), name)
    for name in ("candidate_source_sha256", "oracle_source_sha256", "input_bundle_sha256", "roster_identity"):
        if getattr(admission, name) != request[name]:
            raise ValueError(f"{name} mismatch")
    if admission.max_packet_bytes != request["proposed_max_packet_bytes"]:
        raise ValueError("packet allocation mismatch")
    if admission.idempotency_key != request["reserved_idempotency_key"]:
        raise ValueError("idempotency key mismatch")
    return admission
