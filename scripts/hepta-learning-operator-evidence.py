#!/usr/bin/env python3
"""Create a source-bound qualification gate receipt from an executed stage."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE = importlib.import_module("hepta-learning-operator-stage")


def require_sha(value: str, label: str) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError(f"{label} must be a literal SHA-1 identity")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--status-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()

    require_sha(args.source_sha, "source SHA")
    require_sha(args.source_tree, "source tree")
    if not args.target.strip():
        raise ValueError("gate compiler target is absent")
    log = ROOT / args.log
    status_path = ROOT / args.status_file
    if not log.is_file():
        raise ValueError(f"gate log is absent: {args.log}")
    if not status_path.is_file():
        raise ValueError(f"stage status is absent: {args.status_file}")
    stage = json.loads(status_path.read_text(encoding="utf-8"))
    STAGE.verify_value(stage, stage.get("stage"))
    identity = stage["executionIdentity"]
    if (
        identity["sourceSha"] != args.source_sha
        or identity["sourceTree"] != args.source_tree
    ):
        raise ValueError("gate source differs from executed stage")
    if stage["log"] is None or stage["log"]["path"] != args.log:
        raise ValueError("gate log differs from executed stage")
    stage_status = stage.get("status")
    if stage_status not in {"passed", "failed", "not_run"}:
        raise ValueError(f"invalid stage status: {stage_status}")
    gate_status = {"passed": "pass", "failed": "fail", "not_run": "not_run"}[
        stage_status
    ]
    raw = log.read_bytes()
    receipt = {
        "schema": "hepta.learning-operator-qualification-gate.v2",
        "schemaVersion": 2,
        "module": "learning.operator",
        "gate": args.name,
        "sourceSha": args.source_sha,
        "sourceTree": args.source_tree,
        "command": stage["command"],
        "commandSha256": stage["commandSha256"],
        "gatePurpose": args.command,
        "executionIdentity": identity,
        "target": args.target,
        "status": gate_status,
        "stageStatus": stage_status,
        "stageReceipt": {
            "path": args.status_file,
            "sha256": hashlib.sha256(status_path.read_bytes()).hexdigest(),
        },
        "log": {
            "path": args.log,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "lines": raw.count(b"\n"),
        },
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
