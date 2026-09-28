#!/usr/bin/env python3
"""Generate an external-artifact exact-head status page for learning.plasticity.

The generated page is intentionally not a source-selection authority. It binds one
observed source/tree and optional deterministic merge candidate to command receipts,
workflow identity, module-map and host-profile digests, and an explicit evidence
validity window. It is suitable for upload as a read-only CI artifact.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import subprocess
import sys
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_FILES = {
    "implementationMap": ROOT / "docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json",
    "currentState": ROOT / "docs/modules/learning.plasticity/CURRENT_STATE.json",
    "technicalGuide": ROOT / "docs/modules/learning.plasticity/TECHNICAL.md",
    "operationsProfile": ROOT / "docs/modules/learning.plasticity/OPERATIONS.md",
    "developerQuickstart": ROOT / "docs/modules/learning.plasticity/DEVELOPER_QUICKSTART.md",
    "grammarContractCheck": ROOT / "scripts/learning_plasticity_contract_check.py",
}
REQUIRED_WORKFLOWS = [
    "CI required",
    "Architecture required",
    "Hepta Agentd process qualification",
    "Hepta Lane F shadow qualification",
    "Hepta consolidated source qualification (read-only)",
    "v8-canary",
]


class StatusError(RuntimeError):
    pass


def run_git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise StatusError(f"git {' '.join(args)} failed: {exc}") from exc


def sha256_file(path: pathlib.Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise StatusError(f"cannot hash {path}: {exc}") from exc


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def parse_utc(value: str | None) -> dt.datetime:
    if value is None:
        return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise StatusError("observed-at must include a timezone")
    return parsed.astimezone(dt.timezone.utc).replace(microsecond=0)


def iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def parse_receipts(paths: list[pathlib.Path]) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for path in paths:
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise StatusError(f"cannot read receipt {path}: {exc}") from exc
        decision: str | None = None
        try:
            decoded = json.loads(payload)
            if isinstance(decoded, dict):
                raw = decoded.get("decision") or decoded.get("conclusion")
                if isinstance(raw, str):
                    decision = raw
        except json.JSONDecodeError:
            pass
        receipts.append(
            {
                "path": str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "decision": decision,
            }
        )
    return receipts


def build_status(args: argparse.Namespace) -> dict[str, Any]:
    source_commit = args.source_commit or run_git("rev-parse", "HEAD")
    source_tree = args.source_tree or run_git("rev-parse", f"{source_commit}^{{tree}}")
    base_commit = args.base_commit
    base_tree = args.base_tree
    if base_commit and not base_tree:
        base_tree = run_git("rev-parse", f"{base_commit}^{{tree}}")

    observed = parse_utc(args.observed_at)
    valid_until = observed + dt.timedelta(seconds=args.evidence_ttl_seconds)
    file_digests = {name: sha256_file(path) for name, path in DEFAULT_FILES.items()}
    receipts = parse_receipts(args.test_receipt)
    receipt_set_digest = hashlib.sha256(canonical_json(receipts)).hexdigest()
    workflow_run_id = args.workflow_run_id or os.environ.get("GITHUB_RUN_ID")
    workflow_run_attempt = args.workflow_run_attempt or os.environ.get("GITHUB_RUN_ATTEMPT")
    workflow_name = args.workflow_name or os.environ.get("GITHUB_WORKFLOW")
    repository = args.repository or os.environ.get("GITHUB_REPOSITORY")

    evidence_complete = bool(
        workflow_run_id
        and workflow_name
        and receipts
        and all(receipt.get("decision") in {"passed", "success"} for receipt in receipts)
    )
    return {
        "schema": "hepta.learning-plasticity-exact-head-status.v1",
        "repository": repository,
        "source": {
            "commit": source_commit,
            "tree": source_tree,
            "baseCommit": base_commit,
            "baseTree": base_tree,
            "syntheticMergeCommit": args.merge_commit,
            "syntheticMergeTree": args.merge_tree,
        },
        "module": "learning.plasticity",
        "lane": "LANE-F-ADAPTIVE-POLICY",
        "workflow": {
            "name": workflow_name,
            "runId": workflow_run_id,
            "runAttempt": workflow_run_attempt,
            "serverUrl": os.environ.get("GITHUB_SERVER_URL"),
            "requiredWorkflowNames": REQUIRED_WORKFLOWS,
        },
        "fileDigests": file_digests,
        "testReceipts": receipts,
        "testReceiptSetDigest": receipt_set_digest,
        "hostProfileDigest": file_digests["operationsProfile"],
        "implementationMapDigest": file_digests["implementationMap"],
        "observedAt": iso(observed),
        "evidenceTtlSeconds": args.evidence_ttl_seconds,
        "evidenceValidUntil": iso(valid_until),
        "evidenceCompleteForThisWorkflow": evidence_complete,
        "claimBoundary": {
            "sourceExecutionReceiptOnly": True,
            "productExecutionProved": False,
            "independentAcceptance": False,
            "targetHostQualified": False,
            "activation": False,
            "promotion": False,
            "release": False,
        },
    }


def markdown(status: dict[str, Any]) -> str:
    source = status["source"]
    workflow = status["workflow"]
    claims = status["claimBoundary"]
    rows = [
        ("Source commit", source["commit"]),
        ("Source tree", source["tree"]),
        ("Base commit", source.get("baseCommit")),
        ("Base tree", source.get("baseTree")),
        ("Synthetic merge commit", source.get("syntheticMergeCommit")),
        ("Synthetic merge tree", source.get("syntheticMergeTree")),
        ("Implementation map SHA-256", status["implementationMapDigest"]),
        ("Host profile SHA-256", status["hostProfileDigest"]),
        ("Test receipt set SHA-256", status["testReceiptSetDigest"]),
        ("Workflow", workflow.get("name")),
        ("Workflow run ID", workflow.get("runId")),
        ("Workflow run attempt", workflow.get("runAttempt")),
        ("Observed at", status["observedAt"]),
        ("Evidence valid until", status["evidenceValidUntil"]),
    ]
    lines = [
        "# learning.plasticity exact-head status",
        "",
        "This page is generated from one CI execution. It is not a cached source-selection,",
        "deployment, activation, promotion, or release authority.",
        "",
        "| Fact | Value |",
        "| --- | --- |",
    ]
    for key, value in rows:
        lines.append(f"| {key} | `{value}` |" if value else f"| {key} | _not supplied_ |")
    lines.extend(["", "## Test receipts", ""])
    if status["testReceipts"]:
        lines.extend(["| Path | Decision | SHA-256 | Bytes |", "| --- | --- | --- | ---: |"]) 
        for receipt in status["testReceipts"]:
            lines.append(
                f"| `{receipt['path']}` | `{receipt.get('decision')}` | "
                f"`{receipt['sha256']}` | {receipt['bytes']} |"
            )
    else:
        lines.append("No command receipt was supplied; execution completeness is false.")
    lines.extend(["", "## Required workflow names", ""])
    lines.extend(f"- `{name}`" for name in workflow["requiredWorkflowNames"])
    lines.extend(["", "## Claim boundary", ""])
    for name, value in claims.items():
        lines.append(f"- `{name}`: `{str(value).lower()}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    parser.add_argument("--source-commit")
    parser.add_argument("--source-tree")
    parser.add_argument("--base-commit")
    parser.add_argument("--base-tree")
    parser.add_argument("--merge-commit")
    parser.add_argument("--merge-tree")
    parser.add_argument("--repository")
    parser.add_argument("--workflow-name")
    parser.add_argument("--workflow-run-id")
    parser.add_argument("--workflow-run-attempt")
    parser.add_argument("--observed-at")
    parser.add_argument("--evidence-ttl-seconds", type=int, default=604_800)
    parser.add_argument("--test-receipt", type=pathlib.Path, action="append", default=[])
    args = parser.parse_args()
    if not 1 <= args.evidence_ttl_seconds <= 2_592_000:
        print("evidence TTL must be within 1..2592000 seconds", file=sys.stderr)
        return 2
    try:
        status = build_status(args)
    except StatusError as exc:
        print(f"exact-head status generation failed: {exc}", file=sys.stderr)
        return 1
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "learning-plasticity-exact-head.json").write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output_dir / "learning-plasticity-exact-head.md").write_text(
        markdown(status), encoding="utf-8"
    )
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
