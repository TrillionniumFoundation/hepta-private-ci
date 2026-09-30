#!/usr/bin/env python3
"""Bind API compile-fail and transitive source closure into the paired receipt."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

import channel_matrix_evidence_v2 as policy
import channel_matrix_pair_acceptance as base

API_LABEL = "api-compile-fail"
REQUIRED_EXACT_PATHS = {
    ".github/workflows/channel-matrix-preserve-unknown.yml",
    ".github/workflows/channel-matrix-materialize.yml",
    "codex-rs/hepta-supervisor/src/matrix.rs",
    "codex-rs/hepta-matrixd/tests/fixtures/run-hermetic-synapse.sh",
    "tests/fixtures/run-hermetic-synapse.sh",
}
REQUIRED_PREFIXES = {
    "codex-rs/hepta-contracts/",
    "codex-rs/hepta-operations/",
    "codex-rs/state/",
}


def _source_paths(source: dict[str, Any]) -> set[str]:
    rows = source.get("files")
    if not isinstance(rows, list) or not rows:
        raise ValueError("extended source inventory is empty")
    paths: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise ValueError("untyped extended source inventory")
        path = row["path"]
        if path in paths:
            raise ValueError("duplicate extended source path")
        paths.add(path)
    missing = REQUIRED_EXACT_PATHS - paths
    if missing:
        raise ValueError(f"source closure misses exact paths: {sorted(missing)}")
    missing_prefixes = [prefix for prefix in REQUIRED_PREFIXES if not any(path.startswith(prefix) for path in paths)]
    if missing_prefixes:
        raise ValueError(f"source closure misses owner roots: {sorted(missing_prefixes)}")
    return paths


def _api_receipt(directory: Path, source: dict[str, Any], inventory: dict[str, dict[str, Any]]) -> dict[str, Any]:
    command_name = f"{API_LABEL}.command.json"
    log_name = f"{API_LABEL}.log"
    if command_name not in inventory or log_name not in inventory:
        raise ValueError("paired manifest omits API compile-fail evidence")
    row = base.read_object(directory / command_name)
    log = directory / log_name
    if (
        row.get("schema") != "hepta.channel-matrix-command.v1"
        or row.get("label") != API_LABEL
        or row.get("arguments") != policy.API_COMPILE_FAIL_COMMAND
        or row.get("workingDirectory") != "codex-rs"
        or row.get("testedSha") != source.get("testedSha")
        or row.get("sourceSnapshotSha256") != base.digest(directory / "source.json")
        or type(row.get("exitCode")) is not int
        or row.get("exitCode") != 0
        or row.get("completed") is not True
        or row.get("launchError") is not None
        or row.get("sourceUnchanged") is not True
        or row.get("log")
        != {
            "path": log_name,
            "bytes": log.stat().st_size,
            "sha256": base.digest(log),
            "withinBudget": True,
        }
    ):
        raise ValueError("API compile-fail receipt is missing, failed or mismatched")
    return row


def _extended_lane(directory_value: Path, expected_lane: str) -> dict[str, Any]:
    row = base.lane(directory_value, expected_lane)
    _source_paths(row["source"])
    _api_receipt(row["directory"], row["source"], row["inventory"])
    return row


def paired(source_head: Path, base_merge: Path) -> dict[str, Any]:
    source = _extended_lane(source_head, "source-head")
    merge = _extended_lane(base_merge, "base-merge")
    # Reuse the canonical cross-lane semantic checks, then bind the two added
    # properties explicitly into a versioned receipt.
    result = base.paired(source_head, base_merge)
    result["schema"] = "hepta.channel-matrix-paired-qualification.v2"
    result["sourceClosurePassed"] = True
    result["apiCompileFailBoundaryPassed"] = True
    result["apiCompileFailArguments"] = policy.API_COMPILE_FAIL_COMMAND
    result["extendedLaneDigests"] = {
        "source-head": {
            "apiCommand": base.digest(source["directory"] / f"{API_LABEL}.command.json"),
            "apiLog": base.digest(source["directory"] / f"{API_LABEL}.log"),
        },
        "base-merge": {
            "apiCommand": base.digest(merge["directory"] / f"{API_LABEL}.command.json"),
            "apiLog": base.digest(merge["directory"] / f"{API_LABEL}.log"),
        },
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-head", type=Path, required=True)
    parser.add_argument("--base-merge", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        base.write_exclusive(args.output, paired(args.source_head, args.base_merge))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, re.error) as exc:
        parser.exit(1, f"FAIL_CHANNEL_MATRIX_PAIRED_QUALIFICATION_V2: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
