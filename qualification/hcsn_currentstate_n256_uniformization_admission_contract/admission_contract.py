"""Bind future provider admission to resources and independent custody.

This module does not create evidence and does not admit the provider.  It only
defines the exact field set that a later immutable admission must satisfy.  In
particular, source-level implementation separation is not accepted as external
reviewer independence.
"""

import hashlib
import json
import re
from dataclasses import dataclass


ADMISSION_SCHEMA = "hcsn-n256-uniformization-provider-admission-v2"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
PARENT_IDENTITY_FIELDS = (
    "provider_source_sha256",
    "provider_request_sha256",
    "precision_policy_source_sha256",
    "precision_policy_request_sha256",
    "implementation_review_source_sha256",
    "implementation_review_request_sha256",
)
RESOURCE_FIELDS = (
    "runtime_profile_sha256",
    "host_snapshot_sha256",
    "ancestor_cgroup_snapshot_sha256",
    "allocation_sha256",
    "calendar_sha256",
)
OPERATOR_FIELDS = (
    "operator_roster_sha256",
    "segment_roster_sha256",
)
EXTERNAL_REVIEW_FIELDS = (
    "provider_author_identity_sha256",
    "external_reviewer_identity_sha256",
    "external_reviewer_custody_sha256",
    "external_review_artifact_sha256",
)
HASH_FIELDS = (
    *PARENT_IDENTITY_FIELDS,
    *RESOURCE_FIELDS,
    *OPERATOR_FIELDS,
    *EXTERNAL_REVIEW_FIELDS,
    "execution_request_sha256",
)


class AdmissionContractError(ValueError):
    """Raised before accepting incomplete or self-contradictory admission."""


@dataclass(frozen=True)
class AdmissionContractResult:
    admitted: bool
    required_hash_count: int
    implementation_independence_passed: bool
    external_reviewer_independence_certified: bool
    historical_negative_and_unknown_preserved: bool
    execution_key_bound: bool
    n256_provider_calls: int = 0
    candidate_calls: int = 0
    oracle_calls: int = 0
    model_calls: int = 0
    optimizer_calls: int = 0
    largegrid_qualification: bool = False
    production_adoption: bool = False


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _require_sha256(value, field):
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise AdmissionContractError(f"missing or invalid SHA-256: {field}")


def _required_fields():
    return {
        "schema",
        *HASH_FIELDS,
        "execution_key",
        "created_at_utc",
        "implementation_independence_passed",
        "external_reviewer_independence_certified",
        "historical_negative_and_unknown_preserved",
        "admitted",
        "largegrid_qualification",
        "production_adoption",
        "admission_sha256",
    }


def validate_future_admission(record, expected_parent_identities):
    """Validate one later immutable admission without creating evidence.

    ``expected_parent_identities`` must contain the six exact parent identities.
    Resource, roster, reviewer, custody, future execution-request, and execution
    key values are supplied only by the future admission artifact.
    """

    if not isinstance(record, dict) or set(record) != _required_fields():
        raise AdmissionContractError("provider admission field set mismatch")
    if set(expected_parent_identities) != set(PARENT_IDENTITY_FIELDS):
        raise AdmissionContractError("expected parent identity field set mismatch")
    if record["schema"] != ADMISSION_SCHEMA:
        raise AdmissionContractError("provider admission schema mismatch")
    for field in HASH_FIELDS:
        _require_sha256(record[field], field)
    for field in PARENT_IDENTITY_FIELDS:
        if record[field] != expected_parent_identities[field]:
            raise AdmissionContractError("provider admission parent identity mismatch")
    if record["provider_author_identity_sha256"] == record[
        "external_reviewer_identity_sha256"
    ]:
        raise AdmissionContractError("provider author and external reviewer are not separated")
    if record["external_reviewer_identity_sha256"] == record[
        "external_reviewer_custody_sha256"
    ]:
        raise AdmissionContractError("external reviewer identity and custody are conflated")
    execution_key = record["execution_key"]
    if (
        not isinstance(execution_key, str)
        or not execution_key
        or len(execution_key.encode()) > 192
        or any(character.isspace() for character in execution_key)
    ):
        raise AdmissionContractError("execution key is absent or noncanonical")
    created_at = record["created_at_utc"]
    if (
        not isinstance(created_at, str)
        or len(created_at) != 20
        or not created_at.endswith("Z")
        or created_at[10] != "T"
    ):
        raise AdmissionContractError("admission timestamp is noncanonical")
    required_true = (
        "implementation_independence_passed",
        "external_reviewer_independence_certified",
        "historical_negative_and_unknown_preserved",
        "admitted",
    )
    if not all(record[field] is True for field in required_true):
        raise AdmissionContractError("provider admission truth gates are incomplete")
    if record["largegrid_qualification"] is not False:
        raise AdmissionContractError("provider admission cannot grant large-grid qualification")
    if record["production_adoption"] is not False:
        raise AdmissionContractError("provider admission cannot grant production adoption")
    payload = dict(record)
    digest = payload.pop("admission_sha256")
    _require_sha256(digest, "admission_sha256")
    if digest != hashlib.sha256(_canonical(payload)).hexdigest():
        raise AdmissionContractError("provider admission digest mismatch")
    return AdmissionContractResult(
        admitted=True,
        required_hash_count=len(HASH_FIELDS),
        implementation_independence_passed=True,
        external_reviewer_independence_certified=True,
        historical_negative_and_unknown_preserved=True,
        execution_key_bound=True,
    )


def require_current_hold(request):
    """Confirm that the current request cannot be mistaken for admission."""

    if request.get("provider_admitted") is not False:
        raise AdmissionContractError("current request does not preserve provider HOLD")
    if request.get("numerical_execution_allowed") is not False:
        raise AdmissionContractError("current request unexpectedly allows numerical execution")
    if request.get("execution_key") is not None:
        raise AdmissionContractError("current request unexpectedly allocates an execution key")
    evidence = request.get("missing_external_evidence")
    required_missing = {
        *RESOURCE_FIELDS,
        *OPERATOR_FIELDS,
        *EXTERNAL_REVIEW_FIELDS,
    }
    if not isinstance(evidence, dict) or set(evidence) != required_missing:
        raise AdmissionContractError("current missing-evidence field set mismatch")
    if any(value is not None for value in evidence.values()):
        raise AdmissionContractError("current missing evidence was silently populated")
    if request.get("external_reviewer_independence_certified") is not False:
        raise AdmissionContractError("current request invents external reviewer independence")
    return True
