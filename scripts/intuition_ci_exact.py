#!/usr/bin/env python3
"""Resource-bounded CI entry point; never edits the qualification checkout.

Calls the existing exact-source or ledger entry point unchanged. Adds runner,
workflow, Git-parent and resource evidence to that entry point's own bundle.
An infrastructure failure is retained as failure, never converted to success.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import os
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
import intuition_qualify_exact as q

BUILD_ENV = {
    "CARGO_INCREMENTAL": "0",
    "CARGO_PROFILE_DEV_DEBUG": "0",
    "CARGO_PROFILE_TEST_DEBUG": "0",
    "CARGO_PROFILE_RELEASE_DEBUG": "0",
    "CARGO_PROFILE_RELEASE_INCREMENTAL": "false",
    "CARGO_BUILD_JOBS": "2",
    "PYTHONDONTWRITEBYTECODE": "1",
}


def resources(path: Path) -> dict:
    usage = shutil.disk_usage(path)
    return {
        "path": str(path),
        "totalBytes": usage.total,
        "usedBytes": usage.used,
        "freeBytes": usage.free,
    }


def classify(row: dict, evidence: Path) -> str:
    if row.get("status") == "passed" and row.get("exitCode") == 0:
        return "passed"
    if row.get("exitCode") in (124, 127, 130):
        return "infrastructure_invalid"
    log = row.get("log")
    if isinstance(log, str) and Path(log).name == log:
        path = evidence / log
        if path.is_file() and not path.is_symlink():
            # Stream the entire log: an ENOSPC diagnostic need not be in its tail.
            with path.open(encoding="utf-8", errors="replace") as stream:
                if any(
                    line.lstrip().lower().startswith("error:")
                    and "no space left on device" in line.lower()
                    for line in stream
                ):
                    return "infrastructure_invalid"
    return "test_or_build_failed"


def enrich(evidence: Path, before: dict, target: Path, exit_code: int) -> None:
    receipt = evidence / "command-record.json"
    record = json.loads(receipt.read_text())
    raw_commit = subprocess.check_output(
        ["git", "cat-file", "commit", record["testedSha"]], cwd=q.ROOT
    )
    record["testedCommitObjectBase64"] = base64.b64encode(raw_commit).decode("ascii")
    record["testedParents"] = q.git(
        "rev-list", "--parents", "-n", "1", record["testedSha"]
    ).split()[1:]
    record["workflowSha"] = os.environ.get("GITHUB_WORKFLOW_SHA")
    record["workflowRef"] = os.environ.get("GITHUB_WORKFLOW_REF")
    record["runner"] = {
        key: os.environ.get(key)
        for key in (
            "RUNNER_OS",
            "RUNNER_ARCH",
            "RUNNER_NAME",
            "ImageOS",
            "ImageVersion",
        )
    }
    record["buildEnvironment"] = {key: os.environ.get(key) for key in BUILD_ENV}
    record["resourceEvidence"] = "ci-resources.json"
    classes = [classify(row, evidence) for row in record.get("commands", [])]
    for row, status in zip(record.get("commands", []), classes):
        row["failureClass"] = status
    if "infrastructure_invalid" in classes:
        record["executionStatusBeforeClassification"] = record["status"]
        record["status"] = "infrastructure_invalid"
    q.write_json(
        evidence / "ci-resources.json",
        {
            "schema": "hepta.intuition.ci-resources.v1",
            "before": before,
            "after": resources(target),
            "exitCode": exit_code,
            "buildEnvironment": record["buildEnvironment"],
            "note": "Resource snapshots are not product capacity or latency benchmarks.",
        },
    )
    retain_binaries(record, evidence, target)
    q.write_json(receipt, record)
    if record.get("schema") == q.SCHEMA:
        name = (
            "independent-report.json"
            if record["mode"] == "independent"
            else "qualification-report.json"
        )
        q.write_json(evidence / name, record)
        q.project(record, evidence)
    else:
        q.write_json(evidence / "ledger-report.json", record)
    state = {
        "schema": "hepta.intuition.current-state.v1",
        "sourceCommit": record["sourceSha"],
        "testedCommit": record["testedSha"],
        "testedTree": record["testedTree"],
        "lane": record.get("lane", "ledger"),
        "executionStatus": record["status"],
        "record": "command-record.json",
        "runId": record.get("runId"),
        "runAttempt": record.get("runAttempt"),
        "is_production_implemented": False,
        "happy_path_verified": False,
        "edge_failures_verified": False,
        "has_independent_acceptance_proof": False,
        "promotion": "not_authorized",
    }
    q.write_json(evidence / "CURRENT_STATE.json", state)
    (evidence / "TECHNICAL_STATUS.md").write_text(
        "# Generated intuition.policy execution status\n\n"
        f"Tested commit: `{state['testedCommit']}`\n\n"
        f"Tested tree: `{state['testedTree']}`\n\n"
        f"Execution: `{state['executionStatus']}`; lane: `{state['lane']}`.\n\n"
        "The canonical state is CURRENT_STATE.json. This execution does not grant "
        "semantic evaluator, operator, target-host or production approval.\n",
        encoding="utf-8",
    )
    q.seal(evidence)


def retain_binaries(record: dict, evidence: Path, target: Path) -> None:
    """Retain exactly the binaries reported by Cargo, never arbitrary paths."""
    for row in record.get("commands", []):
        if row.get("name") != "release-binaries" or row.get("status") != "passed":
            continue
        executables = {}
        with (evidence / row["log"]).open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if (
                    isinstance(message, dict)
                    and message.get("reason") == "compiler-artifact"
                    and message.get("executable")
                    and "bin" in message.get("target", {}).get("kind", [])
                ):
                    executables[message["target"]["name"]] = Path(message["executable"])
        for binary in row["binaries"]:
            name = binary["name"]
            if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
                raise ValueError("invalid release binary name")
            source = executables[name]
            if source.is_symlink() or target not in source.resolve().parents:
                raise ValueError(
                    "release binary must be inside the CI target directory"
                )
            destination = evidence / ("release--" + name)
            if destination.exists():
                raise ValueError("duplicate release binary")
            shutil.copyfile(source, destination)
            if q.sha256(destination) != binary["sha256"]:
                raise ValueError("release binary changed after compilation")
            binary["artifact"] = destination.name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kind", choices=("qualification", "ledger"), default="qualification"
    )
    parser.add_argument("--evidence", required=True, type=Path)
    args, forwarded = parser.parse_known_args(argv)
    # Reject stale paths before writing anything; the child owns creation.
    evidence = args.evidence.resolve()
    if evidence == q.ROOT or q.ROOT in evidence.parents:
        parser.error("evidence must be outside the tested checkout")
    if evidence.exists() and any(evidence.iterdir()):
        parser.error("evidence directory must be empty")
    os.environ.update(BUILD_ENV)
    target = Path(
        os.environ.get("CARGO_TARGET_DIR", str(evidence.parent / "intuition-target"))
    ).resolve()
    if target == q.ROOT or q.ROOT in target.parents:
        parser.error("CI build output must be outside the tested checkout")
    if target == evidence or target in evidence.parents or evidence in target.parents:
        parser.error("build output and evidence must not overlap")
    target.mkdir(parents=True, exist_ok=True)
    os.environ["CARGO_TARGET_DIR"] = str(target)
    before = resources(target)
    child_args = [*forwarded, "--evidence", str(evidence)]
    if args.kind == "ledger":
        import intuition_ledger_exact as ledger

        code = ledger.main(child_args)
    else:
        code = q.main(child_args)
    try:
        enrich(evidence, before, target, code)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        receipt = evidence / "command-record.json"
        record = json.loads(receipt.read_text())
        record.update(status="failed", evidenceCollectionFailure=str(error))
        q.write_json(receipt, record)
        if record.get("schema") == q.SCHEMA:
            q.project(record, evidence)
        q.seal(evidence)
        return 1
    print(
        json.dumps(
            {
                "finalEvidence": str(evidence),
                "artifactManifestSha256": q.sha256(evidence / "artifact-manifest.json"),
            }
        )
    )
    return code


if __name__ == "__main__":
    sys.exit(main())
