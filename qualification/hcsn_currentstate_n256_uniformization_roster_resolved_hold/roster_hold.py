"""Bind the exact N256 structural rosters while preserving provider HOLD.

This module does not admit the provider or execute numerical work.  It accepts
only the two exact roster identities published by the preceding structural
stage and requires every other external/resource field to remain absent.
"""

import re


SHA256_RE = re.compile(r"[0-9a-f]{64}")
SCHEMA = "hcsn-n256-uniformization-roster-resolved-hold-v1"
OPERATOR_ROSTER_SHA256 = (
    "b4f1916f021df7c8d4b0cc8f25e09511a427c49c21e45d1432d7d918cb6f8b20"
)
SEGMENT_ROSTER_SHA256 = (
    "e619e001e04bb0dcc64cb1be78cc9773381241ac8d8a4171d3d4f1b7041eace9"
)
ROSTER_FIELDS = {"operator_roster_sha256", "segment_roster_sha256"}
REMAINING_FIELDS = {
    "allocation_sha256",
    "ancestor_cgroup_snapshot_sha256",
    "calendar_sha256",
    "external_review_artifact_sha256",
    "external_reviewer_custody_sha256",
    "external_reviewer_identity_sha256",
    "host_snapshot_sha256",
    "provider_author_identity_sha256",
    "runtime_profile_sha256",
}
ALL_EVIDENCE_FIELDS = ROSTER_FIELDS | REMAINING_FIELDS


class RosterHoldError(ValueError):
    """Raised before a roster-resolved HOLD can be misread as admission."""


def _require_sha256(value, field):
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise RosterHoldError(f"missing or invalid SHA-256: {field}")


def _require_parent_hold(parent):
    evidence = parent.get("missing_external_evidence")
    if not isinstance(evidence, dict) or set(evidence) != ALL_EVIDENCE_FIELDS:
        raise RosterHoldError("parent missing-evidence field set mismatch")
    if any(value is not None for value in evidence.values()):
        raise RosterHoldError("parent admission request was rewritten")
    if (
        parent.get("provider_admitted") is not False
        or parent.get("numerical_execution_allowed") is not False
        or parent.get("execution_key") is not None
        or parent.get("external_reviewer_independence_certified") is not False
    ):
        raise RosterHoldError("parent admission request does not preserve HOLD")


def _require_roster_original(roster):
    if roster.get("operator_roster_sha256") != OPERATOR_ROSTER_SHA256:
        raise RosterHoldError("operator roster identity mismatch")
    if roster.get("segment_roster_sha256") != SEGMENT_ROSTER_SHA256:
        raise RosterHoldError("segment roster identity mismatch")
    if (
        roster.get("provider_admitted") is not False
        or roster.get("numerical_execution_allowed") is not False
        or roster.get("execution_key") is not None
        or roster.get("all_closed") is not False
    ):
        raise RosterHoldError("roster original does not preserve HOLD")


def validate_roster_resolved_hold(record, parent, roster):
    """Validate a child record that resolves exactly two evidence identities."""

    _require_parent_hold(parent)
    _require_roster_original(roster)
    if record.get("schema") != SCHEMA:
        raise RosterHoldError("roster-resolved HOLD schema mismatch")
    evidence = record.get("evidence_state")
    if not isinstance(evidence, dict) or set(evidence) != ALL_EVIDENCE_FIELDS:
        raise RosterHoldError("roster-resolved evidence field set mismatch")
    if evidence["operator_roster_sha256"] != OPERATOR_ROSTER_SHA256:
        raise RosterHoldError("resolved operator roster identity mismatch")
    if evidence["segment_roster_sha256"] != SEGMENT_ROSTER_SHA256:
        raise RosterHoldError("resolved segment roster identity mismatch")
    if any(evidence[field] is not None for field in REMAINING_FIELDS):
        raise RosterHoldError("unbacked external/resource evidence was populated")
    if record.get("remaining_missing_external_evidence") != sorted(REMAINING_FIELDS):
        raise RosterHoldError("remaining missing-evidence roster mismatch")
    for field in (
        "parent_admission_request_sha256",
        "roster_request_sha256",
        "operator_roster_file_sha256",
        "segment_roster_file_sha256",
    ):
        _require_sha256(record.get(field), field)
    if (
        record.get("provider_admitted") is not False
        or record.get("numerical_execution_allowed") is not False
        or record.get("external_reviewer_independence_certified") is not False
        or record.get("execution_key") is not None
        or record.get("largegrid_qualification") is not False
        or record.get("production_adoption") is not False
        or record.get("all_closed") is not False
        or record.get("status") != "HOLD"
    ):
        raise RosterHoldError("roster-resolved record does not preserve HOLD")
    counts = record.get("work_counts")
    if not isinstance(counts, dict) or set(counts) != {
        "dynamic_calls",
        "matrix_exponential_calls",
        "model_calls",
        "optimizer_calls",
        "oracle_calls",
        "provider_calls",
        "torch_calls",
        "training_calls",
    }:
        raise RosterHoldError("zero-work counter field set mismatch")
    if any(value != 0 for value in counts.values()):
        raise RosterHoldError("roster resolution executed prohibited work")
    return True
