#!/usr/bin/env python3
"""Verify memory.retrieval target-host logs against a checked-in profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
from typing import Any

SCHEMA = "hepta.memory-retrieval.target-host.v1"
RECEIPT_SCHEMA = "hepta.memory-retrieval.qualification-receipt.v1"
RSS_RE = re.compile(r"Maximum resident set size \(kbytes\):\s*(\d+)")


def load_measurement(path: pathlib.Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="strict")
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if SCHEMA not in line:
            continue
        start = line.find("{")
        if start < 0:
            continue
        value = json.loads(line[start:])
        if value.get("schema") == SCHEMA:
            rows.append(value)
    if len(rows) != 1:
        raise ValueError(f"{path}: expected exactly one {SCHEMA} row, found {len(rows)}")
    rss = RSS_RE.findall(text)
    if len(rss) != 1:
        raise ValueError(f"{path}: expected one GNU-time maximum RSS field, found {len(rss)}")
    row = rows[0]
    row["maximum_rss_kb"] = int(rss[0])
    row["log_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return row


def verify_phase(measurement: dict[str, Any], limits: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for metric, maximum in sorted(limits.items()):
        actual = measurement.get(metric)
        if not isinstance(actual, int):
            failures.append(f"missing integer metric {metric}")
        elif actual > maximum:
            failures.append(f"{metric}={actual} exceeds {maximum}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--thresholds", required=True, type=pathlib.Path)
    parser.add_argument("--log", action="append", required=True, type=pathlib.Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()

    thresholds = json.loads(args.thresholds.read_text(encoding="utf-8"))
    if thresholds.get("schema") != "hepta.memory-retrieval.slo-thresholds.v1":
        raise ValueError("unsupported threshold schema")
    measurements = [load_measurement(path) for path in args.log]
    by_phase = {row["phase"]: row for row in measurements}
    failures: list[str] = []
    for phase, limits in thresholds["phases"].items():
        row = by_phase.get(phase)
        if row is None:
            failures.append(f"missing phase {phase}")
            continue
        failures.extend(f"{phase}: {failure}" for failure in verify_phase(row, limits))

    receipt = {
        "schema": RECEIPT_SCHEMA,
        "source_sha": args.source_sha,
        "source_tree": args.source_tree,
        "threshold_profile": thresholds["profile"],
        "measurements": sorted(measurements, key=lambda row: row["phase"]),
        "failures": failures,
        "passed": not failures,
    }
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
