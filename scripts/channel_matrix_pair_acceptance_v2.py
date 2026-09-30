#!/usr/bin/env python3
"""Bind repository regressions and transitive source closure into the paired receipt."""
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
import channel_matrix_source_provenance as source_provenance

API_LABEL = "api-compile-fail"
FOCUSED_LABEL = "focused-tests"
PROVENANCE_FILE = "source-provenance.json"
EXTENDED_LOCAL_STATES = ("api_compile_fail", "clean_tree")
REQUIRED_EXACT_PATHS = {
    ".github/workflows/channel-matrix-preserve-unknown.yml",
    ".github/workflows/channel-matrix-materialize.yml",
    "codex-rs/hepta-supervisor/src/matrix.rs",
    "codex-rs/hepta-matrixd/tests/fixtures/run-hermetic-synapse.sh",
    "tests/fixtures/run-hermetic-synapse.sh",
    "docs/modules/channel.matrix/MODULE_STATUS.json",
    "docs/modules/channel.matrix/PROCESS_FAULT_MATRIX.json",
    "docs/modules/channel.matrix/REVIEW_SLICES.json",
    "docs/modules/channel.matrix/TRANSPORT_TCB.json",
    "scripts/channel_matrix_process_qualification.py",
    "scripts/channel_matrix_readiness.py",
    "scripts/channel_matrix_source_provenance.py",
    "scripts/channel_matrix_transport_tcb.py",
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
    missing_prefixes = [
        prefix for prefix in REQUIRED_PREFIXES if not any(path.startswith(prefix) for path in paths)
    ]
    if missing_prefixes:
        raise ValueError(f"source closure misses owner roots: {sorted(missing_prefixes)}")
    return paths


def _command_receipt(
    directory: Path,
    source: dict[str, Any],
    inventory: dict[str, dict[str, Any]],
    label: str,
    arguments: list[str],
    *,
    require_junit: bool,
) -> dict[str, Any]:
    command_name = f"{label}.command.json"
    log_name = f"{label}.log"
    if command_name not in inventory or log_name not in inventory:
        raise ValueError(f"paired manifest omits {label} evidence")
    row = base.read_object(directory / command_name)
    log = directory / log_name
    expected_junit: dict[str, Any] | None = None
    if require_junit:
        junit_name = "focused-tests.junit.xml"
        if junit_name not in inventory:
            raise ValueError("paired manifest omits focused JUnit evidence")
        junit = directory / junit_name
        expected_junit = {
            "path": junit_name,
            "bytes": junit.stat().st_size,
            "sha256": base.digest(junit),
        }
    if (
        row.get("schema") != "hepta.channel-matrix-command.v1"
        or row.get("label") != label
        or row.get("arguments") != arguments
        or row.get("workingDirectory") != "codex-rs"
        or row.get("testedSha") != source.get("testedSha")
        or row.get("sourceSnapshotSha256") != base.digest(directory / "source.json")
        or type(row.get("exitCode")) is not int
        or row.get("exitCode") != 0
        or row.get("completed") is not True
        or row.get("launchError") is not None
        or row.get("sourceUnchanged") is not True
        or row.get("junit") != expected_junit
        or row.get("log")
        != {
            "path": log_name,
            "bytes": log.stat().st_size,
            "sha256": base.digest(log),
            "withinBudget": True,
        }
    ):
        raise ValueError(f"{label} receipt is missing, failed or mismatched")
    return row


def _provenance_receipt(
    directory: Path,
    source: dict[str, Any],
    inventory: dict[str, dict[str, Any]],
    expected_lane: str,
) -> dict[str, Any]:
    if PROVENANCE_FILE not in inventory:
        raise ValueError("paired manifest omits source provenance")
    row = base.read_object(directory / PROVENANCE_FILE)
    manifest = base.read_object(directory / "manifest.json")
    source_provenance.validate_receipt(
        row,
        expected_stage=expected_lane,
        expected_sha=str(source.get("testedSha", "")),
        expected_tree=str(source.get("testedTree", "")),
        expected_run=manifest.get("runId"),
        expected_attempt=manifest.get("runAttempt"),
    )
    return row


def _extended_lane(directory_value: Path, expected_lane: str) -> dict[str, Any]:
    row = base.lane(directory_value, expected_lane)
    _source_paths(row["source"])
    row["provenance"] = _provenance_receipt(
        row["directory"], row["source"], row["inventory"], expected_lane
    )
    states = row["status"].get("states")
    if not isinstance(states, dict) or any(
        states.get(name) != "passed" for name in EXTENDED_LOCAL_STATES
    ):
        raise ValueError("extended repository-controlled states did not pass")
    for label, arguments in policy.evidence.COMMANDS.items():
        _command_receipt(
            row["directory"],
            row["source"],
            row["inventory"],
            label,
            arguments,
            require_junit=label == FOCUSED_LABEL,
        )
    return row


def paired(source_head: Path, base_merge: Path) -> dict[str, Any]:
    source = _extended_lane(source_head, "source-head")
    merge = _extended_lane(base_merge, "base-merge")
    source_manifest = source["manifest"]
    merge_manifest = merge["manifest"]
    if (
        source_manifest.get("runId") != merge_manifest.get("runId")
        or source_manifest.get("runAttempt") != merge_manifest.get("runAttempt")
    ):
        raise ValueError("source-head and deterministic merge mix workflow attempts")
    result = base.paired(source_head, base_merge)
    result["schema"] = "hepta.channel-matrix-paired-qualification.v4"
    result["workflowRunId"] = source_manifest.get("runId")
    result["attemptId"] = source_manifest.get("runAttempt")
    result["sameWorkflowAttempt"] = True
    result["sourceClosurePassed"] = True
    result["sourceProvenancePassed"] = True
    result["apiCompileFailBoundaryPassed"] = True
    result["repositoryRegressionSuitePassed"] = True
    result["allCanonicalCommandsRevalidated"] = True
    result["cleanTreePassed"] = True
    result["ownerPackages"] = list(policy.OWNER_PACKAGES)
    result["canonicalCommandArguments"] = policy.evidence.COMMANDS
    result["apiCompileFailArguments"] = policy.API_COMPILE_FAIL_COMMAND
    result["focusedGateArguments"] = policy.FOCUSED_GATE_COMMAND
    result["extendedLaneDigests"] = {}
    for lane_name, lane in (("source-head", source), ("base-merge", merge)):
        directory = lane["directory"]
        command_digests = {}
        for label in policy.evidence.COMMANDS:
            command_digests[label] = {
                "command": base.digest(directory / f"{label}.command.json"),
                "log": base.digest(directory / f"{label}.log"),
            }
            if label == FOCUSED_LABEL:
                command_digests[label]["junit"] = base.digest(
                    directory / "focused-tests.junit.xml"
                )
        provenance = lane["provenance"]
        result["extendedLaneDigests"][lane_name] = {
            "sourceProvenance": base.digest(directory / PROVENANCE_FILE),
            "sourceInventory": provenance["sourceInventorySha256"],
            "sourceContentInventory": provenance["sourceContentInventorySha256"],
            "apiCommand": base.digest(directory / f"{API_LABEL}.command.json"),
            "apiLog": base.digest(directory / f"{API_LABEL}.log"),
            "focusedCommand": base.digest(directory / f"{FOCUSED_LABEL}.command.json"),
            "focusedLog": base.digest(directory / f"{FOCUSED_LABEL}.log"),
            "focusedJunit": base.digest(directory / "focused-tests.junit.xml"),
            "commands": command_digests,
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
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        re.error,
    ) as exc:
        parser.exit(1, f"FAIL_CHANNEL_MATRIX_PAIRED_QUALIFICATION_V4: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
