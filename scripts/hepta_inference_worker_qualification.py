#!/usr/bin/env python3
"""Run exact-tree inference qualification; never convert absent evidence to success.

CURRENT_STATUS.json is an execution artifact, not a checked-in self-attestation.
The source tree and all codex-rs blobs bind the run; sourceBase provenance is not
rewritten. Hardware, provider and independent acceptance remain separate gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import threading
import time
import xml.etree.ElementTree as ET

PACKAGES = (
    "codex-hepta-infer-core",
    "codex-hepta-infer-worker-host",
    "codex-hepta-agentd",
)
LOG_LIMIT = 32 * 1024 * 1024
JUNIT_LIMIT = 16 * 1024 * 1024


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def identify(root: Path) -> dict:
    entries = subprocess.check_output(
        ["git", "-C", str(root), "ls-tree", "-rz", "HEAD"],
    ).decode().split("\0")
    blobs = {}
    for entry in filter(None, entries):
        metadata, path = entry.split("\t", 1)
        mode, kind, sha = metadata.split()
        if kind == "blob" and path.startswith(("codex-rs/", ".github/", "scripts/", "docs/modules/inference.worker/")):
            blobs[path] = sha
    return {
        "tested_head": git(root, "rev-parse", "HEAD"),
        "tested_tree": git(root, "rev-parse", "HEAD^{tree}"),
        "source_blob_digests": blobs,
    }


def candidate_error(root: Path, source: str, tested: str, base: str, lane: str) -> str | None:
    if git(root, "rev-parse", "HEAD") != tested:
        return "checkout does not match tested SHA"
    if git(root, "status", "--porcelain", "--untracked-files=no"):
        return "tracked checkout is dirty before execution"
    if lane == "source-head":
        return None if tested == source else "source-head is not the exact source commit"
    if lane != "merge-candidate" or not base:
        return "merge-candidate requires a fixed base SHA"
    expected_tree = git(root, "merge-tree", "--write-tree", base, source).splitlines()[0]
    if expected_tree != git(root, "rev-parse", "HEAD^{tree}"):
        return "merge candidate tree does not equal the deterministic base/source merge"
    return None


def junit_result(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size > JUNIT_LIMIT:
        return {"result": "missing_or_oversized", "tests": 0}
    try:
        data = path.read_bytes()
        if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
            raise ValueError("XML declarations are not allowed")
        root = ET.fromstring(data)
        if root.tag not in {"testsuite", "testsuites"}:
            raise ValueError("not a JUnit test suite")
        cases = list(root.iter("testcase"))
        failed = sum(c.find("failure") is not None or c.find("error") is not None for c in cases)
        skipped = sum(c.find("skipped") is not None for c in cases)
        # Suite-level errors (including setup failures) may have no testcase.
        suite_errors = sum(int(s.get("errors", "0")) for s in root.iter("testsuite"))
        suite_failures = sum(int(s.get("failures", "0")) for s in root.iter("testsuite"))
        result = "passed" if cases and not (failed or skipped or suite_errors or suite_failures) else "not_passed"
        return {"result": result, "tests": len(cases), "failed": failed,
                "skipped": skipped, "suite_errors": suite_errors,
                "suite_failures": suite_failures, "sha256": hashlib.sha256(data).hexdigest()}
    except (ET.ParseError, ValueError, OSError) as error:
        return {"result": "invalid", "tests": 0, "error": str(error)}


def run_command(command: list[str], cwd: Path, log: Path, timeout: int, env: dict) -> dict:
    started = time.monotonic()
    tail = bytearray()
    written = 0
    dropped = 0
    reader_errors = []
    try:
        with log.open("xb") as output:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            def drain() -> None:
                nonlocal written, dropped
                assert process.stdout is not None
                try:
                    while chunk := process.stdout.read(8192):
                        keep = min(len(chunk), max(0, LOG_LIMIT - written))
                        output.write(chunk[:keep])
                        written += keep
                        dropped += len(chunk) - keep
                        tail.extend(chunk)
                        if len(tail) > 8000:
                            del tail[:-8000]
                except (OSError, ValueError) as error:
                    reader_errors.append(str(error))
            reader = threading.Thread(target=drain, daemon=True)
            reader.start()
            timed_out = False
            try:
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                returncode = process.wait()
            reader.join(timeout=5)
            incomplete = reader.is_alive()
            if incomplete:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                reader.join(timeout=5)
            if not reader.is_alive() and process.stdout is not None:
                process.stdout.close()
            result = "timed_out" if timed_out else "passed" if returncode == 0 and not incomplete and not reader_errors else "failed"
            return {"result": result, "returncode": returncode,
                    "seconds": round(time.monotonic() - started, 3),
                    "command": command, "log": log.name, "log_bytes_dropped": dropped,
                    "log_errors": reader_errors,
                    "diagnostic_tail": tail.decode("utf-8", errors="replace") if result != "passed" else ""}
    except (OSError, subprocess.SubprocessError) as error:
        return {"result": "execution_error", "command": command, "error": str(error)}


def save(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(value, output, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def stage_commands(package: str, experimental: bool = False) -> list[tuple[str, list[str]]]:
    features = ["--features", "experimental-local-worker"] if experimental else []
    return [
        ("lib", ["cargo", "nextest", "run", "--locked", "--profile", "default", "--no-fail-fast", "--retries", "0", "--lib", "-p", package, *features, "--test-threads", "1"]),
        ("binary", ["cargo", "test", "--locked", "-p", package, *features, "--bins"]),
        ("all_targets", ["cargo", "check", "--locked", "-p", package, *features, "--all-targets"]),
        ("clippy", ["cargo", "clippy", "--locked", "-p", package, *features, "--all-targets", "--no-deps", "--", "-D", "warnings"]),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", choices=PACKAGES, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--tested-sha", required=True)
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--lane", choices=("source-head", "merge-candidate"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    args = parser.parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    if output == root or root in output.parents:
        parser.error("evidence output must be outside the source checkout")
    if not 1 <= args.timeout_seconds <= 3600:
        parser.error("timeout must be 1..3600 seconds")
    output.mkdir(parents=True, exist_ok=False)
    status_path = output / "CURRENT_STATUS.json"
    identity = identify(root)
    run_id = os.environ.get("GITHUB_RUN_ID")
    status = {
        "schema": "hepta.inference-worker.current-status.v1",
        **identity, "source_head": args.source_sha,
        "source_tree": git(root, "rev-parse", f"{args.source_sha}^{{tree}}"),
        "base_head": args.base_sha or None, "lane": args.lane, "package": args.package,
        "platform": platform.system(), "run_id": run_id,
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "last_exact_head_run": run_id if args.lane == "source-head" else None,
        "last_merge_candidate_run": run_id if args.lane == "merge-candidate" else None,
        "linux_result": "in_progress" if platform.system() == "Linux" else "not_executed",
        "macos_result": "in_progress" if platform.system() == "Darwin" else "not_executed",
        "real_hardware_result": "not_executed", "real_provider_result": "not_executed",
        "composition_result": "not_executed", "independent_acceptance_result": "not_executed",
        "activation": False, "release": False, "stages": {}, "result": "in_progress",
    }
    save(status_path, status)
    try:
        error = candidate_error(root, args.source_sha, args.tested_sha, args.base_sha, args.lane)
        if error:
            raise ValueError(error)
        stages = [
            ("derived-projections", ["python3", "scripts/hepta-module-docs.py", "refresh-derived", "--check"], root),
            ("registry", ["python3", "scripts/hepta_module_registry.py", "--strict"], root),
            ("implementation-maps", ["python3", "scripts/hepta-implementation-maps.py", "verify"], root),
        ] if args.package == PACKAGES[0] else []
        workspace = root / "codex-rs"
        for package in [args.package]:
            stages.append((f"{package}.format", ["cargo", "fmt", "--package", package, "--", "--check"], workspace))
            for label, command in stage_commands(package):
                stages.append((f"{package}.{label}", command, workspace))
        if args.package == PACKAGES[1]:
            for label, command in stage_commands(PACKAGES[1], experimental=True):
                stages.append((f"{PACKAGES[1]}.experimental.{label}", command, workspace))
        env = dict(os.environ, CARGO_TARGET_DIR=str(workspace / "target"))
        junit = workspace / "target/nextest/default/junit.xml"
        for name, command, cwd in stages:
            # Clear the known output before every nextest invocation. A stale
            # report from another package, feature set or run cannot pass.
            is_library = name.endswith(".lib")
            if is_library:
                junit.unlink(missing_ok=True)
            status["stages"][name] = {"result": "in_progress", "command": command}
            save(status_path, status)
            result = run_command(command, cwd, output / f"{name}.log", args.timeout_seconds, env)
            if is_library:
                result["junit"] = junit_result(junit)
                if junit.is_file() and junit.stat().st_size <= JUNIT_LIMIT:
                    (output / f"{name}.junit.xml").write_bytes(junit.read_bytes())
                if result["junit"]["result"] != "passed":
                    result["result"] = "failed"
            if name.endswith(".binary"):
                result["proof_scope"] = "cargo_binary_targets_only_not_product_execution"
            status["stages"][name] = result
            save(status_path, status)
            print(f"{name}: {result['result']}", flush=True)
        status["clean_tree"] = identify(root) == identity and not git(root, "status", "--porcelain", "--untracked-files=no")
        status["result"] = "passed" if status["clean_tree"] and all(s["result"] == "passed" for s in status["stages"].values()) else "failed"
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        status["result"] = "failed"
        status["execution_error"] = str(error)
    platform_key = "linux_result" if platform.system() == "Linux" else "macos_result" if platform.system() == "Darwin" else None
    if platform_key:
        status[platform_key] = status["result"]
    for suffix, key in ((".lib", "lib_test_result"), (".binary", "binary_test_result"), (".clippy", "clippy_result")):
        status[key] = {name: value["result"] for name, value in status["stages"].items() if name.endswith(suffix)}
    save(status_path, status)
    return 0 if status["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
