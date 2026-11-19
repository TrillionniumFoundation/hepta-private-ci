"""Fail-closed scientific admission contract for an independent N256 provider.

This source does not implement a provider.  It records why the two existing
lanes cannot supply the independent third stream and what an eventual method
must prove before any numerical work is admitted.
"""

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


INPUT_BUNDLE_SHA256 = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
ROSTER_IDENTITY = "e289c20d6595cb6d92dd3e2585bc7cb40fb0d5a408725c5edc14a9fb7f328fe2"
CANDIDATE_SOURCE_SHA256 = "0f686be417338f7aa102a8386171798b06a63689acdd043a69e95212655bf3f9"
ORACLE_SOURCE_SHA256 = "4213f078e36cd3e296e9301df2d1788c3b9375cf7a911c73c0090fe500f5ab73"
COMPARATOR_SOURCE_SHA256 = "d20bfd4ae57e783d506a571e9a9ecb1deed836a8abbafa6e870f2879595972cf"
REFERENCE_INTERFACE_SOURCE_SHA256 = (
    "2c870cf7b530726a525f32ebee6a3efd0894ca24f7ce958238a0527d35a03783"
)
EXPECTED_DENOMINATOR = 18_225_028
EXPECTED_CAPSULES = 14
EXPECTED_LANE_CAPSULES = {"warm": 8, "coarse": 3, "cold": 3}
REQUIRED_METHOD_SHA_FIELDS = (
    "provider_source_sha256",
    "independence_review_sha256",
    "generator_reconstruction_review_sha256",
    "roster_semantics_review_sha256",
    "precision_policy_sha256",
    "tail_certificate_schema_sha256",
    "stiffness_bound_sha256",
    "cost_envelope_sha256",
    "runtime_profile_sha256",
    "host_snapshot_sha256",
    "ancestor_cgroup_snapshot_sha256",
    "allocation_sha256",
    "calendar_sha256",
)
REQUIRED_CERTIFICATIONS = (
    "certifies_nonreturning_upper",
    "certifies_delay_reset",
    "certifies_signed_l1_tail",
    "certifies_discounted_hit_and_occupation",
    "certifies_fp64_rounding",
    "certifies_all_roster_operators",
)


class AdmissionRequired(RuntimeError):
    """Raised before any independent reference-provider work may begin."""


@dataclass(frozen=True)
class KernelAssessment:
    candidate_uses_scipy_expm_multiply: bool
    oracle_uses_scipy_expm_multiply: bool
    shared_numeric_kernel: bool


def _sha256(value, name):
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return value


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _imports_expm_multiply(source, filename):
    tree = ast.parse(source, filename=filename)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "scipy.sparse.linalg":
            if any(alias.name == "expm_multiply" for alias in node.names):
                return True
    return False


def assess_frozen_numeric_kernels(candidate_source, oracle_source):
    """Determine whether the two frozen lanes share the disallowed kernel."""

    candidate = _imports_expm_multiply(candidate_source, "candidate.py")
    oracle = _imports_expm_multiply(oracle_source, "oracle.py")
    return KernelAssessment(candidate, oracle, candidate and oracle)


def validate_source_request(request):
    """Validate the current non-provider HOLD without weakening any threshold."""

    exact = {
        "schema": "hcsn-n256-reference-provider-feasibility-hold-v1",
        "input_bundle_sha256": INPUT_BUNDLE_SHA256,
        "roster_identity": ROSTER_IDENTITY,
        "candidate_source_sha256": CANDIDATE_SOURCE_SHA256,
        "oracle_source_sha256": ORACLE_SOURCE_SHA256,
        "comparator_source_sha256": COMPARATOR_SOURCE_SHA256,
        "reference_interface_source_sha256": REFERENCE_INTERFACE_SOURCE_SHA256,
        "coordinate_denominator": EXPECTED_DENOMINATOR,
        "capsules": EXPECTED_CAPSULES,
        "lane_capsules": EXPECTED_LANE_CAPSULES,
        "method_status": "NOT_SCIENTIFICALLY_ADMITTED",
        "existing_lanes_share_scipy_expm_multiply": True,
    }
    for name, expected in exact.items():
        if request.get(name) != expected:
            raise ValueError(f"{name} mismatch")
    for name in (
        "reference_provider_source_sha256",
        "reference_provider_admission_sha256",
        "numerical_idempotency_key",
    ):
        if request.get(name) is not None:
            raise ValueError(f"source HOLD must leave {name} unresolved")
    if request.get("numerical_execution_allowed") is not False:
        raise ValueError("reference-provider numerical execution must remain disabled")
    if request.get("preserved_history") != {
        "red_6295": True,
        "red_unknown_6302": True,
        "red_joint_hold_6303": True,
    }:
        raise ValueError("historical RED/UNKNOWN preservation mismatch")
    if request.get("largegrid_qualification") is not False:
        raise ValueError("method HOLD cannot qualify N256")
    if request.get("all_closed") is not False:
        raise ValueError("method HOLD cannot close the global gate")
    return request


def validate_future_method_record(record):
    """Validate evidence required before a future provider can be considered."""

    if not isinstance(record, dict):
        raise ValueError("method record must be an object")
    for name in REQUIRED_METHOD_SHA_FIELDS:
        _sha256(record.get(name), name)
    if record["provider_source_sha256"] in {
        CANDIDATE_SOURCE_SHA256,
        ORACLE_SOURCE_SHA256,
        COMPARATOR_SOURCE_SHA256,
        REFERENCE_INTERFACE_SOURCE_SHA256,
    }:
        raise ValueError("provider source is not independent")
    if record.get("method_id") != "certified_sparse_uniformization_v1":
        raise ValueError("unreviewed independent method")
    if record.get("imports_candidate_or_oracle") is not False:
        raise ValueError("provider may not import candidate or oracle")
    if record.get("uses_scipy_expm_multiply") is not False:
        raise ValueError("provider may not share scipy expm_multiply")
    if record.get("shared_numeric_kernel") is not False:
        raise ValueError("provider numeric kernel is not independent")
    for name in REQUIRED_CERTIFICATIONS:
        if record.get(name) is not True:
            raise ValueError(f"{name} is not certified")
    if record.get("coordinate_denominator") != EXPECTED_DENOMINATOR:
        raise ValueError("coordinate denominator mismatch")
    if record.get("capsules") != EXPECTED_CAPSULES:
        raise ValueError("capsule count mismatch")
    if record.get("lane_capsules") != EXPECTED_LANE_CAPSULES:
        raise ValueError("lane capsule schedule mismatch")
    return record


def require_provider_admission(request_path, admission_path):
    """Reject this source head before imports, input reads, or numerical work."""

    request = validate_source_request(json.loads(Path(request_path).read_text()))
    if (
        admission_path is None
        or request["reference_provider_source_sha256"] is None
        or request["reference_provider_admission_sha256"] is None
    ):
        raise AdmissionRequired("independent N256 reference provider remains scientifically open")
    path = Path(admission_path)
    if _digest(path) != request["reference_provider_admission_sha256"]:
        raise ValueError("reference-provider admission SHA-256 mismatch")
    validate_future_method_record(json.loads(path.read_text()))
    raise AdmissionRequired("this truthful HOLD source cannot execute a provider")
