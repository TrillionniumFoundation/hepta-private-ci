#!/usr/bin/env python3
"""Generate an ephemeral exact-head learning.plasticity evidence page.

The output belongs in a CI artifact, never in the canonical source tree. It binds
one tested commit/tree to retained command receipts, the implementation map, the
host operating profile, the workflow run and a finite evidence-validity window.
It deliberately leaves target-host execution, independent acceptance, activation
and release false unless a separate external authority issues those receipts.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_digest(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("receipt timestamp is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def load_receipts(directory: Path, tested_sha: str) -> list[dict]:
    receipts = []
    for path in sorted(directory.glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("status") != "passed" or row.get("exit_code") != 0:
            raise ValueError(f"non-passing command receipt: {path.name}")
        if row.get("tested_sha") != tested_sha:
            raise ValueError(f"tested SHA mismatch in {path.name}")
        before = row.get("before", {})
        after = row.get("after", {})
        if before != after or before.get("commit") != tested_sha or before.get("dirty"):
            raise ValueError(f"source identity drift in {path.name}")
        receipts.append(
            {
                "file": path.name,
                "command": row.get("command", []),
                "lane": row.get("lane"),
                "startedAt": row.get("started_at"),
                "finishedAt": row.get("finished_at"),
                "elapsedSeconds": row.get("elapsed_seconds"),
                "observedPassedTests": row.get("observed_passed_tests", 0),
                "observedFailedTests": row.get("observed_failed_tests", 0),
                "logSha256": row.get("log_sha256"),
                "receiptSha256": digest_file(path),
            }
        )
    if not receipts:
        raise ValueError("at least one passing command receipt is required")
    return receipts


def workflow_url() -> str | None:
    server = os.environ.get("GITHUB_SERVER_URL")
    repository = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if server and repository and run_id:
        return f"{server}/{repository}/actions/runs/{run_id}"
    return None


def render_markdown(status: dict) -> str:
    command_rows = []
    for receipt in status["commandReceipts"]:
        command = " ".join(receipt["command"])
        command_rows.append(
            f"| `{receipt['file']}` | `{command}` | {receipt['observedPassedTests']} | "
            f"`{receipt['receiptSha256']}` |"
        )
    workflow_rows = []
    observed = status["workflow"]
    for name in status["requiredWorkflows"]:
        state = "this exact run" if name == observed["name"] else "required; externally observed"
        workflow_rows.append(f"| {name} | {state} |")
    claims = status["claimBoundary"]
    return "\n".join(
        [
            "# learning.plasticity exact-head evidence",
            "",
            "> Generated as a CI artifact. This page is not source-selection, deployment, activation, promotion, or release authority.",
            "",
            "## Frozen identity",
            "",
            f"- Source SHA: `{status['sourceSha']}`",
            f"- Tested SHA: `{status['testedSha']}`",
            f"- Tested tree: `{status['testedTree']}`",
            f"- Lane: `{status['lane']}`",
            f"- Observed: `{status['observedAt']}`",
            f"- Evidence valid until: `{status['validUntil']}`",
            f"- Evidence digest: `{status['evidenceDigest']}`",
            "",
            "## Bound source evidence",
            "",
            f"- Implementation map SHA-256: `{status['implementationMapSha256']}`",
            f"- Host profile SHA-256: `{status['hostProfileSha256']}`",
            f"- Workflow run: `{observed.get('url') or 'local/no URL'}`",
            "",
            "## Command receipts",
            "",
            "| Receipt | Command | Passing tests observed | Receipt SHA-256 |",
            "| --- | --- | ---: | --- |",
            *command_rows,
            "",
            "## Required workflow surface",
            "",
            "| Workflow | Evidence state |",
            "| --- | --- |",
            *workflow_rows,
            "",
            "## Claim boundary",
            "",
            f"- Exact source command execution: `{str(claims['exactSourceExecution']).lower()}`",
            f"- Product execution proved: `{str(claims['productExecutionProved']).lower()}`",
            f"- Target-host rollback domains proved: `{str(claims['targetHostRollbackDomainsProved']).lower()}`",
            f"- Independent acceptance: `{str(claims['independentAcceptance']).lower()}`",
            f"- Activation: `{str(claims['activation']).lower()}`",
            f"- Release: `{str(claims['release']).lower()}`",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--tested-sha", required=True)
    parser.add_argument("--receipt-dir", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    parser.add_argument("--valid-hours", type=int, default=168)
    args = parser.parse_args()

    for value, label in ((args.source_sha, "source"), (args.tested_sha, "tested")):
        if re.fullmatch(r"[0-9a-f]{40}", value) is None:
            raise ValueError(f"invalid {label} SHA")
    if args.valid_hours <= 0 or args.valid_hours > 24 * 30:
        raise ValueError("evidence validity must be within one hour and 30 days")
    actual = git("rev-parse", "HEAD")
    if actual != args.tested_sha or git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("checkout is not the clean tested SHA")

    receipts = load_receipts(args.receipt_dir, args.tested_sha)
    finished = [parse_time(receipt["finishedAt"]) for receipt in receipts]
    observed_at = max(finished)
    valid_until = observed_at + timedelta(hours=args.valid_hours)
    tested_tree = git("rev-parse", "HEAD^{tree}")
    implementation_map = ROOT / "docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json"
    host_profile = ROOT / "docs/modules/learning.plasticity/OPERATIONS.md"
    workflow = {
        "name": os.environ.get("GITHUB_WORKFLOW", "local"),
        "runId": os.environ.get("GITHUB_RUN_ID"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "job": os.environ.get("GITHUB_JOB"),
        "url": workflow_url(),
    }
    status = {
        "schema": "hepta.learning-plasticity-exact-head-evidence.v1",
        "sourceSha": args.source_sha,
        "testedSha": args.tested_sha,
        "testedTree": tested_tree,
        "lane": args.lane,
        "observedAt": observed_at.isoformat(),
        "validUntil": valid_until.isoformat(),
        "implementationMapSha256": digest_file(implementation_map),
        "hostProfileSha256": digest_file(host_profile),
        "workflow": workflow,
        "requiredWorkflows": [
            "CI required",
            "Architecture required",
            "Hepta Lane F shadow qualification",
            "Hepta Agentd process qualification",
            "v8-canary",
        ],
        "commandReceipts": receipts,
        "claimBoundary": {
            "exactSourceExecution": args.source_sha == args.tested_sha,
            "productExecutionProved": False,
            "targetHostRollbackDomainsProved": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        },
    }
    status["evidenceDigest"] = canonical_digest(status)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.output_md.write_text(render_markdown(status), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
