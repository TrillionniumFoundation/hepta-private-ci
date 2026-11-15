"""Fail-closed source contract for a future N256 joint numerical run.

This module is stdlib-only.  It does not import, open, or invoke any candidate,
oracle, serializer, dynamic, matrix-exponential, Torch, or optimizer surface.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


INPUT_BUNDLE_SHA256 = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
ROSTER_IDENTITY = "e289c20d6595cb6d92dd3e2585bc7cb40fb0d5a408725c5edc14a9fb7f328fe2"
CANDIDATE_SOURCE_SHA256 = "0f686be417338f7aa102a8386171798b06a63689acdd043a69e95212655bf3f9"
ORACLE_SOURCE_SHA256 = "4213f078e36cd3e296e9301df2d1788c3b9375cf7a911c73c0090fe500f5ab73"
SERIALIZER_SOURCE_SHA256 = "3107fb296043de8f3e3c78e13aa940aea38aa64c16dfe68d342d2adb0c7aa97a"
RESOURCE_SOURCE_FREEZE_SHA256 = "f58815dc902d9129a99a91770ce644af2e3b56b00a8d0bd02440b3d7055467e9"
EXPECTED_DENOMINATOR = 18_225_028
EXPECTED_CAPSULES = 14
EXPECTED_LANE_CAPSULES = {"warm": 8, "coarse": 3, "cold": 3}
BYTE_PAIR_NAMES = (
    "warm_saved_state_roundtrip",
    "coarse_saved_state_roundtrip",
    "cold_saved_state_roundtrip",
)
REQUIRED_EXTERNAL_FREEZE = (
    "runtime_profile_sha256",
    "host_snapshot_sha256",
    "ancestor_cgroup_snapshot_sha256",
    "allocation_sha256",
    "calendar_sha256",
    "candidate_admission_sha256",
    "oracle_admission_sha256",
    "serializer_admission_sha256",
    "joint_admission_sha256",
)


class AdmissionRequired(RuntimeError):
    """Raised before any future N256 stream may be opened."""


@dataclass(frozen=True)
class FrozenAdmission:
    runtime_profile_sha256: str
    host_snapshot_sha256: str
    ancestor_cgroup_snapshot_sha256: str
    allocation_sha256: str
    calendar_sha256: str
    candidate_admission_sha256: str
    oracle_admission_sha256: str
    serializer_admission_sha256: str
    joint_admission_sha256: str
    concurrency: int
    lane: str


def _is_sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_source_request(request):
    """Validate that the checked-in request remains an execution-denying intent."""

    exact = {
        "input_bundle_sha256": INPUT_BUNDLE_SHA256,
        "roster_identity": ROSTER_IDENTITY,
        "candidate_source_sha256": CANDIDATE_SOURCE_SHA256,
        "oracle_source_sha256": ORACLE_SOURCE_SHA256,
        "serializer_source_sha256": SERIALIZER_SOURCE_SHA256,
        "resource_snapshot_source_freeze_sha256": RESOURCE_SOURCE_FREEZE_SHA256,
        "coordinate_denominator": EXPECTED_DENOMINATOR,
        "capsules": EXPECTED_CAPSULES,
        "lane_capsules": EXPECTED_LANE_CAPSULES,
        "byte_pair_names": list(BYTE_PAIR_NAMES),
    }
    for name, expected in exact.items():
        if request.get(name) != expected:
            raise ValueError(f"{name} mismatch")
    if request.get("numerical_execution_allowed") is not False:
        raise ValueError("N256 numerical execution must remain disabled")
    if request.get("numerical_idempotency_key") is not None:
        raise ValueError("source intent must not allocate a numerical idempotency key")
    if request.get("admission_sha256") is not None:
        raise ValueError("source intent must not freeze an execution admission")
    external = request.get("required_external_freeze")
    if not isinstance(external, dict) or set(external) != set(REQUIRED_EXTERNAL_FREEZE):
        raise ValueError("external freeze schema mismatch")
    if any(external[name] is not None for name in REQUIRED_EXTERNAL_FREEZE):
        raise ValueError("source intent must leave every external freeze unresolved")
    preserved = request.get("preserved_history", {})
    if preserved != {
        "red_6295": True,
        "red_unknown_6302": True,
        "red_joint_hold_6303": True,
    }:
        raise ValueError("historical RED/UNKNOWN preservation mismatch")
    if request.get("largegrid_qualification") is not False:
        raise ValueError("source intent cannot grant large-grid qualification")
    if request.get("all_closed") is not False:
        raise ValueError("source intent cannot close the global gate")
    return request


def require_execution_admission(request_path, admission_path):
    """Reject before opening candidate/oracle/serializer streams on this source head."""

    request = validate_source_request(json.loads(Path(request_path).read_text()))
    if admission_path is None or request["admission_sha256"] is None:
        raise AdmissionRequired("N256 joint comparator admission is not frozen")
    path = Path(admission_path)
    if _digest(path) != request["admission_sha256"]:
        raise ValueError("admission SHA-256 mismatch")
    record = json.loads(path.read_text())
    admission = FrozenAdmission(**record)
    for name in REQUIRED_EXTERNAL_FREEZE:
        if not _is_sha256(getattr(admission, name)):
            raise ValueError(f"{name} must be a lowercase SHA-256")
        if request["required_external_freeze"][name] != getattr(admission, name):
            raise ValueError(f"{name} mismatch")
    if admission.concurrency != 1:
        raise ValueError("N256 numerical lanes require concurrency one")
    if admission.lane != "joint-candidate-oracle-serializer-comparator":
        raise ValueError("joint lane mismatch")
    return admission
