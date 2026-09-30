#!/usr/bin/env python3
"""Bind regressions, source closure and review slices into the paired receipt."""
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
import channel_matrix_review_slices as review_slices
import channel_matrix_source_provenance as source_provenance

API_LABEL = "api-compile-fail"
FOCUSED_LABEL = "focused-tests"
PROVENANCE_FILE = "source-provenance.json"
REVIEW_FILE = "review-slices.json"
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
    "scripts/channel_matrix_review_slices.py",
    "scripts/channel_matrix_source_provenance.py",
    "scripts/channel_matrix_transport_tcb.py",
}
REQUIRED_PREFIXES = {
    "codex-rs/hepta-contracts/",
    "codex-rs/hepta-operations/",
    "codex-rs/state/",
}
REVIEW_FIELDS = {
    "id",
    "owner",
    "deputy",
    "paths",
    "invariants",
    "commands",
    "firstCommit",
    "lastCommit",
    "commitCount",
    "commits",
    "changedPathCount",
    "changedPaths",
    "sourceRangeSha256",
    "invariantPolicySha256",
    "commandEvidenceSha256",
    "sourceBound",
    "invariantPolicyBound",
    "commandEvidenceBound",
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


def _command_evidence(
    directory: Path,
    source: dict[str, Any],
    inventory: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    rows: dict[str, Any] = {}
    for label, arguments in policy.evidence.COMMANDS.items():
        receipt = _command_receipt(
            directory,
            source,
            inventory,
            label,
            arguments,
            require_junit=label == FOCUSED_LABEL,
        )
        junit = receipt.get("junit")
        rows[label] = {
            "arguments": arguments,
            "commandReceiptSha256": base.digest(directory / f"{label}.command.json"),
            "logSha256": base.digest(directory / f"{label}.log"),
            "junitSha256": junit.get("sha256") if isinstance(junit, dict) else None,
        }
    return rows, review_slices.object_digest(rows, review_slices.COMMAND_SET_DOMAIN)


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


def _path_matches(path: str, pathspecs: list[str]) -> bool:
    return any(path == value or path.startswith(value.rstrip("/") + "/") for value in pathspecs)


def _review_receipt(
    directory: Path,
    source: dict[str, Any],
    inventory: dict[str, dict[str, Any]],
    expected_lane: str,
    provenance: dict[str, Any],
    command_evidence: dict[str, Any],
    command_set_sha256: str,
) -> dict[str, Any]:
    if REVIEW_FILE not in inventory:
        raise ValueError("paired manifest omits review-slice evidence")
    row = base.read_object(directory / REVIEW_FILE)
    manifest = base.read_object(directory / "manifest.json")
    policies, registry_sha256 = review_slices.load_registry()
    if (
        row.get("schema") != review_slices.RESULT_SCHEMA
        or row.get("module") != "channel.matrix"
        or row.get("lane") != expected_lane
        or row.get("sourceSha") != source.get("sourceSha")
        or row.get("baseSha") != source.get("baseSha")
        or row.get("testedSha") != source.get("testedSha")
        or row.get("testedTree") != source.get("testedTree")
        or row.get("workflowRunId") != manifest.get("runId")
        or row.get("attemptId") != manifest.get("runAttempt")
        or row.get("sourceProvenanceSha256") != base.digest(directory / PROVENANCE_FILE)
        or row.get("sourceInventorySha256") != provenance.get("sourceInventorySha256")
        or row.get("sourceContentInventorySha256")
        != provenance.get("sourceContentInventorySha256")
        or row.get("registrySha256") != registry_sha256
        or row.get("commandSetSha256") != command_set_sha256
        or row.get("commandEvidence") != command_evidence
        or row.get("allSlicesSourceBound") is not True
        or row.get("allSlicesInvariantPolicyBound") is not True
        or row.get("allSlicesCommandEvidenceBound") is not True
        or row.get("authorityGranted") is not False
        or row.get("activation") is not False
        or row.get("promotion") is not False
        or row.get("release") is not False
    ):
        raise ValueError("review-slice receipt identity or denial boundary mismatch")
    slices = row.get("slices")
    if (
        not isinstance(slices, list)
        or len(slices) != len(policies)
        or tuple(item.get("id") for item in slices if isinstance(item, dict))
        != review_slices.EXPECTED_SLICE_IDS
    ):
        raise ValueError("review-slice receipt inventory is incomplete or reordered")
    for item, policy in zip(slices, policies):
        policy_row = {
            "id": policy["id"],
            "owner": policy["owner"],
            "deputy": policy["deputy"],
            "paths": policy["paths"],
            "invariants": policy["invariants"],
            "commands": policy["commands"],
        }
        commits = item.get("commits") if isinstance(item, dict) else None
        changed = item.get("changedPaths") if isinstance(item, dict) else None
        if (
            not isinstance(item, dict)
            or set(item) != REVIEW_FIELDS
            or any(item.get(key) != value for key, value in policy_row.items())
            or not isinstance(commits, list)
            or not commits
            or any(not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit) for commit in commits)
            or item.get("firstCommit") != commits[0]
            or item.get("lastCommit") != commits[-1]
            or item.get("commitCount") != len(commits)
            or not isinstance(changed, list)
            or not changed
            or changed != sorted(set(changed))
            or any(not isinstance(path, str) or not _path_matches(path, policy["paths"]) for path in changed)
            or item.get("changedPathCount") != len(changed)
            or item.get("sourceRangeSha256")
            != review_slices.object_digest(
                {
                    "base": source["baseSha"],
                    "source": source["sourceSha"],
                    "commits": commits,
                    "paths": changed,
                },
                review_slices.SOURCE_RANGE_DOMAIN,
            )
            or item.get("invariantPolicySha256")
            != review_slices.object_digest(policy_row, review_slices.INVARIANT_POLICY_DOMAIN)
            or item.get("commandEvidenceSha256") != command_set_sha256
            or item.get("sourceBound") is not True
            or item.get("invariantPolicyBound") is not True
            or item.get("commandEvidenceBound") is not True
        ):
            raise ValueError(f"invalid review-slice evidence: {policy['id']}")
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
    commands, command_set_sha256 = _command_evidence(
        row["directory"], row["source"], row["inventory"]
    )
    row["review"] = _review_receipt(
        row["directory"],
        row["source"],
        row["inventory"],
        expected_lane,
        row["provenance"],
        commands,
        command_set_sha256,
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
    result["reviewSlicesPassed"] = True
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
            "reviewSlices": base.digest(directory / REVIEW_FILE),
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
