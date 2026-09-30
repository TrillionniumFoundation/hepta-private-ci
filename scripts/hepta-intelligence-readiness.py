#!/usr/bin/env python3
"""Summarize exact CI lane evidence without upgrading it to product qualification.

Artifact hashes establish byte identity; the Actions artifact download supplies
provenance. This verifier does not authenticate arbitrary locally authored logs.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import re
import subprocess
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "intelligence_acceptance",
    Path(__file__).with_name("hepta-intelligence-acceptance.py"),
)
assert SPEC is not None and SPEC.loader is not None
ACCEPTANCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ACCEPTANCE)
STATUS = ACCEPTANCE.STATUS


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def deterministic_merge_identity(base: str, source: str, number: str) -> dict[str, Any]:
    if (
        any(re.fullmatch(r"[0-9a-f]{40}", value) is None for value in (base, source))
        or re.fullmatch(r"[1-9][0-9]*", number) is None
    ):
        raise ValueError(
            "merge evidence requires exact parents and a pull-request number"
        )
    tree = STATUS.git("merge-tree", "--write-tree", base, source)
    body = (
        f"tree {tree}\nparent {base}\nparent {source}\n"
        "author Hepta Intelligence CI <hepta-intelligence-ci@users.noreply.github.com> 946684800 +0000\n"
        "committer Hepta Intelligence CI <hepta-intelligence-ci@users.noreply.github.com> 946684800 +0000\n\n"
        f"intelligence.control synthetic merge for PR {number}\n"
    )
    commit = subprocess.check_output(
        ["git", "hash-object", "-t", "commit", "--stdin"],
        cwd=ROOT,
        input=body,
        text=True,
    ).strip()
    return {"commit": commit, "tree": tree, "parents": [base, source], "dirty": False}


def artifact_files(root: Path) -> dict[str, Path]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("lane evidence directory missing or symlinked")
    files: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("symlinked lane evidence")
        if path.is_file():
            if path.name in files:
                raise ValueError(f"duplicate artifact filename: {path.name}")
            files[path.name] = path
    return files


def validate_receipt(
    path: Path,
    head: str,
    lane_name: str,
    trace: dict[str, Any],
    records: dict[str, tuple[dict[str, Any], str]],
) -> None:
    value = STATUS.load_json(path)
    expected_identity = {
        "commit": head,
        "lane": lane_name,
        "executionStatus": "passed",
        "commitMustEqualCheckoutHead": True,
    }
    if (
        value.get("schema") != ACCEPTANCE.SCHEMA
        or type(value.get("schemaVersion")) is not int
        or value["schemaVersion"] != 1
        or value.get("module") != "intelligence.control"
    ):
        raise ValueError("wrong acceptance receipt schema")
    if (
        value.get("sourceIdentity") != expected_identity
        or value["sourceIdentity"].get("commitMustEqualCheckoutHead") is not True
        or value.get("objectiveDefinitionSha256") != ACCEPTANCE.objective_digest()
    ):
        raise ValueError("acceptance receipt source or objective mismatch")
    boundary = {
        "sourceAndExactPackageAcceptance": True,
        "realProcessProviderE2E": False,
        "targetHostQualified": False,
        "independentAcceptance": False,
        "activation": False,
        "release": False,
    }
    if (
        value.get("claimBoundary") != boundary
        or any(
            value["claimBoundary"].get(key) is not expected
            for key, expected in boundary.items()
        )
        or value.get("remainingExternalGates") != list(ACCEPTANCE.EXTERNAL_GATES)
    ):
        raise ValueError("acceptance receipt exceeds the source/package claim boundary")
    tests = {
        row["name"]: (row, STATUS.PACKAGE_RECORDS[row["package"]])
        for row in trace["ordinaryProductTests"]
    }
    tests.update(
        {
            row["name"]: (row, "agentd-qualification-tests.json")
            for row in trace["qualificationOnlyTests"]
        }
    )
    expected = []
    for objective in ACCEPTANCE.OBJECTIVES:
        observed = {}
        for name in objective["mappedTests"]:
            _, record_name = tests[name]
            observed[name] = STATUS.observed_test_name(records[record_name][1], name)
        for test in objective["directTests"]:
            observed[test["name"]] = STATUS.observed_test_name(
                records[STATUS.PACKAGE_RECORDS[test["package"]]][1], test["name"]
            )
        expected.append(
            {
                "id": objective["id"],
                "stage": objective["stage"],
                "status": "passed",
                "observedTests": observed,
                "commandLogSha256": {
                    name: records[name][0]["log_sha256"]
                    for name in objective["commandRecords"]
                },
            }
        )
    if value.get("objectives") != expected:
        raise ValueError(
            "acceptance objectives do not match observed exact command evidence"
        )


def validate_lane(
    root: Path | None,
    lane_name: str,
    identity: dict[str, Any],
    source: str,
    base: str,
    invocation: dict[str, str],
    trace: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "missing_or_failed",
        "commandHashes": {},
        "logHashes": {},
        "artifactHashes": {},
    }
    try:
        if root is None:
            raise ValueError("lane evidence was not supplied")
        files = artifact_files(root)
        directory = str((ROOT / "codex-rs").resolve())
        records = {}
        for name, command in STATUS.COMMANDS.items():
            path = files[name]
            record, text = STATUS.validate_command_record(
                path,
                command,
                identity["commit"],
                lane_name,
                expected_identity=identity,
                expected_directory=directory,
                expected_invocation=invocation,
            )
            if record.get("source_sha") != source or record.get("base_sha") != base:
                raise ValueError(f"wrong exact source/base identity: {name}")
            records[name] = record, text
            result["commandHashes"][name] = sha256(path)
            result["logHashes"][record["log_file"]] = record["log_sha256"]
        for rows, legacy in (
            (trace["ordinaryProductTests"], False),
            (trace["qualificationOnlyTests"], True),
        ):
            for test in rows:
                name = (
                    "agentd-qualification-tests.json"
                    if legacy
                    else STATUS.PACKAGE_RECORDS[test["package"]]
                )
                STATUS.observed_test_name(records[name][1], test["name"])
        receipt = files["ACCEPTANCE_RECEIPT.json"]
        validate_receipt(receipt, identity["commit"], lane_name, trace, records)
        result["artifactHashes"]["ACCEPTANCE_RECEIPT.json"] = sha256(receipt)
        result["status"] = "passed"
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.CalledProcessError,
    ) as error:
        result["error"] = str(error)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "source-head-sha",
        "base-sha",
        "workflow-sha",
        "workflow-run-id",
        "workflow-attempt",
    ):
        parser.add_argument("--" + name, required=True)
    for name in (
        "deterministic-merge-sha",
        "github-merge-sha",
        "source-tree-hash",
        "pull-request-number",
    ):
        parser.add_argument("--" + name, default="")
    parser.add_argument("--runner-fingerprint", default=platform.platform())
    parser.add_argument("--target-triple", default="unknown")
    parser.add_argument("--rustc-version", default="unknown")
    parser.add_argument("--source-head-evidence", type=Path)
    parser.add_argument("--base-merge-evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(ROOT):
        raise ValueError("readiness manifest must be outside the source checkout")
    if args.source_head_sha != STATUS.git("rev-parse", "HEAD") or STATUS.git(
        "status", "--porcelain", "--untracked-files=normal"
    ):
        raise ValueError("readiness requires the unchanged exact source checkout")
    source_identity = STATUS.checkout_identity(args.source_head_sha)
    if args.source_tree_hash != source_identity[
        "tree"
    ] or args.workflow_sha != STATUS.git(
        "rev-parse", "HEAD:.github/workflows/hepta-intelligence-control.yml"
    ):
        raise ValueError("readiness source tree or workflow digest mismatch")
    _, trace = ACCEPTANCE.validate_objectives()
    invocation = {
        "run_id": args.workflow_run_id,
        "run_attempt": args.workflow_attempt,
        "job": "qualification",
    }
    source = validate_lane(
        args.source_head_evidence,
        "source-head",
        source_identity,
        args.source_head_sha,
        args.base_sha,
        invocation,
        trace,
    )
    merge: dict[str, Any] = {
        "status": "missing_or_failed",
        "commandHashes": {},
        "logHashes": {},
        "artifactHashes": {},
    }
    try:
        identity = deterministic_merge_identity(
            args.base_sha, args.source_head_sha, args.pull_request_number
        )
        if identity["commit"] != args.deterministic_merge_sha:
            raise ValueError(
                "merge SHA differs from the deterministic exact-parent candidate"
            )
        merge = validate_lane(
            args.base_merge_evidence,
            "base-merge",
            identity,
            args.source_head_sha,
            args.base_sha,
            invocation,
            trace,
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        merge["error"] = str(error)
    tracked = {
        "Cargo.lock_hash": sha256(ROOT / "codex-rs/Cargo.lock"),
        "implementation_map_hash": sha256(STATUS.DOCS / "IMPLEMENTATION_MAP.json"),
        "test_traceability_hash": sha256(STATUS.DOCS / "TEST_TRACEABILITY.json"),
        "acceptance_verifier_hash": sha256(
            ROOT / "scripts/hepta-intelligence-acceptance.py"
        ),
        "readiness_verifier_hash": sha256(Path(__file__)),
    }
    partitions = STATUS.DOCS / "REVIEW_PARTITIONS.json"
    if partitions.is_file():
        tracked["review_partitions_hash"] = sha256(partitions)
    lanes = {"source-head": source, "base-merge": merge}
    manifest = {
        "schema": "hepta.intelligence-control-readiness.v1",
        "source_head_sha": args.source_head_sha,
        "base_sha": args.base_sha,
        "deterministic_merge_sha": args.deterministic_merge_sha or None,
        "github_merge_sha": args.github_merge_sha or None,
        "workflow_sha": args.workflow_sha,
        "workflow_run_id": args.workflow_run_id,
        "workflow_attempt": args.workflow_attempt,
        "runner_image_or_host_fingerprint": args.runner_fingerprint,
        "target_triple": args.target_triple,
        "rustc_version": args.rustc_version,
        "source_tree_hash": source_identity["tree"],
        **tracked,
        "command_record_hashes": {
            name: row["commandHashes"] for name, row in lanes.items()
        },
        "raw_log_hashes": {name: row["logHashes"] for name, row in lanes.items()},
        "artifact_hashes": {name: row["artifactHashes"] for name, row in lanes.items()},
        "laneStatus": {name: row["status"] for name, row in lanes.items()},
        "laneErrors": {
            name: row["error"] for name, row in lanes.items() if "error" in row
        },
        "mergeReady": all(row["status"] == "passed" for row in lanes.values()),
        "productionQualified": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
