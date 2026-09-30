#!/usr/bin/env python3
"""Create and verify explicit passed/failed/not_run qualification stages."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALID = {"passed", "failed", "not_run"}


def sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def record(args: argparse.Namespace) -> None:
    if args.status not in VALID:
        raise ValueError(f"invalid stage status: {args.status}")
    output = ROOT / args.output
    log = ROOT / args.log if args.log else None
    payload = {
        "schema": "hepta.learning-operator-stage.v1",
        "schemaVersion": 1,
        "module": "learning.operator",
        "stage": args.stage,
        "status": args.status,
        "reason": args.reason,
        "command": args.command,
        "commandSha256": hashlib.sha256(args.command.encode("utf-8")).hexdigest(),
        "log": None
        if log is None
        else {
            "path": args.log,
            "present": log.is_file(),
            "sha256": sha256(log),
            "bytes": log.stat().st_size if log.is_file() else 0,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify(args: argparse.Namespace) -> None:
    root = ROOT / args.directory
    required = [value for value in args.required.split(",") if value]
    missing: list[str] = []
    non_passed: list[str] = []
    for stage in required:
        path = root / f"{stage}.json"
        if not path.is_file():
            missing.append(stage)
            continue
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("schema") != "hepta.learning-operator-stage.v1" or value.get("stage") != stage:
            raise ValueError(f"malformed stage receipt: {stage}")
        status = value.get("status")
        if status not in VALID:
            raise ValueError(f"invalid stage receipt status: {stage}: {status}")
        if status != "passed":
            non_passed.append(f"{stage}={status}")
    if missing or non_passed:
        raise SystemExit(
            "qualification stages are not all passed: "
            + ", ".join([*(f"{stage}=missing" for stage in missing), *non_passed])
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    write = subparsers.add_parser("record")
    write.add_argument("--stage", required=True)
    write.add_argument("--status", required=True, choices=sorted(VALID))
    write.add_argument("--reason", default="")
    write.add_argument("--command", default="")
    write.add_argument("--log")
    write.add_argument("--output", required=True)
    check = subparsers.add_parser("verify")
    check.add_argument("--directory", required=True)
    check.add_argument("--required", required=True)
    args = parser.parse_args()
    if args.action == "record":
        record(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
