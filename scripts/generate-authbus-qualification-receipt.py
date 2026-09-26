#!/usr/bin/env python3
"""Create and verify exact-head AuthBus qualification receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SHA_RE = re.compile(r"[0-9a-f]{40}")
SUCCESS = "success"


def parse_pair(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("expected NAME=VALUE")
    name, item = value.split("=", 1)
    if not name or not item:
        raise argparse.ArgumentTypeError("expected non-empty NAME=VALUE")
    return name, item


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_sha(name: str, value: str) -> None:
    if not SHA_RE.fullmatch(value):
        raise SystemExit(f"{name} must be a lowercase 40-character Git SHA")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--code-sha", required=True)
    parser.add_argument("--code-tree", required=True)
    parser.add_argument("--schema-digest", required=True)
    parser.add_argument("--cargo-lock-digest", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--workflow-attempt", required=True)
    parser.add_argument("--runner-os", required=True)
    parser.add_argument("--runner-arch", required=True)
    parser.add_argument("--synthetic-merge-sha")
    parser.add_argument("--gate", action="append", type=parse_pair, default=[])
    parser.add_argument("--artifact", action="append", type=parse_pair, default=[])
    args = parser.parse_args()

    for name, value in (
        ("source-sha", args.source_sha),
        ("source-tree", args.source_tree),
        ("code-sha", args.code_sha),
        ("code-tree", args.code_tree),
    ):
        validate_sha(name, value)
    if args.synthetic_merge_sha:
        validate_sha("synthetic-merge-sha", args.synthetic_merge_sha)
    for name, value in (
        ("schema-digest", args.schema_digest),
        ("cargo-lock-digest", args.cargo_lock_digest),
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise SystemExit(f"{name} must be a lowercase SHA-256 digest")

    gates = dict(args.gate)
    if not gates:
        raise SystemExit("at least one gate is required")
    invalid = {name: value for name, value in gates.items() if value != SUCCESS}
    if invalid:
        raise SystemExit(f"qualification has non-success gates: {invalid}")
    required = {
        "qualification-package",
        "owner-all-targets",
        "workspace-regression",
        "strict-clippy",
        "synthetic-merge",
        "clean-tree",
        "product-caller-execution",
        "api-inventory",
        "implementation-map",
        "observability-contract",
    }
    missing = sorted(required.difference(gates))
    if missing:
        raise SystemExit(f"qualification receipt missing required gates: {missing}")

    artifacts: dict[str, dict[str, object]] = {}
    for name, raw_path in args.artifact:
        target = Path(raw_path)
        if not target.is_file():
            raise SystemExit(f"qualification artifact is missing: {target}")
        artifacts[name] = {
            "path": str(target),
            "bytes": target.stat().st_size,
            "sha256": sha256(target),
        }

    receipt = {
        "schemaVersion": 1,
        "module": "auth.authbus",
        "result": "success",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": {
            "exactHeadSha": args.source_sha,
            "exactHeadTree": args.source_tree,
            "codeSha": args.code_sha,
            "codeTree": args.code_tree,
            "syntheticMergeSha": args.synthetic_merge_sha,
        },
        "digests": {
            "schemaSha256": args.schema_digest,
            "cargoLockSha256": args.cargo_lock_digest,
        },
        "workflow": {
            "runId": args.workflow_run_id,
            "attempt": args.workflow_attempt,
            "runnerOs": args.runner_os,
            "runnerArch": args.runner_arch,
        },
        "gates": gates,
        "artifacts": artifacts,
        "policy": {
            "skippedAccepted": False,
            "cancelledAccepted": False,
            "staticOnlyAccepted": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
