#!/usr/bin/env python3
"""Run independent artifact gates; retain failures without granting release authority.

The receipt is integrity-bound, not an independently authenticated acceptance.
Use the hosting workflow/run/attempt and independently verified provenance when
consuming it. Never accept a hash or a caller-supplied success boolean as trust.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

PACKAGE = "codex-hepta-learning-artifacts"
MAP = "docs/modules/learning.artifacts/IMPLEMENTATION_MAP.json"
FAMILIES = (
    "owner_host", "owner_service", "publication", "registry", "storage",
    "pinned", "closure_v2", "admission_v3", "dataset_revocation",
    "lifecycle_journal", "selection",
)
GATES = ("closure", "build", "clippy", "format", "inventory", "tests")
MAX_REPORT = 16 * 1024 * 1024


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def bounded(path: Path) -> bytes:
    with path.open("rb") as stream:
        value = stream.read(MAX_REPORT + 1)
    if len(value) > MAX_REPORT:
        raise ValueError(f"report exceeds {MAX_REPORT} bytes: {path.name}")
    return value


def execution_evidence(inventory: dict, xml: bytes) -> dict:
    """Compare the full discovered test multiset with actual successful cases."""
    if len(xml) > MAX_REPORT or b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise ValueError("oversize or DTD-bearing JUnit")
    expected: Counter[str] = Counter()
    for suite in inventory["rust-suites"].values():
        if suite["package-name"] != PACKAGE or suite.get("status") != "listed":
            raise ValueError("unexpected package or undiscovered test binary")
        expected.update(suite["testcases"].keys())
    if not expected or type(inventory["test-count"]) is not int or sum(expected.values()) != inventory["test-count"]:
        raise ValueError("empty or inconsistent discovered inventory")
    report = ET.fromstring(xml)
    if report.tag not in ("testsuites", "testsuite"):
        raise ValueError("unsupported JUnit root")
    for suite in [report, *report.iter("testsuite")]:
        for key in ("failures", "errors", "skipped", "disabled"):
            if int(suite.get(key, "0")) != 0:
                raise ValueError(f"nonzero JUnit {key}")
    observed: Counter[str] = Counter()
    for case in report.iter("testcase"):
        if any(child.tag not in ("system-out", "system-err", "properties") for child in case):
            raise ValueError("failed, skipped, retried or unknown testcase outcome")
        name = case.get("name")
        if not name:
            raise ValueError("missing testcase name")
        observed[name] += 1
    if observed != expected:
        raise ValueError("JUnit does not match the complete discovered test multiset")
    families = {
        family: sorted(name for name in observed if name.split("::", 1)[0] == family)
        for family in FAMILIES
    }
    if any(not names for names in families.values()):
        raise ValueError("a required artifact regression family did not execute")
    return {"tests": sorted(observed.elements()), "families": families,
            "passed": sum(observed.values()), "skipped": 0, "retries": 0}


def gate_success(gates: dict) -> bool:
    return set(gates) == set(GATES) and all(
        row.get("status") == "completed" and type(row.get("exitCode")) is int
        and row["exitCode"] == 0 for row in gates.values()
    )


def source_binding(root: Path, source: str, base: str, lane: str) -> dict:
    for sha in (source, base):
        if not re.fullmatch(r"[0-9a-f]{40}", sha) or sha == "0" * 40:
            raise ValueError("source and base must be full nonzero commit SHAs")
        if git(root, "rev-parse", f"{sha}^{{commit}}") != sha:
            raise ValueError("commit identity mismatch")
    head = git(root, "rev-parse", "HEAD")
    if lane == "exact-head":
        if head != source:
            raise ValueError("checkout is not the requested exact source")
    elif git(root, "show", "-s", "--format=%P", "HEAD").split() != [base, source]:
        raise ValueError("synthetic merge has wrong ordered parents")
    if git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("tracked source is dirty")
    mapping = json.loads((root / MAP).read_text())
    objects = {}
    for entry in mapping["sourceObjects"]:
        path = entry["path"]
        if path in objects:
            raise ValueError("duplicate source object")
        actual = git(root, "rev-parse", f"HEAD:{path}")
        if actual != entry["object"]:
            raise ValueError(f"stale implementation-map object: {path}")
        objects[path] = actual
    for operation in mapping["operations"]:
        if objects.get(operation["sourcePath"]) != operation["sourceBlob"]:
            raise ValueError("operation/source-object seal mismatch")
    for path in (MAP, "scripts/hepta_artifact_qualification.py",
                 ".github/workflows/hepta-learning-artifacts-qualification.yml",
                 "codex-rs/Cargo.lock", "codex-rs/.config/nextest.toml", "justfile"):
        objects[path] = git(root, "rev-parse", f"HEAD:{path}")
    return {"sourceCommit": source, "baseCommit": base, "testedCommit": head,
            "testedTree": git(root, "rev-parse", "HEAD^{tree}"), "lane": lane,
            "sourceObjects": objects}


def run_gate(root: Path, out: Path, name: str, argv: list[str], timeout: int) -> dict:
    start = time.monotonic()
    # stdout and stderr are separate: inventory stdout is machine-readable JSON.
    stdout, stderr = out / f"{name}.stdout", out / f"{name}.stderr"
    code, status = 127, "not_started"
    with stdout.open("xb") as output, stderr.open("xb") as errors:
        try:
            with subprocess.Popen(argv, cwd=root, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, start_new_session=True) as process:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ, output)
                    selector.register(process.stderr, selectors.EVENT_READ, errors)
                    total = 0
                    status = "completed"
                    while selector.get_map():
                        if time.monotonic() - start > timeout or total >= 64 * 1024 * 1024:
                            status = "timed_out" if total < 64 * 1024 * 1024 else "output_limit"
                            os.killpg(process.pid, signal.SIGKILL)
                            break
                        for key, _ in selector.select(timeout=0.2):
                            block = os.read(key.fileobj.fileno(), 65536)
                            if not block:
                                selector.unregister(key.fileobj)
                            else:
                                key.data.write(block)
                                total += len(block)
                    try:
                        code = process.wait(timeout=max(0.1, timeout - (time.monotonic() - start)))
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                        code, status = 124, "timed_out"
                    if status == "timed_out":
                        code = 124
                    elif status == "output_limit":
                        code = 125
        except OSError as error:
            errors.write(str(error).encode())
            code, status = 127, "not_started"
    return {"argv": argv, "status": status, "exitCode": code,
            "seconds": round(time.monotonic() - start, 3),
            "stdoutSha256": digest(stdout), "stderrSha256": digest(stderr)}


def qualify(root: Path, out: Path, source: str, base: str, lane: str) -> int:
    # No reuse of an earlier receipt, log, test inventory or JUnit result.
    out.mkdir(parents=True, exist_ok=False)
    binding = source_binding(root, source, base, lane)
    package = ["--manifest-path", "codex-rs/Cargo.toml", "--locked", "-p", PACKAGE]
    junit = root / "codex-rs/target/nextest/local/junit.xml"
    junit.unlink(missing_ok=True)
    commands = {
        "closure": [sys.executable, "scripts/hepta-lane-e-closure.py", "verify"],
        "build": ["cargo", "check", *package, "--all-targets"],
        "clippy": ["cargo", "clippy", *package, "--all-targets", "--", "-D", "warnings"],
        "format": ["cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml", "-p", PACKAGE, "--", "--check"],
        "inventory": ["cargo", "nextest", "list", *package, "--message-format", "json"],
        "tests": ["just", "test", "--locked", "-p", PACKAGE, "--run-ignored", "all", "--retries", "0"],
    }
    gates = {}
    for name, argv in commands.items():
        gates[name] = run_gate(root, out, name, argv, 900)
        print(f"{name}: {gates[name]['status']} exit={gates[name]['exitCode']}", flush=True)
    errors, execution = [], {}
    try:
        execution = execution_evidence(json.loads(bounded(out / "inventory.stdout")), bounded(junit))
        shutil.copyfile(junit, out / "junit.xml")
    except (ValueError, OSError, KeyError, TypeError, ET.ParseError) as error:
        errors.append(str(error))
    try:
        if source_binding(root, source, base, lane) != binding:
            errors.append("source changed during qualification")
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        errors.append(str(error))
    mapping = json.loads((root / MAP).read_text())
    trace = []
    names = execution.get("tests", [])
    for op in mapping["operations"]:
        declared = op.get("tests", [])
        matched = {test: [name for name in names if name == test or name.endswith("::" + test.rsplit("::", 1)[-1])] for test in declared}
        trace.append({"operation": op["operation"], "symbol": op["nativeSymbol"],
                      "sourcePath": op["sourcePath"], "sourceBlob": op["sourceBlob"],
                      "declaredTests": matched,
                      "mappingStatus": "declared_tests_executed" if matched and all(len(values) == 1 for values in matched.values()) else "unmapped_or_not_executed"})
    ok = gate_success(gates) and not errors
    receipt = {"schema": "hepta.learning-artifacts.qualification.v1", **binding,
               "runner": {key: os.environ.get(key) for key in ("GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "RUNNER_OS")},
               "gates": gates, "execution": execution, "traceability": trace,
               "errors": errors, "qualified": ok,
               "claimBoundary": {"productionImplementation": False, "productExecutionProved": False,
                                 "independentAcceptance": False, "activation": False, "release": False}}
    payload = canonical(receipt)
    (out / "qualification.json").write_bytes(payload)
    (out / "qualification.sha256").write_text(hashlib.sha256(payload).hexdigest() + "\n")
    print(json.dumps({"qualified": ok, "errors": errors}, indent=2))
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--lane", required=True, choices=("exact-head", "synthetic-merge"))
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    os.environ["CARGO_TARGET_DIR"] = str(root / "codex-rs/target")
    try:
        return qualify(root, args.out.resolve(), args.source, args.base, args.lane)
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        print(f"qualification refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
