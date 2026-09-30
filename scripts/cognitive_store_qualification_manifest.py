#!/usr/bin/env python3
"""Aggregate exact-command cognitive.store CI records into one signed-by-Git identity manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--tested-sha", required=True)
    parser.add_argument("--lane", choices=["source-head", "base-merge"], required=True)
    args = parser.parse_args()
    for value in (args.source_sha, args.tested_sha):
        if re.fullmatch(r"[0-9a-f]{40}", value) is None:
            raise SystemExit("invalid Git identity")
    records = []
    failures = []
    for path in sorted(args.records.glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("status") != "passed" or row.get("exit_code") != 0:
            failures.append(path.name)
        if row.get("source_sha") != args.source_sha or row.get("tested_sha") != args.tested_sha or row.get("lane") != args.lane:
            failures.append(path.name + ":identity")
        records.append(
            {
                "name": path.name,
                "sha256": digest_file(path),
                "command": row.get("command"),
                "status": row.get("status"),
                "passedTests": row.get("observed_passed_tests", 0),
                "failedTests": row.get("observed_failed_tests", 0),
                "elapsedSeconds": row.get("elapsed_seconds"),
                "tree": row.get("after", {}).get("tree"),
            }
        )
    required = {
        "architecture.json",
        "format.json",
        "cognitive-store-tests.json",
        "memory-tests.json",
        "agentd-product-tests.json",
        "crash-reopen.json",
        "perf-256-command.json",
        "perf-16384-command.json",
        "clippy-store-memory.json",
        "clippy-agentd.json",
        "bootstrap-tests.json",
    }
    missing = sorted(required - {row["name"] for row in records})
    if missing:
        failures.extend("missing:" + name for name in missing)
    if failures:
        raise SystemExit("qualification records are incomplete: " + ", ".join(failures))
    manifest = {
        "schema": "hepta.cognitive-store-qualification-manifest.v1",
        "sourceSha": args.source_sha,
        "testedSha": args.tested_sha,
        "lane": args.lane,
        "terminalSuccess": True,
        "records": records,
        "claimBoundary": {
            "sourceImplementation": True,
            "productExecutionAtTestHost": True,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
