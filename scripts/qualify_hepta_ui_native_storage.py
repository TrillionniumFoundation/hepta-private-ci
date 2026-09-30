#!/usr/bin/env python3
"""Validate exact-SHA ui.native storage evidence and Linux durability syscalls."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

WRITE_CALLS = ("write(", "writev(", "pwrite64(", "pwritev(", "pwritev2(")
SYNC_CALLS = ("fsync(", "fdatasync(")
RETURN_VALUE = re.compile(r"\)\s+=\s+(-?\d+)(?:\s|$)")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{path} must contain a JSON object")
    return value


def integer(value: dict[str, Any], key: str) -> int:
    observed = value.get(key)
    require(isinstance(observed, int) and not isinstance(observed, bool), f"{key} is not an integer")
    return observed


def number(value: dict[str, Any], key: str) -> float:
    observed = value.get(key)
    require(
        isinstance(observed, (int, float)) and not isinstance(observed, bool),
        f"{key} is not numeric",
    )
    result = float(observed)
    require(math.isfinite(result) and result >= 0.0, f"{key} is not a finite non-negative number")
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_traces(prefix: Path, storage_root: str) -> tuple[int, int, list[dict[str, Any]]]:
    traces = sorted(prefix.parent.glob(f"{prefix.name}*"))
    require(traces, f"no strace files matched {prefix}*")
    write_bytes = 0
    sync_calls = 0
    inventory: list[dict[str, Any]] = []
    for trace in traces:
        inventory.append(
            {
                "path": trace.name,
                "bytes": trace.stat().st_size,
                "sha256": sha256_file(trace),
            }
        )
        for line in trace.read_text(encoding="utf-8", errors="strict").splitlines():
            if storage_root not in line:
                continue
            result = RETURN_VALUE.search(line)
            if result is None:
                continue
            returned = int(result.group(1))
            if returned < 0:
                continue
            if any(call in line for call in WRITE_CALLS):
                write_bytes += returned
            if returned == 0 and any(call in line for call in SYNC_CALLS):
                sync_calls += 1
    require(write_bytes > 0, "strace observed no successful durable-state writes")
    require(sync_calls > 0, "strace observed no successful fsync/fdatasync calls")
    return write_bytes, sync_calls, inventory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budgets", type=Path, required=True)
    parser.add_argument("--active", type=Path, required=True)
    parser.add_argument("--retired", type=Path, required=True)
    parser.add_argument("--trace-prefix", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--emit", type=Path, required=True)
    args = parser.parse_args()

    require(
        len(args.source_sha) == 40 and all(character in "0123456789abcdef" for character in args.source_sha),
        "--source-sha must be a lowercase 40-character Git SHA",
    )
    budgets = load_object(args.budgets)
    active = load_object(args.active)
    retired = load_object(args.retired)
    structural = budgets.get("structural")
    performance = budgets.get("performance")
    require(isinstance(structural, dict), "storage structural budgets are missing")
    require(isinstance(performance, dict), "storage performance budgets are missing")
    require(budgets.get("status") == "provisional-unqualified", "input budgets falsely claim qualification")
    require(budgets.get("measurements") is None, "input budgets contain mutable embedded measurements")

    require(active.get("sourceSha") == args.source_sha, "active evidence source SHA mismatch")
    require(retired.get("sourceSha") == args.source_sha, "retirement evidence source SHA mismatch")
    require(
        integer(active, "activeRecords") == int(performance["activeRecordsSubject"]),
        "active-record qualification subject mismatch",
    )
    require(
        integer(active, "activeRecords") == int(structural["maxActiveRecords"]),
        "active-record qualification did not reach the structural ceiling",
    )
    require(
        integer(retired, "retiredIdentities") == int(performance["retiredIdentitiesSubject"]),
        "retired-identity qualification subject mismatch",
    )
    require(active.get("schema") == "hepta.ui-native-storage-active-evidence.v1", "active evidence schema mismatch")
    require(
        retired.get("schema") == "hepta.ui-native-storage-retirement-evidence.v1",
        "retirement evidence schema mismatch",
    )

    metric_limits = {
        "coldStartMilliseconds": "coldStartP95Milliseconds",
        "mutationP50Milliseconds": "mutationP50Milliseconds",
        "mutationP95Milliseconds": "mutationP95Milliseconds",
        "mutationP99Milliseconds": "mutationP99Milliseconds",
    }
    for metric, budget_name in metric_limits.items():
        require(
            number(active, metric) <= float(performance[budget_name]),
            f"{metric} exceeded {budget_name}",
        )
    require(
        number(retired, "indexedColdOpenMilliseconds")
        <= float(performance["coldStartP95Milliseconds"]),
        "million-retired indexed cold open exceeded its hard ceiling",
    )
    require(
        number(retired, "indexRebuildMilliseconds")
        <= float(performance["millionRetiredIndexRebuildP95Milliseconds"]),
        "million-retired index rebuild exceeded its hard ceiling",
    )
    require(retired.get("deterministicRebuild") is True, "retirement index rebuild was not deterministic")
    require(
        integer(retired, "peakRssMiB") <= int(performance["millionRetiredPeakRssMiB"]),
        "million-retired peak RSS exceeded its hard ceiling",
    )
    require(
        integer(active, "snapshotBytes") <= int(structural["maxSnapshotBytes"]),
        "active snapshot exceeded its structural byte ceiling",
    )
    require(
        integer(active, "walBytes") <= int(structural["maxWalBytes"]),
        "active WAL exceeded its structural byte ceiling",
    )

    storage_root = active.get("root")
    require(isinstance(storage_root, str) and storage_root, "active evidence lacks its storage root")
    write_bytes, sync_calls, trace_inventory = parse_traces(args.trace_prefix, storage_root)
    transitions = integer(active, "transitions")
    require(transitions > 0, "active evidence contains no state transitions")
    write_bytes_per_transition = math.ceil(write_bytes / transitions)
    require(
        write_bytes_per_transition
        <= int(performance["maximumWriteAmplificationBytesPerStateTransition"]),
        "durable write amplification exceeded its hard ceiling",
    )

    combined = {
        "schema": "hepta.ui-native-storage-qualification.v1",
        "sourceSha": args.source_sha,
        "status": "pass",
        "storageQualified": True,
        "productionQualified": False,
        "deploymentQualified": False,
        "releaseAuthorized": False,
        "activeEvidence": {
            "path": args.active.name,
            "sha256": sha256_file(args.active),
            "measurements": active,
        },
        "retirementEvidence": {
            "path": args.retired.name,
            "sha256": sha256_file(args.retired),
            "measurements": retired,
        },
        "durabilitySyscalls": {
            "writeBytes": write_bytes,
            "stateTransitions": transitions,
            "writeBytesPerTransition": write_bytes_per_transition,
            "fsyncOrFdatasyncCalls": sync_calls,
            "traceFiles": trace_inventory,
        },
        "budgets": {
            "path": args.budgets.name,
            "sha256": sha256_file(args.budgets),
            "structural": structural,
            "performance": performance,
        },
        "limitations": [
            "Linux hosted-runner evidence is not physical desktop acceptance",
            "storage qualification alone does not authorize production, deployment or release",
        ],
    }
    args.emit.parent.mkdir(parents=True, exist_ok=True)
    args.emit.write_text(json.dumps(combined, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(combined, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
