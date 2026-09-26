#!/usr/bin/env python3
"""Generate a non-authoritative exact-head learning.plasticity status artifact.

The artifact is generated at execution time and binds source/tree plus the current
implementation map and host profile. It is deliberately not a selection, deployment,
activation, promotion or release receipt.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REQUIRED_WORKFLOWS = (
    "CI required",
    "Architecture required",
    "learning.plasticity exact head",
    "Hepta Lane F shadow qualification",
)


def git(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_status(arguments: argparse.Namespace) -> dict[str, Any]:
    observed_at = datetime.now(timezone.utc)
    expires_at = observed_at + timedelta(seconds=arguments.evidence_ttl_seconds)
    implementation_map = ROOT / "docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json"
    host_profile = ROOT / "docs/modules/learning.plasticity/OPERATIONS.md"
    source_sha = git("rev-parse", "HEAD")
    source_tree = git("rev-parse", "HEAD^{tree}")
    dirty = bool(git("status", "--porcelain"))
    required_workflows = arguments.required_workflow or list(DEFAULT_REQUIRED_WORKFLOWS)
    workflow_receipts = arguments.workflow_receipt or []
    test_receipts = arguments.test_receipt or []
    return {
        "schema": "hepta.learning-plasticity-exact-head-status.v1",
        "source": {
            "commit": source_sha,
            "tree": source_tree,
            "clean": not dirty,
        },
        "bindings": {
            "implementationMapPath": str(implementation_map.relative_to(ROOT)),
            "implementationMapDigest": sha256_file(implementation_map),
            "hostProfilePath": str(host_profile.relative_to(ROOT)),
            "hostProfileDigest": sha256_file(host_profile),
        },
        "qualification": {
            "requiredWorkflows": required_workflows,
            "workflowReceipts": workflow_receipts,
            "testReceipts": test_receipts,
            "allRequiredReceiptsPresent": len(workflow_receipts) >= len(required_workflows)
            and bool(test_receipts),
        },
        "claimBoundary": {
            "sourceOnly": True,
            "targetHostExecutionProved": False,
            "physicalRollbackDomainIndependenceProved": False,
            "independentAcceptance": False,
            "activation": False,
            "promotion": False,
            "release": False,
        },
        "evidenceWindow": {
            "observedAt": observed_at.isoformat().replace("+00:00", "Z"),
            "ttlSeconds": arguments.evidence_ttl_seconds,
            "expiresAt": expires_at.isoformat().replace("+00:00", "Z"),
        },
        "generator": {
            "githubRunId": os.environ.get("GITHUB_RUN_ID"),
            "githubRunAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "githubJob": os.environ.get("GITHUB_JOB"),
        },
    }


def markdown(status: dict[str, Any]) -> str:
    source = status["source"]
    bindings = status["bindings"]
    qualification = status["qualification"]
    boundary = status["claimBoundary"]
    evidence = status["evidenceWindow"]
    lines = [
        "# learning.plasticity exact-head status",
        "",
        "> Generated execution artifact. It grants no activation, promotion, release or deployment authority.",
        "",
        "## Candidate identity",
        "",
        f"- Source SHA: `{source['commit']}`",
        f"- Source tree: `{source['tree']}`",
        f"- Clean checkout: `{str(source['clean']).lower()}`",
        f"- Implementation map digest: `{bindings['implementationMapDigest']}`",
        f"- Host profile digest: `{bindings['hostProfileDigest']}`",
        "",
        "## Required workflows",
        "",
    ]
    lines.extend(f"- `{name}`" for name in qualification["requiredWorkflows"])
    lines.extend(["", "## Observed workflow receipts", ""])
    if qualification["workflowReceipts"]:
        lines.extend(f"- `{receipt}`" for receipt in qualification["workflowReceipts"])
    else:
        lines.append("- None supplied")
    lines.extend(["", "## Test receipts", ""])
    if qualification["testReceipts"]:
        lines.extend(f"- `{receipt}`" for receipt in qualification["testReceipts"])
    else:
        lines.append("- None supplied")
    lines.extend(
        [
            "",
            "## Claim boundary",
            "",
            f"- All required receipts present: `{str(qualification['allRequiredReceiptsPresent']).lower()}`",
            f"- Target-host execution proved: `{str(boundary['targetHostExecutionProved']).lower()}`",
            f"- Physical rollback-domain independence proved: `{str(boundary['physicalRollbackDomainIndependenceProved']).lower()}`",
            f"- Independent acceptance: `{str(boundary['independentAcceptance']).lower()}`",
            f"- Activation: `{str(boundary['activation']).lower()}`",
            f"- Promotion: `{str(boundary['promotion']).lower()}`",
            f"- Release: `{str(boundary['release']).lower()}`",
            "",
            "## Evidence window",
            "",
            f"- Observed at: `{evidence['observedAt']}`",
            f"- Expires at: `{evidence['expiresAt']}`",
            f"- TTL seconds: `{evidence['ttlSeconds']}`",
            "",
            "## Machine-readable payload",
            "",
            "```json",
            json.dumps(status, indent=2, sort_keys=True),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--evidence-ttl-seconds", type=int, default=86_400)
    parser.add_argument("--required-workflow", action="append")
    parser.add_argument("--workflow-receipt", action="append")
    parser.add_argument("--test-receipt", action="append")
    arguments = parser.parse_args()
    if arguments.evidence_ttl_seconds <= 0:
        parser.error("--evidence-ttl-seconds must be positive")
    return arguments


def main() -> int:
    arguments = parse_arguments()
    status = build_status(arguments)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    if arguments.output.suffix == ".json":
        content = json.dumps(status, indent=2, sort_keys=True) + "\n"
    else:
        content = markdown(status)
    arguments.output.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
