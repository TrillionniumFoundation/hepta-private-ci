#!/usr/bin/env python3
"""Create a source-bound qualification gate receipt from an executed log."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    parser.add_argument("--output", required=True)
    parser.add_argument("--target", default="")
    args = parser.parse_args()

    require_sha(args.source_sha, "source SHA")
    require_sha(args.source_tree, "source tree")
    log = ROOT / args.log
    if not log.is_file():
        raise ValueError(f"gate log is absent: {args.log}")
    raw = log.read_bytes()
    receipt = {
        "schema": "hepta.learning-operator-qualification-gate.v1",
        "schemaVersion": 1,
        "module": "learning.operator",
        "gate": args.name,
        "sourceSha": args.source_sha,
        "sourceTree": args.source_tree,
        "command": args.command,
        "commandSha256": hashlib.sha256(args.command.encode("utf-8")).hexdigest(),
        "target": args.target,
        "status": "pass",
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
