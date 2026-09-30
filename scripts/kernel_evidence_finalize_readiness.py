#!/usr/bin/env python3
"""Finalize kernel.evidence readiness after retained-receipt byte auditing.

The preliminary manifest and runtime status are deliberately generated before
this step.  This postprocessor binds the independent receipt-audit object, forces
all aggregate readiness claims false on any audit or identity failure, updates
the runtime status atomically, and then emits the only final readiness manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=".readiness-final-"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def audit_identity_errors(manifest: dict[str, Any], audit: dict[str, Any]) -> list[str]:
    identity = audit.get("identity")
    if not isinstance(identity, dict):
        return ["receipt audit identity is absent"]
    pairs = (
        ("sourceHeadSha", "source_head_sha"),
        ("sourceHeadTree", "source_head_tree"),
        ("baseSha", "base_sha"),
        ("deterministicMergeSha", "deterministic_merge_sha"),
        ("githubSyntheticMergeSha", "github_synthetic_merge_sha"),
        ("workflowSha", "workflow_sha"),
        ("finalMergeSha", "final_merge_sha"),
        ("workflowRunId", "workflow_run_id"),
        ("workflowRunAttempt", "workflow_run_attempt"),
        ("runnerImage", "runner_image"),
        ("targetTriple", "target_triple"),
    )
    errors: list[str] = []
    for audit_key, manifest_key in pairs:
        if identity.get(audit_key) != manifest.get(manifest_key):
            errors.append(
                f"receipt audit {audit_key} does not match manifest {manifest_key}"
            )
    return errors


def runtime_identity_errors(manifest: dict[str, Any], runtime: dict[str, Any]) -> list[str]:
    pairs = (
        ("asOfCommit", "source_head_sha"),
        ("asOfTree", "source_head_tree"),
        ("baseSha", "base_sha"),
        ("deterministicMergeSha", "deterministic_merge_sha"),
        ("githubSyntheticMergeSha", "github_synthetic_merge_sha"),
        ("workflowSha", "workflow_sha"),
        ("finalMergeSha", "final_merge_sha"),
        ("workflowRunId", "workflow_run_id"),
        ("workflowRunAttempt", "workflow_run_attempt"),
        ("runnerImage", "runner_image"),
        ("targetTriple", "target_triple"),
    )
    errors: list[str] = []
    for runtime_key, manifest_key in pairs:
        if runtime.get(runtime_key) != manifest.get(manifest_key):
            errors.append(
                f"runtime status {runtime_key} does not match manifest {manifest_key}"
            )
    return errors


def finalize(
    preliminary_manifest_path: Path,
    runtime_status_path: Path,
    receipt_audit_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    manifest = load_json(preliminary_manifest_path)
    runtime = load_json(runtime_status_path)
    audit = load_json(receipt_audit_path)

    errors: list[str] = []
    if audit.get("schemaVersion") != 1:
        errors.append("receipt audit schema version is unsupported")
    if audit.get("module") != "kernel.evidence":
        errors.append("receipt audit module is incorrect")
    if audit.get("receiptKind") != "readiness_receipt_audit":
        errors.append("receipt audit kind is incorrect")
    if audit.get("passed") is not True:
        errors.append("receipt audit did not reach terminal success")
    audit_errors = audit.get("errors")
    if not isinstance(audit_errors, list):
        errors.append("receipt audit errors field is invalid")
    elif audit_errors:
        errors.append("receipt audit retained one or more validation errors")
    errors.extend(audit_identity_errors(manifest, audit))
    errors.extend(runtime_identity_errors(manifest, runtime))

    audit_sha = sha256_file(receipt_audit_path)
    audit_qualified = not errors

    runtime["receiptAuditQualified"] = audit_qualified
    runtime["receiptAuditSha256"] = audit_sha
    runtime["receiptAuditPath"] = str(receipt_audit_path)
    runtime["receiptAuditErrors"] = errors
    if not audit_qualified:
        runtime["repositoryControlledReady"] = False
        runtime["authenticatedFrontierProtocolQualified"] = False
        runtime["finalMergeRequalified"] = False
    # Never broaden external authority while finalizing repository evidence.
    for key in (
        "authenticatedFrontierAuthorityAccepted",
        "externalFrontierActive",
        "independentRollbackAnchorAccepted",
        "independentAcceptance",
        "operatorActivation",
        "canaryAccepted",
        "promotionApproved",
        "releaseApproved",
    ):
        runtime[key] = False
    atomic_json(runtime_status_path, runtime)
    runtime_sha = sha256_file(runtime_status_path)

    readiness = manifest.setdefault("readiness", {})
    readiness["receipt_audit_qualified"] = audit_qualified
    for key in (
        "repository_controlled_ready",
        "local_integrity_ready",
        "authenticated_frontier_protocol_ready",
        "final_merge_requalified",
    ):
        readiness[key] = bool(readiness.get(key) is True and audit_qualified)
    for key in (
        "authenticated_frontier_authority_ready",
        "external_rollback_anchor_ready",
        "independent_acceptance",
        "operator_activation",
        "production_activation",
        "promotion_approved",
        "release_approved",
    ):
        readiness[key] = False

    blockers = manifest.get("blockers")
    if not isinstance(blockers, list):
        blockers = []
    blockers = [item for item in blockers if item != "receipt_audit"]
    if not audit_qualified:
        blockers.append("receipt_audit")
    manifest["blockers"] = list(dict.fromkeys(blockers))

    manifest["receipt_audit"] = {
        "present": True,
        "passed": audit_qualified,
        "sha256": audit_sha,
        "path": str(receipt_audit_path),
        "errors": errors,
        "reportedErrors": audit_errors if isinstance(audit_errors, list) else [],
    }

    status_identity = manifest.setdefault("status_identity", {})
    runtime_identity = status_identity.setdefault("runtime", {})
    current_runtime_identity_errors = runtime_identity_errors(manifest, runtime)
    runtime_identity.update(
        {
            "present": True,
            "exact": not current_runtime_identity_errors,
            "sha256": runtime_sha,
            "asOfCommit": runtime.get("asOfCommit"),
            "asOfTree": runtime.get("asOfTree"),
            "receiptAuditQualified": audit_qualified,
            "error": None
            if not current_runtime_identity_errors
            else "runtime STATUS_SOURCE is not bound to the exact tested object",
        }
    )

    artifacts = manifest.setdefault("artifact_hashes", {})
    for name, path in (
        ("receipt_audit", receipt_audit_path),
        ("runtime_status", runtime_status_path),
    ):
        artifacts[name] = {
            "path": str(path),
            "present": True,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }

    authority = manifest.setdefault("authority", {})
    for key in (
        "self_issued_independent_acceptance",
        "self_issued_external_activation",
        "self_issued_operator_activation",
        "self_issued_promotion",
        "self_issued_release_approval",
    ):
        authority[key] = False

    atomic_json(output_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preliminary-manifest", type=Path, required=True)
    parser.add_argument("--runtime-status", type=Path, required=True)
    parser.add_argument("--receipt-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = finalize(
            args.preliminary_manifest,
            args.runtime_status,
            args.receipt_audit,
            args.output,
        )
        print(json.dumps(manifest, sort_keys=True))
        # The caller performs the final policy gate. Returning zero here keeps
        # the fail-closed manifest available even when the audit rejected it.
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"ready": False, "error": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
