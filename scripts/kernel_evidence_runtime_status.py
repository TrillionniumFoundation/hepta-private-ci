#!/usr/bin/env python3
"""Generate the exact tested-SHA STATUS_SOURCE artifact for kernel.evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
QUALIFICATION_KINDS = (
    "exact_source",
    "deterministic_merge",
    "metadata",
    "publication_diagnostics",
)


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


def atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=".runtime-status-"
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


def require_oid(value: str, label: str, *, optional: bool = False) -> None:
    if optional and not value:
        return
    if OID.fullmatch(value) is None:
        raise ValueError(f"{label} must be a full lowercase Git object id")


def receipt_state(path: Path | None, kind: str, source_sha: str) -> dict[str, object]:
    if path is None or not path.is_file():
        return {"present": False, "passed": False, "error": "receipt is absent"}
    try:
        value = load_json(path)
        passed = (
            value.get("schemaVersion") == 2
            and value.get("module") == "kernel.evidence"
            and value.get("receiptKind") == "candidate_qualification"
            and value.get("kind") == kind
            and value.get("sourceHeadSha") == source_sha
            and value.get("status") == "passed"
            and value.get("passed") is True
            and value.get("exitCode") == 0
            and value.get("qualificationGranted") is False
            and value.get("productionActivationGranted") is False
            and value.get("releaseGranted") is False
        )
        return {
            "present": True,
            "passed": passed,
            "sha256": sha256_file(path),
            "error": None if passed else "receipt is not exact terminal success",
        }
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {"present": True, "passed": False, "error": str(error)}


def build_status(
    *,
    source_head_sha: str,
    source_head_tree: str,
    base_sha: str,
    deterministic_merge_sha: str | None,
    github_synthetic_merge_sha: str | None,
    workflow_sha: str,
    final_merge_sha: str | None,
    workflow_run_id: str,
    workflow_run_attempt: str,
    runner_image: str,
    target_triple: str,
    checked_in_status_source: Path,
    qualification_receipts: dict[str, Path],
    crash_summary: Path | None,
) -> dict[str, object]:
    for label, value in (
        ("source head", source_head_sha),
        ("source tree", source_head_tree),
        ("base", base_sha),
        ("workflow", workflow_sha),
    ):
        require_oid(value, label)
    for label, value in (
        ("deterministic merge", deterministic_merge_sha or ""),
        ("GitHub synthetic merge", github_synthetic_merge_sha or ""),
        ("final merge", final_merge_sha or ""),
    ):
        require_oid(value, label, optional=True)
    checked_in = load_json(checked_in_status_source)
    checked_anchor = checked_in.get("asOfCommit")
    checked_tree = checked_in.get("asOfTree")
    require_oid(str(checked_anchor or ""), "checked-in status anchor")
    require_oid(str(checked_tree or ""), "checked-in status tree")

    receipts = {
        kind: receipt_state(qualification_receipts.get(kind), kind, source_head_sha)
        for kind in QUALIFICATION_KINDS
    }
    crash_state: dict[str, object]
    if crash_summary is None or not crash_summary.is_file():
        crash_state = {
            "present": False,
            "passed": False,
            "error": "crash matrix summary is absent",
        }
    else:
        try:
            crash = load_json(crash_summary)
            passed = (
                crash.get("schemaVersion") == 2
                and crash.get("module") == "kernel.evidence"
                and crash.get("receiptKind") == "crash_consistency_matrix"
                and crash.get("sourceHeadSha") == source_head_sha
                and crash.get("sourceHeadTree") == source_head_tree
                and crash.get("passed") is True
                and crash.get("scenarioCount") == crash.get("requiredScenarioCount")
                and crash.get("targetHostAcceptanceGranted") is False
                and crash.get("productionActivationGranted") is False
                and crash.get("releaseGranted") is False
            )
            crash_state = {
                "present": True,
                "passed": passed,
                "sha256": sha256_file(crash_summary),
                "error": None if passed else "crash summary is not exact terminal success",
            }
        except (OSError, ValueError, json.JSONDecodeError) as error:
            crash_state = {"present": True, "passed": False, "error": str(error)}

    exact_source = bool(receipts["exact_source"]["passed"])
    deterministic_merge = bool(receipts["deterministic_merge"]["passed"])
    metadata = bool(receipts["metadata"]["passed"])
    publication = bool(receipts["publication_diagnostics"]["passed"])
    crash_ready = bool(crash_state["passed"])
    repository_controlled_ready = (
        exact_source and deterministic_merge and metadata and publication and crash_ready
    )
    final_merge_requalified = bool(
        final_merge_sha and final_merge_sha == source_head_sha and repository_controlled_ready
    )

    return {
        "schema": "hepta.kernel-evidence-runtime-status-source.v1",
        "schemaVersion": 1,
        "module": "kernel.evidence",
        "statusClass": "exact_runtime_qualification",
        "asOfCommit": source_head_sha,
        "asOfTree": source_head_tree,
        "baseSha": base_sha,
        "deterministicMergeSha": deterministic_merge_sha,
        "githubSyntheticMergeSha": github_synthetic_merge_sha,
        "workflowSha": workflow_sha,
        "finalMergeSha": final_merge_sha,
        "workflowRunId": workflow_run_id,
        "workflowRunAttempt": workflow_run_attempt,
        "runnerImage": runner_image,
        "targetTriple": target_triple,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "checkedInImplementationStatus": {
            "path": str(checked_in_status_source),
            "sha256": sha256_file(checked_in_status_source),
            "asOfCommit": checked_anchor,
            "asOfTree": checked_tree,
            "isAncestorProvenanceOnly": True,
        },
        "qualificationReceipts": receipts,
        "crashConsistency": crash_state,
        "exactSourceQualified": exact_source,
        "mergeCandidateQualified": deterministic_merge,
        "metadataQualified": metadata,
        "publicationDiagnosticsQualified": publication,
        "crashMatrixQualified": crash_ready,
        "repositoryControlledReady": repository_controlled_ready,
        "finalMergeRequalified": final_merge_requalified,
        "authenticatedFrontierProtocolQualified": repository_controlled_ready,
        "authenticatedFrontierAuthorityAccepted": False,
        "externalFrontierActive": False,
        "independentRollbackAnchorAccepted": False,
        "independentAcceptance": False,
        "operatorActivation": False,
        "canaryAccepted": False,
        "promotionApproved": False,
        "releaseApproved": False,
        "authority": {
            "selfIssuedIndependentAcceptance": False,
            "selfIssuedExternalActivation": False,
            "selfIssuedOperatorActivation": False,
            "selfIssuedPromotion": False,
            "selfIssuedRelease": False,
        },
    }


def parse_named_paths(values: list[str]) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for value in values:
        name, separator, raw_path = value.partition("=")
        if not separator or not name or name in parsed:
            raise ValueError(f"expected one unique NAME=PATH value, got {value!r}")
        parsed[name] = Path(raw_path)
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--source-head-tree", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--deterministic-merge-sha", default="")
    parser.add_argument("--github-synthetic-merge-sha", default="")
    parser.add_argument("--workflow-sha", required=True)
    parser.add_argument("--final-merge-sha", default="")
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--workflow-run-attempt", required=True)
    parser.add_argument("--runner-image", required=True)
    parser.add_argument("--target-triple", required=True)
    parser.add_argument("--checked-in-status-source", type=Path, required=True)
    parser.add_argument("--qualification-receipt", action="append", default=[])
    parser.add_argument("--crash-summary", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        status = build_status(
            source_head_sha=args.source_head_sha,
            source_head_tree=args.source_head_tree,
            base_sha=args.base_sha,
            deterministic_merge_sha=args.deterministic_merge_sha or None,
            github_synthetic_merge_sha=args.github_synthetic_merge_sha or None,
            workflow_sha=args.workflow_sha,
            final_merge_sha=args.final_merge_sha or None,
            workflow_run_id=args.workflow_run_id,
            workflow_run_attempt=args.workflow_run_attempt,
            runner_image=args.runner_image,
            target_triple=args.target_triple,
            checked_in_status_source=args.checked_in_status_source,
            qualification_receipts=parse_named_paths(args.qualification_receipt),
            crash_summary=args.crash_summary,
        )
        atomic_json(args.output, status)
        print(json.dumps(status, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"ready": False, "error": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
