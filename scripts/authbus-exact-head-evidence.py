#!/usr/bin/env python3
"""Execute AuthBus qualification and retain fail-closed exact-candidate receipts.

A receipt is an assertion from this workflow, NOT independent authorization.
Consumers must also verify the GitHub run/attempt, both candidate jobs and the
independent production review. No receipt produced here enables activation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    'inventory',
    'inventory_tests',
    'implementation_map',
    'operations_contract',
    'receipt_tests',
    'format',
    'authbus',
    'doc_tests',
    'qualification',
    'evidence',
    'agentd',
    'bao',
    'workspace',
    'clippy',
    'clean_tree',
)
TEST_STEPS = frozenset(("authbus", "doc_tests", "qualification", "evidence", "agentd", "bao", "workspace"))
SHA = re.compile(r"[0-9a-f]{40}\Z")


def output(*command: str) -> str:
    return subprocess.check_output(command, cwd=ROOT, text=True).strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def aggregate(entries: list[dict[str, str]]) -> str:
    return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def clean_tree() -> bool:
    # Include untracked source and submodule drift. Build/output files live
    # outside the repository, never behind a broad ignore/exclusion here.
    return not output("git", "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none")


def gates_pass(rows: list[dict[str, Any]], candidate: str) -> bool:
    if not isinstance(candidate, str) or SHA.fullmatch(candidate) is None:
        return False
    if (not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows)
            or [row.get("id") for row in rows] != list(REQUIRED)):
        return False
    for row in rows:
        elapsed = row.get("elapsed_seconds")
        code = row.get("exit_code")
        if (row.get("state") != "success" or type(code) is not int or code != 0
                or row.get("candidate") != candidate
                or not isinstance(row.get("log_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", row["log_sha256"]) is None
                or type(elapsed) not in (float, int)
                or not math.isfinite(elapsed) or elapsed < 0):
            return False
        if row["id"] in TEST_STEPS:
            passed = row.get("passed_tests")
            if type(passed) is not int or passed <= 0:
                return False
    return True


def commands() -> dict[str, list[str]]:
    cargo = ["cargo", "test", "--locked", "--manifest-path", "codex-rs/Cargo.toml",
             "--message-format=json-render-diagnostics"]
    packages = {
        "authbus": "codex-hepta-authbus",
        "qualification": "codex-hepta-authbus-p1-3-qualification",
        "evidence": "codex-hepta-evidence",
        "agentd": "codex-hepta-agentd",
        "bao": "codex-hepta-bao-adapter",
    }
    result = {'inventory': [sys.executable, 'scripts/check-authbus-closed-world.py', '--check'], 'receipt_tests': [sys.executable, 'scripts/test-authbus-exact-head-evidence.py'], 'inventory_tests': [sys.executable, 'scripts/test-authbus-closed-world.py'], 'doc_tests': cargo + ['-p', 'codex-hepta-authbus', '--doc'], 'format': ['cargo', 'fmt', '--all', '--manifest-path', 'codex-rs/Cargo.toml', '--', '--check'], 'workspace': cargo + ['--workspace', '--all-targets', '--no-fail-fast'], 'clippy': ['cargo', 'clippy', '--locked', '--manifest-path', 'codex-rs/Cargo.toml', '--workspace', '--all-targets', '--', '-D', 'warnings'], 'clean_tree': [sys.executable, '-c', "import subprocess; s=subprocess.check_output(['git','status','--porcelain=v1','--untracked-files=all','--ignore-submodules=none'],text=True); print(s,end=''); raise SystemExit(bool(s))"], 'implementation_map': [sys.executable, 'scripts/generate-authbus-implementation-map.py', '--check'], 'operations_contract': [sys.executable, 'scripts/test-authbus-operations.py']}
    for name, package in packages.items():
        result[name] = cargo + ["-p", package, "--all-targets"]
    return result


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def run_step(row: dict[str, Any], command: list[str], directory: Path,
             environment: dict[str, str], timeout: float) -> None:
    log = directory / (row["id"] + ".log")
    state_file = directory / (row["id"] + ".json")
    row.update(state="running", command=command, started_at_unix=time.time())
    atomic_json(state_file, row)
    start = time.monotonic()
    process = None
    try:
        with log.open("wb") as stream:
            process = subprocess.Popen(command, cwd=ROOT, env=environment,
                                       stdout=stream, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            try:
                code = process.wait(timeout=timeout)
                row.update(exit_code=code, state="success" if code == 0 else "failure")
            except subprocess.TimeoutExpired:
                stop_process(process)
                row.update(exit_code=process.returncode, state="timeout")
    except (KeyboardInterrupt, InterruptedError):
        if process is not None:
            stop_process(process)
        row.update(exit_code=None, state="interrupted")
        raise
    except OSError as error:
        row.update(exit_code=None, state="failure", error=str(error))
    finally:
        row["elapsed_seconds"] = time.monotonic() - start
        row["finished_at_unix"] = time.time()
        if log.exists():
            row["log_sha256"] = sha256(log)
            if row["id"] in TEST_STEPS:
                text = log.read_text(encoding="utf-8", errors="replace")
                row["passed_tests"] = sum(int(value) for value in re.findall(
                    r"test result: ok\.\s+(\d+) passed;", text))
                if row["state"] == "success" and row["passed_tests"] == 0:
                    row["state"] = "failure"
                    row["error"] = "no executed passing tests in the test command output"
        atomic_json(state_file, row)
        print(f"{row['id']}: {row['state']} (exit={row.get('exit_code')})", flush=True)
        if row['state'] != 'success' and log.exists():
            print("\n".join(log.read_text(errors="replace").splitlines()[-80:]), flush=True)


def executable_evidence(directory: Path, target: Path) -> list[dict[str, str]]:
    found: set[Path] = set()
    for log in sorted(directory.glob("*.log")):
        with log.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if not line.lstrip().startswith("{"):
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(message, dict) or message.get("reason") != "compiler-artifact":
                    continue
                executable = message.get("executable")
                if not executable or not message.get("profile", {}).get("test", False):
                    continue
                raw = Path(executable)
                path = raw.resolve()
                if raw.is_symlink() or not path.is_relative_to(target.resolve()) or not path.is_file():
                    raise ValueError("test executable is missing or outside the fresh candidate target")
                found.add(path)
    return [{"path": path.relative_to(target).as_posix(), "sha256": sha256(path)}
            for path in sorted(found)]


def check_identity(mode: str, source: str, base: str) -> tuple[str, str]:
    if SHA.fullmatch(source) is None or SHA.fullmatch(base) is None:
        raise ValueError("source/base must be exact full commit SHAs")
    candidate = output("git", "rev-parse", "HEAD")
    if mode == "source-head" and candidate != source:
        raise ValueError("checkout does not equal the expected source head")
    if mode == "synthetic-merge":
        parents = output("git", "rev-list", "--parents", "-n", "1", "HEAD").split()[1:]
        if parents != [base, source]:
            raise ValueError("synthetic merge parents do not match the fixed base and source")
    if not clean_tree():
        raise ValueError("candidate worktree is not clean")
    return candidate, output("git", "rev-parse", "HEAD^{tree}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("source-head", "synthetic-merge"))
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--step-timeout", type=float, default=1800)
    args = parser.parse_args()
    if not math.isfinite(args.step_timeout) or args.step_timeout <= 0:
        parser.error("step timeout must be positive")
    destination = args.output.resolve()
    if destination.is_relative_to(ROOT):
        parser.error("evidence must be written outside the source checkout")
    destination.parent.mkdir(parents=True, exist_ok=True)
    steps = destination.parent / "steps"
    steps.mkdir(exist_ok=False)  # Do not merge receipts or logs across attempts.
    target = Path(tempfile.mkdtemp(prefix="authbus-candidate-target-", dir=os.environ.get("RUNNER_TEMP")))
    environment = dict(os.environ, CARGO_TARGET_DIR=str(target), CARGO_TERM_COLOR="never")
    receipt: dict[str, Any] = {
        "schema": "hepta.authbus.exact-head-evidence.v2",
        "mode": args.mode, "source_head": args.source_head, "base_sha": args.base_sha,
        "qualification_status": "incomplete", "activation": False,
        "workflow": {key: os.environ.get(key) for key in (
            "GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB",
            "GITHUB_EVENT_NAME", "GITHUB_SHA")},
        "steps": [], "build_artifacts": [],
    }
    atomic_json(destination, receipt)
    try:
        candidate, tree = check_identity(args.mode, args.source_head, args.base_sha)
        receipt["candidate"] = {"commit": candidate, "tree": tree}
        receipt["steps"] = [{"id": name, "candidate": candidate, "state": "not_run"}
                            for name in REQUIRED]
        if sys.platform != "linux":
            raise ValueError("full AuthBus qualification requires native Linux; portable checks are supplemental")
        receipt["toolchain"] = {"rustc": output("rustc", "--version", "--verbose"),
                                "cargo": output("cargo", "--version")}
        receipt["cargo_lock_sha256"] = sha256(ROOT / "codex-rs/Cargo.lock")
        migrations = [{"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)}
                      for path in sorted((ROOT / "codex-rs/hepta-authbus/migrations").glob("*.sql"))]
        if not migrations:
            raise ValueError("authority migration inventory is empty")
        receipt["migrations"] = migrations
        receipt["schema_sha256"] = aggregate(migrations)
        plan = commands()
        for row in receipt["steps"]:
            print(f"AuthBus {args.mode}: executing {row['id']}", flush=True)
            run_step(row, plan[row["id"]], steps, environment, args.step_timeout)
            atomic_json(destination, receipt)
        receipt["build_artifacts"] = executable_evidence(steps, target)
        receipt["build_artifacts_sha256"] = aggregate(receipt["build_artifacts"])
        receipt["clean_tree"] = clean_tree()
        ci_identity = (os.environ.get("GITHUB_REPOSITORY") == "TrillionniumFoundation/hepta-private-ci"
                       and str(os.environ.get("GITHUB_RUN_ID", "")).isdigit()
                       and str(os.environ.get("GITHUB_RUN_ATTEMPT", "")).isdigit())
        passed = (gates_pass(receipt["steps"], candidate) and receipt["clean_tree"]
                  and output("git", "rev-parse", "HEAD") == candidate
                  and bool(receipt["build_artifacts"]) and ci_identity)
        receipt["qualification_status"] = "passed" if passed else "incomplete"
    except (ValueError, OSError, subprocess.SubprocessError, KeyboardInterrupt, InterruptedError) as error:
        receipt["error"] = str(error) or type(error).__name__
        receipt["qualification_status"] = "incomplete"
    finally:
        receipt["finished_at_unix"] = time.time()
        atomic_json(destination, receipt)
    return 0 if receipt["qualification_status"] == "passed" else 1


if __name__ == "__main__":
    def interrupted(signum: int, _frame: Any) -> None:
        raise InterruptedError(f"qualification interrupted by signal {signum}")
    signal.signal(signal.SIGTERM, interrupted)
    raise SystemExit(main())
