"""Fail-closed cross-binding for the signed-content independent oracle v2."""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from qualification.hcsn_currentstate_n256_sparse_dynamic_v2_intent import (
    admission as candidate_admission,
)


SCHEMA = "hcsn-n256-independent-oracle-signedcontent-binding-v2"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
FIELDS = {
    "schema",
    "oracle_adapter_source_sha256",
    "oracle_admission_source_sha256",
    "oracle_request_sha256",
    "legacy_oracle_source_sha256",
    "candidate_source_sha256",
    "candidate_admission_sha256",
    "candidate_request_sha256",
    "candidate_source_binding_sha256",
    "provider_admission_sha256",
    "execution_freeze_sha256",
    "execution_key",
    "input_bundle_sha256",
    "phase_original_sha256",
    "state_original_sha256",
    "npz_b64_original_sha256",
    "t0_builder_source_sha256",
    "external_reviewer_identity_sha256",
    "external_reviewer_custody_sha256",
    "external_review_artifact_sha256",
    "created_at_utc",
    "historical_negative_and_unknown_preserved",
    "largegrid_qualification",
    "production_adoption",
    "binding_sha256",
}


class NumericalAdmissionRequired(RuntimeError):
    """Raised before any numerical dependency or propagation is allowed."""


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _utc(value, field):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"noncanonical UTC timestamp: {field}")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError(f"noncanonical UTC timestamp: {field}") from error
    if result.tzinfo != timezone.utc or result.microsecond != 0:
        raise ValueError(f"noncanonical UTC timestamp: {field}")
    if result.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ValueError(f"noncanonical UTC timestamp: {field}")
    return result


def _record(path, name):
    if path is None:
        raise NumericalAdmissionRequired(f"N256 {name} is not frozen")
    try:
        value = json.loads(Path(path).read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {name}") from error
    if not isinstance(value, dict):
        raise ValueError(f"invalid {name}")
    return value


def require_admission(
    request_path,
    adapter_path,
    candidate_source_path,
    candidate_request_path,
    legacy_oracle_source_path,
    t0_builder_source_path,
    provider_admission_path,
    execution_freeze_path,
    candidate_binding_path,
    oracle_binding_path,
):
    """Bind the oracle adapter to the exact admitted candidate before numerics."""

    request = json.loads(Path(request_path).read_text())
    if request.get("numerical_execution_allowed") is not False:
        raise ValueError("oracle v2 source intent must remain numerical HOLD")
    if request.get("execution_key") is not None:
        raise ValueError("oracle v2 source intent must not contain an execution key")
    if any(value is not None for value in request["required_external_freeze"].values()):
        raise ValueError("oracle v2 source intent must retain unresolved originals")
    if oracle_binding_path is None:
        raise NumericalAdmissionRequired("independent oracle v2 binding is not frozen")

    admitted = candidate_admission.require_admission(
        candidate_request_path,
        candidate_source_path,
        provider_admission_path,
        execution_freeze_path,
        candidate_binding_path,
    )
    provider = _record(provider_admission_path, "provider admission")
    freeze = _record(execution_freeze_path, "execution freeze")
    candidate_binding = _record(candidate_binding_path, "candidate source binding")
    binding = _record(oracle_binding_path, "oracle source binding")
    if set(binding) != FIELDS or binding.get("schema") != SCHEMA:
        raise ValueError("oracle source binding field set or schema")
    for field in FIELDS - {
        "schema",
        "execution_key",
        "created_at_utc",
        "historical_negative_and_unknown_preserved",
        "largegrid_qualification",
        "production_adoption",
    }:
        if not isinstance(binding[field], str) or SHA256_RE.fullmatch(binding[field]) is None:
            raise ValueError(f"missing or invalid SHA-256: {field}")
    expected = {
        "oracle_adapter_source_sha256": _sha(adapter_path),
        "oracle_admission_source_sha256": _sha(__file__),
        "oracle_request_sha256": _sha(request_path),
        "legacy_oracle_source_sha256": _sha(legacy_oracle_source_path),
        "candidate_source_sha256": _sha(candidate_source_path),
        "candidate_admission_sha256": _sha(candidate_admission.__file__),
        "candidate_request_sha256": _sha(candidate_request_path),
        "candidate_source_binding_sha256": admitted.source_binding_sha256,
        "provider_admission_sha256": admitted.provider_admission_sha256,
        "execution_freeze_sha256": admitted.execution_freeze_sha256,
        "execution_key": admitted.execution_key,
        "input_bundle_sha256": request["input_bundle_sha256"],
        "phase_original_sha256": request["phase_original_sha256"],
        "state_original_sha256": request["state_original_sha256"],
        "npz_b64_original_sha256": request["npz_b64_original_sha256"],
        "t0_builder_source_sha256": _sha(t0_builder_source_path),
        "external_reviewer_identity_sha256": provider["external_reviewer_identity_sha256"],
        "external_reviewer_custody_sha256": provider["external_reviewer_custody_sha256"],
        "external_review_artifact_sha256": provider["external_review_artifact_sha256"],
    }
    for field, value in expected.items():
        if binding[field] != value:
            raise ValueError(f"oracle source binding mismatch: {field}")
    if request["candidate_source_sha256"] != expected["candidate_source_sha256"]:
        raise ValueError("oracle request candidate source mismatch")
    if request["candidate_admission_sha256"] != expected["candidate_admission_sha256"]:
        raise ValueError("oracle request candidate admission mismatch")
    if request["legacy_oracle_source_sha256"] != expected["legacy_oracle_source_sha256"]:
        raise ValueError("oracle request legacy oracle mismatch")
    if request["t0_builder_source_sha256"] != expected["t0_builder_source_sha256"]:
        raise ValueError("oracle request t0 builder mismatch")
    created = _utc(binding["created_at_utc"], "created_at_utc")
    candidate_created = _utc(candidate_binding["created_at_utc"], "candidate.created_at_utc")
    not_before = _utc(freeze["execution_not_before_utc"], "execution_not_before_utc")
    if created < candidate_created or created > not_before:
        raise ValueError("oracle binding is outside the preexecution interval")
    if binding["historical_negative_and_unknown_preserved"] is not True:
        raise ValueError("historical negative or UNKNOWN state was erased")
    if binding["largegrid_qualification"] is not False:
        raise ValueError("oracle binding cannot grant qualification")
    if binding["production_adoption"] is not False:
        raise ValueError("oracle binding cannot adopt production")
    payload = dict(binding)
    digest = payload.pop("binding_sha256")
    if digest != hashlib.sha256(_canonical(payload)).hexdigest():
        raise ValueError("oracle source binding digest mismatch")
    return admitted
