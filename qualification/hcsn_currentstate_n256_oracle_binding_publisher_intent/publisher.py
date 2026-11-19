"""Construct the exact #6375 oracle binding after authentic originals exist.

This module performs no publication or numerical work.  It returns a canonical
record only after the existing candidate admission accepts the supplied
provider admission, execution freeze, and candidate source binding.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from qualification.hcsn_currentstate_n256_independent_oracle_v2_intent import (
    admission as oracle_admission,
)


SHA256_RE = re.compile(r"[0-9a-f]{64}")


class BindingOriginalRequired(RuntimeError):
    """Raised before admission when an authentic external original is absent."""


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _record(path, name):
    if path is None:
        raise BindingOriginalRequired(f"N256 {name} is not supplied")
    try:
        value = json.loads(Path(path).read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {name}") from error
    if not isinstance(value, dict):
        raise ValueError(f"invalid {name}")
    return value


def _utc(value, name):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"noncanonical UTC timestamp: {name}")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError(f"noncanonical UTC timestamp: {name}") from error
    if result.tzinfo != timezone.utc or result.microsecond != 0:
        raise ValueError(f"noncanonical UTC timestamp: {name}")
    if result.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ValueError(f"noncanonical UTC timestamp: {name}")
    return result


def _sha_field(record, name):
    value = record.get(name)
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"invalid SHA-256: {name}")
    return value


def build_binding_record(
    *,
    created_at_utc,
    oracle_request_path,
    oracle_adapter_path,
    candidate_source_path,
    candidate_request_path,
    legacy_oracle_source_path,
    t0_builder_source_path,
    provider_admission_path,
    execution_freeze_path,
    candidate_binding_path,
):
    """Return one canonical binding record without writing or executing it."""

    external = (
        (provider_admission_path, "provider admission"),
        (execution_freeze_path, "execution freeze"),
        (candidate_binding_path, "candidate source binding"),
    )
    for path, name in external:
        if path is None:
            raise BindingOriginalRequired(f"N256 {name} is not supplied")

    request = _record(oracle_request_path, "oracle request")
    if request.get("numerical_execution_allowed") is not False:
        raise ValueError("oracle request must remain numerical HOLD")
    if request.get("execution_key") is not None:
        raise ValueError("oracle request must not contain an execution key")
    if any(value is not None for value in request["required_external_freeze"].values()):
        raise ValueError("oracle request external originals must remain unresolved")

    admitted = oracle_admission.candidate_admission.require_admission(
        candidate_request_path,
        candidate_source_path,
        provider_admission_path,
        execution_freeze_path,
        candidate_binding_path,
    )
    provider = _record(provider_admission_path, "provider admission")
    freeze = _record(execution_freeze_path, "execution freeze")
    candidate_binding = _record(candidate_binding_path, "candidate source binding")

    created = _utc(created_at_utc, "created_at_utc")
    candidate_created = _utc(candidate_binding.get("created_at_utc"), "candidate.created_at_utc")
    not_before = _utc(freeze.get("execution_not_before_utc"), "execution_not_before_utc")
    if created < candidate_created or created > not_before:
        raise ValueError("oracle binding is outside the preexecution interval")

    request_bound_sources = {
        "candidate_source_sha256": _sha(candidate_source_path),
        "candidate_admission_sha256": _sha(oracle_admission.candidate_admission.__file__),
        "legacy_oracle_source_sha256": _sha(legacy_oracle_source_path),
        "t0_builder_source_sha256": _sha(t0_builder_source_path),
    }
    for name, value in request_bound_sources.items():
        if request.get(name) != value:
            raise ValueError(f"oracle request source mismatch: {name}")
    exact_sources = {
        **request_bound_sources,
        "candidate_request_sha256": _sha(candidate_request_path),
    }

    payload = {
        "schema": oracle_admission.SCHEMA,
        "oracle_adapter_source_sha256": _sha(oracle_adapter_path),
        "oracle_admission_source_sha256": _sha(oracle_admission.__file__),
        "oracle_request_sha256": _sha(oracle_request_path),
        **exact_sources,
        "candidate_source_binding_sha256": admitted.source_binding_sha256,
        "provider_admission_sha256": admitted.provider_admission_sha256,
        "execution_freeze_sha256": admitted.execution_freeze_sha256,
        "execution_key": admitted.execution_key,
        "input_bundle_sha256": request["input_bundle_sha256"],
        "phase_original_sha256": request["phase_original_sha256"],
        "state_original_sha256": request["state_original_sha256"],
        "npz_b64_original_sha256": request["npz_b64_original_sha256"],
        "external_reviewer_identity_sha256": _sha_field(
            provider, "external_reviewer_identity_sha256"
        ),
        "external_reviewer_custody_sha256": _sha_field(
            provider, "external_reviewer_custody_sha256"
        ),
        "external_review_artifact_sha256": _sha_field(
            provider, "external_review_artifact_sha256"
        ),
        "created_at_utc": created_at_utc,
        "historical_negative_and_unknown_preserved": True,
        "largegrid_qualification": False,
        "production_adoption": False,
    }
    if set(payload) != oracle_admission.FIELDS - {"binding_sha256"}:
        raise ValueError("constructed oracle binding field set mismatch")
    result = dict(payload)
    result["binding_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
    return result
