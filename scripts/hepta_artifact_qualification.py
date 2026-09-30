#!/usr/bin/env python3
"""Exact-candidate artifact qualification. Receipts are integrity, not authority.

A consumer must independently authenticate the workflow/run/attempt and supply
its expected source identity. A passing receipt never activates production.
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
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

PACKAGE = "codex-hepta-learning-artifacts"
SOURCE_ROOT = "codex-rs/hepta-learning-artifacts"
MAP = "docs/modules/learning.artifacts/IMPLEMENTATION_MAP.json"
FAMILIES = (
    "owner_host", "owner_service", "publication", "registry", "storage",
    "pinned", "closure_v2", "admission_v3", "dataset_revocation",
    "lifecycle_journal", "selection",
)
GATES = ("closure", "build", "clippy", "format", "inventory", "tests", "process_crash", "daemon_process", "product_process")
MAX_REPORT = 16 * 1024 * 1024
MAX_OUTPUT = 64 * 1024 * 1024
RUNNER_KEYS = ("GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "RUNNER_OS")
SEALED_PATHS = (MAP, "scripts/hepta_artifact_qualification.py",
                "scripts/test_hepta_artifact_qualification.py",
                ".github/workflows/hepta-learning-artifacts-qualification.yml",
                "codex-rs/Cargo.toml", "codex-rs/Cargo.lock",
                "codex-rs/.config/nextest.toml", "justfile")


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def strict_json(data: bytes | str) -> object:
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError(f"duplicate JSON field: {key}")
            result[key] = value
        return result
    def constant(value):
        raise ValueError(f"nonfinite JSON value: {value}")
    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


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
    """Match (nextest binary ID, fully qualified test name), never just a name."""
    if len(xml) > MAX_REPORT or b"\x00" in xml or b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise ValueError("oversize, non-UTF8 or DTD-bearing JUnit")
    expected: Counter[tuple[str, str]] = Counter()
    binaries = inventory["rust-suites"]
    for binary_id, suite in binaries.items():
        if suite["package-name"] != PACKAGE or suite.get("status") != "listed":
            raise ValueError("unexpected package or undiscovered test binary")
        if binary_id != PACKAGE and not binary_id.startswith(PACKAGE + "::"):
            raise ValueError("binary ID belongs to another package")
        for name in suite["testcases"]:
            if not isinstance(name, str) or not name:
                raise ValueError("invalid discovered test name")
            expected[(binary_id, name)] += 1
    if not expected or type(inventory["test-count"]) is not int or sum(expected.values()) != inventory["test-count"]:
        raise ValueError("empty or inconsistent discovered inventory")
    report = ET.fromstring(xml)
    if report.tag not in ("testsuites", "testsuite"):
        raise ValueError("unsupported JUnit root")
    suites = [report] if report.tag == "testsuite" else list(report)
    if any(suite.tag != "testsuite" for suite in suites):
        raise ValueError("unknown JUnit top-level content")
    observed: Counter[tuple[str, str]] = Counter()
    seen = set()
    for suite in suites:
        binary_id = suite.get("name")
        if binary_id not in binaries or binary_id in seen:
            raise ValueError("unknown or duplicate JUnit binary ID")
        seen.add(binary_id)
        cases = []
        for case in suite:
            if case.tag in ("properties", "system-out", "system-err"):
                # Testcases hidden in metadata must not count as execution.
                if any(node.tag == "testcase" for node in case.iter()):
                    raise ValueError("testcase hidden in JUnit metadata")
                continue
            if case.tag != "testcase":
                raise ValueError("unknown or nested JUnit suite content")
            cases.append(case)
            if any(child.tag not in ("system-out", "system-err", "properties") for child in case):
                raise ValueError("failed, skipped, retried or unknown testcase outcome")
            name = case.get("name")
            if not name or case.get("classname") != binary_id:
                raise ValueError("missing test name or substituted testcase binary")
            observed[(binary_id, name)] += 1
        if "tests" in suite.attrib and int(suite.attrib["tests"]) != len(cases):
            raise ValueError("JUnit suite test-count mismatch")
    for node in [report, *suites]:
        for key in ("failures", "errors", "skipped", "disabled"):
            if int(node.get(key, "0")) != 0:
                raise ValueError(f"nonzero JUnit {key}")
    if report.tag == "testsuites" and "tests" in report.attrib and int(report.attrib["tests"]) != sum(observed.values()):
        raise ValueError("JUnit total test-count mismatch")
    if observed != expected:
        raise ValueError("JUnit does not match the complete discovered test identities")
    families = {family: sorted(name for binary, name in observed
                               if binary == PACKAGE and name.split("::", 1)[0] == family)
                for family in FAMILIES}
    if any(not names for names in families.values()):
        raise ValueError("a required artifact regression family did not execute")
    return {"tests": sorted(name for _, name in observed.elements()),
            "testIdentities": [{"binaryId": binary, "testName": name}
                               for binary, name in sorted(observed.elements())],
            "families": families, "passed": sum(observed.values()), "skipped": 0, "retries": 0}


def gate_success(gates: dict) -> bool:
    return set(gates) == set(GATES) and all(
        isinstance(row, dict) and row.get("status") == "completed"
        and type(row.get("exitCode")) is int and row["exitCode"] == 0
        for row in gates.values())


def checkout_identity(root: Path, source: str, base: str, lane: str) -> dict:
    if lane not in ("exact-head", "synthetic-merge"):
        raise ValueError("unknown qualification lane")
    for sha in (source, base):
        if not re.fullmatch(r"[0-9a-f]{40}", sha) or sha == "0" * 40:
            raise ValueError("source and base must be full nonzero commit SHAs")
        if git(root, "rev-parse", f"{sha}^{{commit}}") != sha:
            raise ValueError("commit identity mismatch")
    head, tree = git(root, "rev-parse", "HEAD"), git(root, "rev-parse", "HEAD^{tree}")
    if lane == "exact-head":
        if head != source:
            raise ValueError("checkout is not the requested exact source")
    else:
        if git(root, "show", "-s", "--format=%P", "HEAD").split() != [base, source]:
            raise ValueError("synthetic merge has wrong ordered parents")
        if git(root, "merge-tree", "--write-tree", base, source) != tree:
            raise ValueError("synthetic merge tree differs from the actual base/source merge")
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("source checkout is dirty or contains untracked inputs")
    return {"sourceCommit": source, "baseCommit": base, "testedCommit": head,
            "testedTree": tree, "lane": lane}


def source_binding(root: Path, source: str, base: str, lane: str) -> dict:
    binding = checkout_identity(root, source, base, lane)
    mapping = strict_json((root / MAP).read_bytes())
    if mapping.get("module") != "learning.artifacts" or not mapping.get("operations"):
        raise ValueError("missing artifact implementation map")
    objects = {}
    for entry in mapping["sourceObjects"]:
        path = entry["path"]
        if path in objects:
            raise ValueError("duplicate source object")
        actual = git(root, "rev-parse", f"HEAD:{path}")
        if actual != entry["object"]:
            raise ValueError(f"stale implementation-map object: {path}")
        objects[path] = actual
    if SOURCE_ROOT not in objects or git(root, "cat-file", "-t", objects[SOURCE_ROOT]) != "tree":
        raise ValueError("complete artifact source tree is not sealed")
    for operation in mapping["operations"]:
        if objects.get(operation["sourcePath"]) != operation["sourceBlob"]:
            raise ValueError("operation/source-object seal mismatch")
    for path in SEALED_PATHS:
        objects[path] = git(root, "rev-parse", f"HEAD:{path}")
    return {**binding, "sourceObjects": objects}


def run_gate(root: Path, out: Path, name: str, argv: list[str], timeout: int) -> dict:
    start = time.monotonic()
    stdout, stderr = out / f"{name}.stdout", out / f"{name}.stderr"
    code, status = 127, "not_started"
    with stdout.open("xb") as output, stderr.open("xb") as errors:
        try:
            with subprocess.Popen(argv, cwd=root, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, start_new_session=True) as process:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ, output)
                    selector.register(process.stderr, selectors.EVENT_READ, errors)
                    total, status = 0, "completed"
                    while selector.get_map():
                        if time.monotonic() - start > timeout or total >= MAX_OUTPUT:
                            status = "timed_out" if total < MAX_OUTPUT else "output_limit"
                            os.killpg(process.pid, signal.SIGKILL)
                            break
                        for key, _ in selector.select(timeout=0.2):
                            block = os.read(key.fileobj.fileno(), min(65536, MAX_OUTPUT - total))
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


def traceability(mapping: dict, execution: dict) -> list[dict]:
    identities = execution.get("testIdentities", [])
    trace = []
    for op in mapping["operations"]:
        matched = {}
        for declared in op.get("tests", []):
            path, sep, symbol = declared.partition(".rs::")
            if sep:
                path += ".rs"
                prefix = Path(path).stem.removesuffix("_tests")
                # Module-scoped match: an identically named test in another
                # binary or module is not evidence for this declaration.
                matches = [row for row in identities if row["binaryId"] == PACKAGE
                           and path.startswith(SOURCE_ROOT + "/src/")
                           and row["testName"].startswith(prefix + "::")
                           and row["testName"].endswith("::" + symbol)]
            else:
                matches = [row for row in identities if row["binaryId"] == PACKAGE
                           and row["testName"] == declared]
            matched[declared] = matches
        trace.append({"operation": op["operation"], "symbol": op["nativeSymbol"],
                      "sourcePath": op["sourcePath"], "sourceBlob": op["sourceBlob"],
                      "declaredTests": matched,
                      "mappingStatus": "declared_tests_executed" if matched and all(len(values) == 1 for values in matched.values()) else "unmapped_or_not_executed"})
    return trace


def qualify(root: Path, out: Path, source: str, base: str, lane: str) -> int:
    out.mkdir(parents=True, exist_ok=False)
    # Wrong source/parents/merge tree are never executed. A stale *map* does
    # not suppress independent native gates, but permanently fails this run.
    binding = checkout_identity(root, source, base, lane)
    errors, execution = [], {}
    try:
        binding = source_binding(root, source, base, lane)
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        errors.append(f"source binding: {error}")
    package = ["--manifest-path", "codex-rs/Cargo.toml", "--locked", "-p", PACKAGE]
    junit = root / "codex-rs/target/nextest/local/junit.xml"
    junit.unlink(missing_ok=True)
    commands = {
        "closure": [sys.executable, "scripts/hepta-lane-e-closure.py", "verify"],
        "build": ["cargo", "check", *package, "--all-targets"],
        "clippy": ["cargo", "clippy", *package, "--all-targets", "--", "-D", "warnings"],
        "format": ["cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml", "-p", PACKAGE, "--", "--check"],
        "inventory": ["cargo", "nextest", "list", *package, "--ignore-default-filter", "--message-format", "json"],
        "tests": ["just", "test", "--locked", "-p", PACKAGE, "--ignore-default-filter", "--run-ignored", "all", "--retries", "0", "--no-fail-fast"],
        "process_crash": [
            "cargo", "test", *package,
            "sigkill_every_durable_phase_reconciles_exactly_and_preserves_writer_exclusion",
            "--", "--test-threads=1",
        ],
        "daemon_process": [
            "cargo", "test", *package,
            "--test", "artifactd_process",
            "--", "--test-threads=1",
        ],
        "product_process": [
            "cargo", "test", "--manifest-path", "codex-rs/Cargo.toml", "--locked",
            "-p", "codex-hepta-shadow-qualification",
            "existing_artifact_owner_new_process_predictions_and_revoked_rollback",
            "--", "--test-threads=1",
        ],
    }
    gates = {}
    for name, argv in commands.items():
        gates[name] = run_gate(root, out, name, argv, 900)
        print(f"{name}: {gates[name]['status']} exit={gates[name]['exitCode']}", flush=True)
        if gates[name]["exitCode"] != 0:
            for suffix in ("stdout", "stderr"):
                with (out / f"{name}.{suffix}").open("rb") as stream:
                    stream.seek(max(0, os.fstat(stream.fileno()).st_size - 8192))
                    # JSON escaping prevents log text from injecting workflow commands.
                    print(json.dumps({"gate": name, "stream": suffix,
                                      "failureTail": stream.read().decode("utf-8", "replace")}), flush=True)
    try:
        xml = bounded(junit)
        execution = execution_evidence(strict_json(bounded(out / "inventory.stdout")), xml)
        (out / "junit.xml").write_bytes(xml)
    except (ValueError, OSError, KeyError, TypeError, ET.ParseError) as error:
        errors.append(f"test execution: {error}")
    try:
        if source_binding(root, source, base, lane) != binding:
            errors.append("source changed during qualification")
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        errors.append(f"final source binding: {error}")
    trace = []
    try:
        trace = traceability(strict_json((root / MAP).read_bytes()), execution)
    except (ValueError, OSError, KeyError, TypeError) as error:
        errors.append(f"traceability: {error}")
    ok = gate_success(gates) and not errors
    trace_ok = bool(trace) and all(row["mappingStatus"] == "declared_tests_executed" for row in trace)
    receipt = {"schema": "hepta.learning-artifacts.qualification.v2", **binding,
               "runner": {key: os.environ.get(key) for key in RUNNER_KEYS},
               "gates": gates, "execution": execution, "traceability": trace,
               "errors": errors, "qualified": ok,
               "completion": {"nativeCandidateQualified": ok,
                              "requirementTraceabilityComplete": ok and trace_ok,
                              "moduleComplete": False},
               "claimBoundary": {"productionImplementation": False, "productExecutionProved": False,
                                 "independentAcceptance": False, "activation": False, "release": False}}
    payload = canonical(receipt)
    (out / "qualification.json").write_bytes(payload)
    (out / "qualification.sha256").write_text(hashlib.sha256(payload).hexdigest() + "\n")
    print(json.dumps({"qualified": ok, "completion": receipt["completion"], "errors": errors}, indent=2))
    return 0 if ok else 1


def verify_bundle(out: Path, expected: dict) -> dict:
    """Recheck retained evidence against independently supplied CI identity.

    This proves consistency only. Authentication of expected is the caller's
    responsibility; deriving expected from this same bundle is not verification.
    """
    identity_keys = ("sourceCommit", "baseCommit", "testedCommit", "testedTree", "lane", "runner", "sourceObjects")
    if set(expected) != set(identity_keys) or not expected["sourceObjects"]:
        raise ValueError("complete independent source/run/object identity is required")
    if set(expected["runner"]) != set(RUNNER_KEYS) or any(not value for value in expected["runner"].values()):
        raise ValueError("incomplete expected workflow provenance")
    payload = bounded(out / "qualification.json")
    if hashlib.sha256(payload).hexdigest() != bounded(out / "qualification.sha256").decode().strip():
        raise ValueError("receipt digest mismatch")
    receipt = strict_json(payload)
    if payload != canonical(receipt) or receipt.get("schema") != "hepta.learning-artifacts.qualification.v2":
        raise ValueError("unsupported or noncanonical receipt")
    if any(receipt.get(key) != expected[key] for key in identity_keys):
        raise ValueError("receipt identity differs from independently expected candidate")
    if receipt.get("qualified") is not True or receipt.get("errors") != [] or not gate_success(receipt["gates"]):
        raise ValueError("candidate did not pass every required gate")
    if set(receipt["claimBoundary"]) != {"productionImplementation", "productExecutionProved", "independentAcceptance", "activation", "release"} or any(value is not False for value in receipt["claimBoundary"].values()):
        raise ValueError("receipt attempts to grant external authority")
    for name, row in receipt["gates"].items():
        for suffix in ("stdout", "stderr"):
            if digest(out / f"{name}.{suffix}") != row[suffix + "Sha256"]:
                raise ValueError(f"retained {name}.{suffix} digest mismatch")
    actual = execution_evidence(strict_json(bounded(out / "inventory.stdout")), bounded(out / "junit.xml"))
    if actual != receipt["execution"] or receipt["completion"]["moduleComplete"] is not False:
        raise ValueError("receipt execution or completion drift")
    if receipt["completion"]["nativeCandidateQualified"] is not True:
        raise ValueError("contradictory native qualification state")
    return receipt


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
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"qualification refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
