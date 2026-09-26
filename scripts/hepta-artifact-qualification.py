#!/usr/bin/env python3
"""Bound exact-source test execution to retained output; never confer activation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

SCHEMA = "hepta.learning-artifacts.execution.v1"
CRATE = "codex-hepta-learning-artifacts"
FILTERS = {
    "owner": "test(owner_host::) | test(owner_service::)",
    "storage": "test(storage_tests::)",
    "lifecycle": "test(lifecycle_journal::)",
    "selection": "test(selection::)",
    "revocation": "test(dataset_revocation_tests::)",
    "pinned": "test(pinned_tests::)",
    "publication": "test(publication::)",
    "all": None,
    "synthetic": None,
}
LANES = ("metadata", "build", "lint", "format", *FILTERS)
BOUND_PATHS = (
    "codex-rs/hepta-learning-artifacts", "codex-rs/hepta-types",
    "codex-rs/Cargo.toml", "codex-rs/Cargo.lock", "justfile",
    "scripts/hepta-artifact-qualification.py",
    "scripts/test_hepta_artifact_qualification.py",
    "qualification/learning-artifacts/nextest.toml",
    ".github/workflows/hepta-learning-artifacts-qualification.yml",
)
MAX_LOG = 64 * 1024 * 1024
MAX_REPORT = 16 * 1024 * 1024


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, timeout=120).decode().strip()


def checked_sha(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value) or value == "0" * 40:
        raise ValueError("a nonzero exact 40-character Git SHA is required")
    return value


def suite_summary(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_REPORT:
        raise ValueError("missing, symlinked or oversized JUnit report")
    data = path.read_bytes()
    data.decode("utf-8")  # Reject alternate encodings before scanning declarations.
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("DTD/entity declarations are forbidden")
    root = ET.fromstring(data)
    cases = list(root.iter("testcase"))
    if not cases:
        raise ValueError("zero executed tests is not qualification")
    identities = [(c.get("classname", ""), c.get("name")) for c in cases]
    if any(not name for _, name in identities) or len(set(identities)) != len(cases):
        raise ValueError("missing or duplicate test identity")
    if any(c.find(tag) is not None for c in cases for tag in ("failure", "error", "skipped", "rerunFailure", "flakyFailure")):
        raise ValueError("failed, skipped or retried tests are not qualification")
    if any(c.get("status", "run") in ("notrun", "disabled", "skipped") for c in cases):
        raise ValueError("unexecuted test case")
    suites = list(root.iter("testsuite"))
    if not suites or sum(int(s.get("tests", "-1")) for s in suites) != len(cases):
        raise ValueError("JUnit count differs from executed test cases")
    for s in suites:
        if any(int(s.get(k, "0")) != 0 for k in ("failures", "errors", "skipped", "disabled")):
            raise ValueError("non-success JUnit suite")
    return {"tests": len(cases), "identitiesDigest": digest(canonical(identities))}


def context(root: Path, source: str, base: str, synthetic: bool) -> dict:
    checked_sha(source)
    source_tree = git(root, "rev-parse", source + "^{tree}")
    tree = source_tree
    if synthetic:
        checked_sha(base)
        tree = git(root, "merge-tree", "--write-tree", base, source).splitlines()[0]
    blobs = {}
    for row in git(root, "ls-tree", "-r", tree, "--", *BOUND_PATHS).splitlines():
        meta, path = row.split("\t", 1)
        mode, kind, sha = meta.split()
        if kind != "blob" or mode == "120000":
            raise ValueError("unsupported source object: " + path)
        blobs[path] = sha
    if not blobs or not any(p.startswith("codex-rs/hepta-learning-artifacts/src/") for p in blobs):
        raise ValueError("artifact source is absent")
    return {"sourceSha": source, "sourceTree": source_tree, "baseSha": base if synthetic else None,
            "testedTree": tree, "sourceBlobs": blobs,
            "runId": os.environ.get("GITHUB_RUN_ID", "local"),
            "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"),
            "repository": os.environ.get("GITHUB_REPOSITORY", "local")}


def execute(argv: list[str], cwd: Path, output: Path, timeout: float = 1200) -> dict:
    started = time.monotonic()
    reason = None
    with output.open("xb") as log:
        process = subprocess.Popen(argv, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=(os.name == "posix"))
        try:
            while process.poll() is None:
                if time.monotonic() - started > timeout or output.stat().st_size > MAX_LOG:
                    reason = "timeout_or_output_limit"
                    break
                time.sleep(0.1)
        finally:
            if process.poll() is None:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            process.wait()
    return {"argv": argv, "exitCode": process.returncode, "reason": reason,
            "elapsedSeconds": round(time.monotonic() - started, 3)}


def commands(lane: str) -> list[list[str]]:
    check = ["cargo", "check", "--locked", "-p", CRATE, "--all-targets"]
    if lane == "metadata":
        return [["python3", "scripts/hepta-lane-e-closure.py", "self-test"],
                ["python3", "scripts/hepta-lane-e-closure.py", "verify"],
                ["python3", "-m", "unittest", "discover", "-s", "scripts", "-p", "test_hepta_artifact_qualification.py", "-v"]]
    if lane == "build":
        return [check]
    if lane == "lint":
        return [check, ["cargo", "clippy", "--locked", "-p", CRATE, "--all-targets", "--", "-D", "warnings"]]
    if lane == "format":
        return [["cargo", "fmt", "-p", CRATE, "--", "--check"]]
    test = ["just", "test", "--locked", "-p", CRATE, "--all-targets", "--profile", "artifact-qualification",
            "--config-file", "../qualification/learning-artifacts/nextest.toml", "--retries", "0"]
    if FILTERS[lane]:
        test += ["-E", FILTERS[lane]]
    return [check, test]


def seal(record: dict) -> dict:
    return {**record, "receiptDigest": digest(canonical(record))}


def run(root: Path, lane: str, source: str, base: str, destination: Path) -> int:
    destination.mkdir(parents=True, exist_ok=False)
    record = {"schema": SCHEMA, "lane": lane, "passed": False, "activation": False,
              "release": False, "job": os.environ.get("GITHUB_JOB", "local"), "commands": [], "outputs": {}, "testSummary": None}
    try:
        record["context"] = context(root, source, base, lane == "synthetic")
        record["testedCommit"] = git(root, "rev-parse", "HEAD")
        if git(root, "rev-parse", "HEAD^{tree}") != record["context"]["testedTree"]:
            raise ValueError("checkout does not match tested tree")
        if lane != "synthetic" and record["testedCommit"] != source:
            raise ValueError("checkout does not match exact source commit")
        if lane == "synthetic" and git(root, "show", "-s", "--format=%P", "HEAD").split() != [base, source]:
            raise ValueError("synthetic merge parents do not match ordered base/source")
        if git(root, "status", "--porcelain", "--untracked-files=no"):
            raise ValueError("tracked source is dirty")
        report = root / "codex-rs/target/nextest/artifact-qualification/junit.xml"
        if lane in FILTERS and report.exists():
            raise ValueError("stale JUnit output exists before execution")
        for index, argv in enumerate(commands(lane)):
            log = destination / f"command-{index}.log"
            result = execute(argv, root if lane == "metadata" else root / "codex-rs", log)
            record["commands"].append(result)
            if result["exitCode"] != 0 or result["reason"]:
                if lane == "metadata":
                    print(log.read_bytes()[:32768].decode(errors="replace"))
                else:
                    break  # Failed compilation must never be followed by tests.
        if lane in FILTERS:
            record["testSummary"] = suite_summary(report)
            (destination / "junit.xml").write_bytes(report.read_bytes())
        if git(root, "status", "--porcelain", "--untracked-files=no"):
            raise ValueError("execution modified tracked source")
        record["passed"] = len(record["commands"]) == len(commands(lane)) and all(
            c["exitCode"] == 0 and c["reason"] is None for c in record["commands"])
    except (OSError, ValueError, subprocess.SubprocessError, ET.ParseError) as error:
        record["error"] = str(error)
    for path in sorted(destination.iterdir()):
        if path.is_file() and path.stat().st_size <= MAX_LOG:
            record["outputs"][path.name] = {"sha256": digest(path.read_bytes()), "bytes": path.stat().st_size}
        else:
            record["passed"] = False
    (destination / "receipt.json").write_bytes(canonical(seal(record)) + b"\n")
    print(json.dumps({"lane": lane, "passed": record["passed"], "error": record.get("error")}))
    return 0 if record["passed"] else 1


def validate(record: dict, lane: str, expected: dict, directory: Path) -> None:
    body = dict(record)
    receipt_digest = body.pop("receiptDigest", None)
    if receipt_digest != digest(canonical(body)):
        raise ValueError("receipt digest mismatch")
    if (body.get("schema") != SCHEMA or body.get("lane") != lane or body.get("context") != expected
            or body.get("passed") is not True or body.get("activation") is not False or body.get("release") is not False):
        raise ValueError("wrong source, run, lane, result or authority")
    checked_sha(body.get("testedCommit", ""))
    if lane != "synthetic" and body["testedCommit"] != expected["sourceSha"]:
        raise ValueError("tested commit is not exact source")
    expected_job = "metadata" if lane == "metadata" else "synthetic" if lane == "synthetic" else "native"
    if body.get("job") != ("local" if expected["runId"] == "local" else expected_job):
        raise ValueError("job identity mismatch")
    observed = body.get("commands", [])
    if [c.get("argv") for c in observed] != commands(lane) or any(
            type(c.get("exitCode")) is not int or c["exitCode"] != 0 or c.get("reason") is not None for c in observed):
        raise ValueError("command inventory or exit status mismatch")
    required = {f"command-{i}.log" for i in range(len(commands(lane)))}
    if lane in FILTERS:
        required.add("junit.xml")
    outputs = body.get("outputs", {})
    if set(outputs) != required:
        raise ValueError("output inventory mismatch")
    for name, item in outputs.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_LOG:
            raise ValueError("missing or invalid output")
        if item != {"sha256": digest(path.read_bytes()), "bytes": path.stat().st_size}:
            raise ValueError("output content mismatch")
    if lane in FILTERS and body.get("testSummary") != suite_summary(directory / "junit.xml"):
        raise ValueError("test summary mismatch")


def collect(root: Path, source: str, base: str, directory: Path, output: Path, needs: dict) -> int:
    results, failures = {}, []
    expected_jobs = {"metadata", "native", "synthetic"}
    if set(needs) != expected_jobs or any(needs[k].get("result") != "success" for k in expected_jobs if k in needs):
        failures.append("a required job is missing, failed, cancelled or skipped")
    paths = list(directory.rglob("receipt.json"))
    for lane in LANES:
        matches = [p for p in paths if p.parent.name == lane]
        try:
            if (len(matches) != 1 or any(p.is_symlink() for p in (matches[0], *matches[0].parents))
                    or matches[0].stat().st_size > MAX_REPORT):
                raise ValueError("missing, duplicate or invalid receipt")
            record = json.loads(matches[0].read_bytes())
            validate(record, lane, context(root, source, base, lane == "synthetic"), matches[0].parent)
            results[lane] = record["receiptDigest"]
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, ET.ParseError) as error:
            failures.append(f"{lane}: {error}")
    if len(paths) != len(LANES):
        failures.append("unexpected receipt inventory")
    summary = {"schema": "hepta.learning-artifacts.qualification.v1", "sourceSha": source,
               "qualified": not failures, "laneReceipts": results, "failures": failures,
               "activation": False, "independentAcceptance": False, "release": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical(seal(summary)) + b"\n")
    print(json.dumps(summary, indent=2))
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "collect"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source", required=True)
    parser.add_argument("--base", default="")
    parser.add_argument("--lane", choices=LANES)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    checked_sha(args.source)
    if args.action == "run":
        if not args.lane:
            parser.error("run requires --lane")
        return run(args.root.resolve(), args.lane, args.source, args.base, args.directory.resolve() / args.lane)
    if not args.output:
        parser.error("collect requires --output")
    return collect(args.root.resolve(), args.source, args.base, args.directory, args.output,
                   json.loads(os.environ.get("JOB_RESULTS", "{}")))


if __name__ == "__main__":
    sys.exit(main())
