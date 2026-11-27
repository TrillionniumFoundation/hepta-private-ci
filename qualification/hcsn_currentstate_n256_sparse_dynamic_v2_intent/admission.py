"""Fail-closed v3 admission bridge for the N256 sparse candidate."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from qualification.hcsn_currentstate_n256_execution_admission_bridge import (
    admission_bridge,
)


BINDING_SCHEMA = "hcsn-n256-signedcontent-source-execution-binding-v1"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
BINDING_FIELDS = {
    "schema",
    "candidate_source_sha256",
    "candidate_admission_sha256",
    "candidate_request_sha256",
    "provider_admission_sha256",
    "execution_freeze_sha256",
    "execution_key",
    "input_bundle_sha256",
    "roster_identity",
    "operator_roster_sha256",
    "segment_roster_sha256",
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
    """Raised until the exact external preexecution bundle is available."""


@dataclass(frozen=True)
class AdmittedSource:
    execution_key: str
    provider_admission_sha256: str
    execution_freeze_sha256: str
    source_binding_sha256: str


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _require_sha256(value, field):
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"missing or invalid SHA-256: {field}")


def _parse_utc(value, field):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"noncanonical UTC timestamp: {field}")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError(f"noncanonical UTC timestamp: {field}") from error
    if parsed.tzinfo != timezone.utc or parsed.microsecond != 0:
        raise ValueError(f"noncanonical UTC timestamp: {field}")
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ValueError(f"noncanonical UTC timestamp: {field}")
    return parsed


def _load_record(path, name):
    if path is None:
        raise NumericalAdmissionRequired(f"N256 {name} is not frozen")
    try:
        record = json.loads(Path(path).read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {name}") from error
    if not isinstance(record, dict):
        raise ValueError(f"invalid {name}")
    return record


def require_admission(request_path, source_path, admission_path, freeze_path, binding_path):
    """Validate the current source plus #6357 preexecution records before imports."""

    request = json.loads(Path(request_path).read_text())
    if request.get("execution_key") is not None:
        raise ValueError("source intent must not contain an execution key")
    if request.get("numerical_execution_allowed") is not False:
        raise ValueError("source intent must remain numerical HOLD")
    required = request.get("required_external_freeze", {})
    if not required or any(value is not None for value in required.values()):
        raise ValueError("source request must leave every external freeze unresolved")
    if admission_path is None or freeze_path is None or binding_path is None:
        raise NumericalAdmissionRequired("complete N256 preexecution bundle is not frozen")

    admission = _load_record(admission_path, "provider admission")
    freeze = _load_record(freeze_path, "execution freeze")
    binding = _load_record(binding_path, "source binding")
    pre = admission_bridge.validate_preexecution_bundle(admission, freeze)

    if set(binding) != BINDING_FIELDS or binding.get("schema") != BINDING_SCHEMA:
        raise ValueError("source binding field set or schema mismatch")
    for field in (
        "candidate_source_sha256",
        "candidate_admission_sha256",
        "candidate_request_sha256",
        "provider_admission_sha256",
        "execution_freeze_sha256",
        "input_bundle_sha256",
        "roster_identity",
        "operator_roster_sha256",
        "segment_roster_sha256",
        "external_reviewer_identity_sha256",
        "external_reviewer_custody_sha256",
        "external_review_artifact_sha256",
        "binding_sha256",
    ):
        _require_sha256(binding[field], field)
    if binding["candidate_source_sha256"] != _digest(source_path):
        raise ValueError("candidate source is not byte-bound")
    if binding["candidate_admission_sha256"] != _digest(__file__):
        raise ValueError("candidate admission bridge is not byte-bound")
    if binding["candidate_request_sha256"] != _digest(request_path):
        raise ValueError("candidate request is not byte-bound")
    expected = {
        "provider_admission_sha256": pre.admission_sha256,
        "execution_freeze_sha256": pre.execution_freeze_sha256,
        "execution_key": pre.execution_key,
        "input_bundle_sha256": request["input_bundle_sha256"],
        "roster_identity": request["roster_identity"],
        "operator_roster_sha256": admission["operator_roster_sha256"],
        "segment_roster_sha256": admission["segment_roster_sha256"],
        "external_reviewer_identity_sha256": admission[
            "external_reviewer_identity_sha256"
        ],
        "external_reviewer_custody_sha256": admission[
            "external_reviewer_custody_sha256"
        ],
        "external_review_artifact_sha256": admission[
            "external_review_artifact_sha256"
        ],
    }
    for field, value in expected.items():
        if binding[field] != value:
            raise ValueError(f"source binding mismatch: {field}")
    created = _parse_utc(binding["created_at_utc"], "created_at_utc")
    admitted = _parse_utc(admission["created_at_utc"], "admission.created_at_utc")
    not_before = _parse_utc(freeze["execution_not_before_utc"], "execution_not_before_utc")
    if created < admitted or created > not_before:
        raise ValueError("source binding is outside the admitted preexecution interval")
    if binding["historical_negative_and_unknown_preserved"] is not True:
        raise ValueError("historical negative or UNKNOWN state was erased")
    if binding["largegrid_qualification"] is not False:
        raise ValueError("source binding cannot grant qualification")
    if binding["production_adoption"] is not False:
        raise ValueError("source binding cannot adopt production")
    payload = dict(binding)
    digest = payload.pop("binding_sha256")
    if digest != hashlib.sha256(_canonical(payload)).hexdigest():
        raise ValueError("source binding digest mismatch")
    return AdmittedSource(
        execution_key=pre.execution_key,
        provider_admission_sha256=pre.admission_sha256,
        execution_freeze_sha256=pre.execution_freeze_sha256,
        source_binding_sha256=digest,
    )
