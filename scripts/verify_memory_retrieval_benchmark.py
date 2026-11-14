#!/usr/bin/env python3
"""Parse memory.retrieval benchmark logs, enforce ceilings, and emit a receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

TARGET_SCHEMA = "hepta.memory-retrieval.target-host.v1"
E2E_SCHEMA = "hepta.memory-retrieval.e2e-slo.v1"
TIME_PATTERNS = {
    "user_seconds": re.compile(r"User time \(seconds\):\s*([0-9.]+)"),
    "system_seconds": re.compile(r"System time \(seconds\):\s*([0-9.]+)"),
    "max_rss_kb": re.compile(r"Maximum resident set size \(kbytes\):\s*(\d+)"),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_log(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        start = line.find("{")
        if start < 0:
            continue
        try:
            value = json.loads(line[start:])
        except json.JSONDecodeError:
            continue
        if value.get("schema") in {TARGET_SCHEMA, E2E_SCHEMA}:
            records.append(value)
    if len(records) != 1:
        raise ValueError(f"{path}: expected exactly one benchmark JSON record, found {len(records)}")
    resource: dict[str, Any] = {}
    for name, pattern in TIME_PATTERNS.items():
        match = pattern.search(text)
        if match:
            resource[name] = float(match.group(1)) if "seconds" in name else int(match.group(1))
    return {"record": records[0], "resource": resource, "sha256": _sha256(path), "path": path.name}


def enforce(records: list[dict[str, Any]], limits: dict[str, Any]) -> None:
    phases = {str(row["record"].get("phase")): row["record"] for row in records}
    configured = limits.get("phases") or {}
    missing = sorted(set(configured) - set(phases))
    if missing:
        raise ValueError(f"missing required benchmark phases: {', '.join(missing)}")
    for phase, contract in configured.items():
        record = phases[phase]
        for metric, maximum in (contract.get("maximum") or {}).items():
            actual = record.get(metric)
            if not isinstance(actual, (int, float)):
                raise ValueError(f"{phase}.{metric} is missing or non-numeric")
            if actual > maximum:
                raise ValueError(f"{phase}.{metric}={actual} exceeds maximum {maximum}")
        for metric, minimum in (contract.get("minimum") or {}).items():
            actual = record.get(metric)
            if not isinstance(actual, (int, float)):
                raise ValueError(f"{phase}.{metric} is missing or non-numeric")
            if actual < minimum:
                raise ValueError(f"{phase}.{metric}={actual} is below minimum {minimum}")


def build_receipt(
    logs: list[Path],
    limits_path: Path,
    host_path: Path,
    *,
    source_commit: str,
    source_tree: str,
) -> dict[str, Any]:
    limits = json.loads(limits_path.read_text(encoding="utf-8"))
    parsed = [parse_log(path) for path in logs]
    enforce(parsed, limits)
    return {
        "schema": "hepta.memory-retrieval.qualification-receipt.v1",
        "claimBoundary": "github_hosted_qualification_not_production_target_acceptance",
        "sourceCommit": source_commit,
        "sourceTree": source_tree,
        "limitsSha256": _sha256(limits_path),
        "hostSha256": _sha256(host_path),
        "measurements": parsed,
        "decision": "qualification_limits_passed",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", action="append", type=Path, required=True)
    parser.add_argument("--limits", type=Path, required=True)
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = build_receipt(
        args.log,
        args.limits,
        args.host,
        source_commit=args.source_commit,
        source_tree=args.source_tree,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
