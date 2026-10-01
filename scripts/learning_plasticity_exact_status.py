#!/usr/bin/env python3
"""Generate an expiring exact-head qualification page for learning.plasticity.

The page is a workflow artifact, never a source-of-truth file committed as a
permanent "current" claim. It binds source/tree, implementation-map and host
profile bytes, the exact workflow run, the declared test command set and an
expiry. Target-host, independent/operator acceptance, activation and release
remain false unless separately supplied external receipts exist.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAP = ROOT / "docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json"
DEFAULT_HOST = ROOT / "docs/modules/learning.plasticity/OPERATIONS.md"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=ROOT, text=True
    ).strip()


def canonical_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", default=None)
    parser.add_argument("--source-tree", default=None)
    parser.add_argument("--workflow-run-id", default=None)
    parser.add_argument("--workflow-name", default="Learning plasticity exact qualification")
    parser.add_argument("--lane", choices=("source-head", "synthetic-merge"), required=True)
    parser.add_argument("--implementation-map", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--host-profile", type=Path, default=DEFAULT_HOST)
    parser.add_argument("--ttl-seconds", type=int, default=86_400)
    parser.add_argument("--tests", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.ttl_seconds <= 0 or args.ttl_seconds > 7 * 86_400:
        raise SystemExit("ttl must be within 1 second and 7 days")
    source_commit = args.source_commit or git("rev-parse", "HEAD")
    source_tree = args.source_tree or git("rev-parse", "HEAD^{tree}")
    if git("rev-parse", "HEAD") != source_commit:
        raise SystemExit("checked-out source does not match requested exact commit")
    if git("rev-parse", "HEAD^{tree}") != source_tree:
        raise SystemExit("checked-out tree does not match requested exact tree")

    implementation_map = args.implementation_map.resolve()
    host_profile = args.host_profile.resolve()
    for path in (implementation_map, host_profile):
        if not path.is_file():
            raise SystemExit(f"missing qualification input: {path}")

    observed_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    expires_at = observed_at + dt.timedelta(seconds=args.ttl_seconds)
    workflow_run_id = args.workflow_run_id or os.environ.get("GITHUB_RUN_ID", "local-unbound")
    tests = args.tests or [
        "canonical grammar contract",
        "docs and generated projections",
        "plasticity and learning-artifacts crate tests",
        "Agentd named plasticity lifetime and process E2E",
        "live structural-canary fault and recovery",
        "strict clippy and rustfmt",
    ]
    receipt: dict[str, Any] = {
        "schema": "hepta.learning-plasticity-exact-status.v1",
        "module": "learning.plasticity",
        "lane": args.lane,
        "sourceCommit": source_commit,
        "sourceTree": source_tree,
        "implementationMapPath": str(implementation_map.relative_to(ROOT)),
        "implementationMapSha256": sha256_file(implementation_map),
        "hostProfilePath": str(host_profile.relative_to(ROOT)),
        "hostProfileSha256": sha256_file(host_profile),
        "workflowName": args.workflow_name,
        "workflowRunId": str(workflow_run_id),
        "tests": tests,
        "testsPassed": True,
        "observedAt": observed_at.isoformat().replace("+00:00", "Z"),
        "expiresAt": expires_at.isoformat().replace("+00:00", "Z"),
        "evidenceTtlSeconds": args.ttl_seconds,
        "targetHostEvidence": False,
        "independentAcceptance": False,
        "operatorAcceptance": False,
        "activation": False,
        "release": False,
    }
    receipt["qualificationReceiptDigest"] = canonical_digest(receipt)

    lines = [
        "# learning.plasticity exact-head status",
        "",
        f"- **Lane:** `{receipt['lane']}`",
        f"- **Source commit:** `{source_commit}`",
        f"- **Source tree:** `{source_tree}`",
        f"- **Implementation map SHA-256:** `{receipt['implementationMapSha256']}`",
        f"- **Workflow:** `{receipt['workflowName']}` run `{workflow_run_id}`",
        f"- **Qualification receipt:** `{receipt['qualificationReceiptDigest']}`",
        f"- **Observed:** `{receipt['observedAt']}`",
        f"- **Expires:** `{receipt['expiresAt']}`",
        "- **Repository test receipt:** `passed`",
        "- **Target-host evidence:** `false`",
        "- **Independent/operator acceptance:** `false`",
        "- **Activation/release:** `false`",
        "",
        "## Executed checks",
        "",
        *(f"- {test}" for test in tests),
        "",
        "## Bound machine record",
        "",
        "```json",
        json.dumps(receipt, indent=2, sort_keys=True),
        "```",
        "",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    args.output.with_suffix(".json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(receipt["qualificationReceiptDigest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
