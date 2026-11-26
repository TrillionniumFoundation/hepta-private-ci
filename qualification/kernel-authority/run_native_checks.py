#!/usr/bin/env python3
"""Read-only exact-candidate native checks with retained per-command evidence.

A partially executed plan, zero tests, missing tools, timeouts, source mutation,
or any failed command cannot produce a passing receipt. This is repository
qualification, never production trust, deployment, or independent acceptance.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location("authority_runtime_checks", Path(__file__).with_name("runtime_qualification.py"))
assert SPEC is not None and SPEC.loader is not None
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)
ROOT = RUNTIME.ROOT
PACKAGES = (
    "codex-hepta-contracts", "codex-hepta-fleet", "codex-hepta-agentd",
    "codex-hepta-automation", "codex-hepta-prompt-registry", "codex-hepta-bao-adapter",
)


def command_plan():
    package_args = [argument for package in PACKAGES for argument in ("-p", package)]
    return [
        ("rust-toolchain", "codex-rs", ["rustc", "-Vv"]),
        ("cargo-version", "codex-rs", ["cargo", "-V"]),
        ("rust-format", "codex-rs", ["cargo", "fmt", "--check", *package_args]),
        ("all-target-check", "codex-rs", ["cargo", "check", "--locked", "--all-targets", *package_args]),
        ("native-package-tests", "codex-rs", ["just", "test", "--locked", *package_args, "--retries", "0", "--no-tests=fail"]),
        ("strict-clippy", "codex-rs", ["cargo", "clippy", "--locked", "--all-targets", *package_args, "--", "-D", "warnings"]),
        ("qualification-regressions", ".", ["python3", "-B", "-m", "unittest", "discover", "-s", "qualification/kernel-authority", "-p", "test_*.py", "-v"]),
        ("b4-authority-api", ".", ["python3", "-B", "-m", "unittest", "discover", "-s", "qa/b4-no-bypass", "-p", "test_kernel_authority*.py", "-v"]),
        ("closed-caller-proof", ".", ["python3", "-B", "scripts/verify_hepta_callers.py"]),
        ("status-projections", ".", ["python3", "-B", "scripts/kernel_authority_status.py", "check"]),
        ("source-whitespace", ".", ["git", "diff", "--check"]),
    ]


def run_step(name, cwd, command, output, timeout):
    log = output / "logs" / f"{name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic_ns()
    error = None
    env = RUNTIME.environment()
    env.update(PYTHONDONTWRITEBYTECODE="1", RUST_MIN_STACK="8388608")
    with log.open("wb") as stream:
        try:
            result = subprocess.run(command, cwd=ROOT / cwd, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=timeout, check=False)
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            exit_code, error = 124, "command exceeded its explicit time limit"
        except OSError as caught:
            exit_code, error = 127, f"command could not be started: {caught}"
        if error:
            stream.write((error + "\n").encode())
    return {
        "name": name, "workingDirectory": cwd, "command": command,
        "exitCode": exit_code, "durationMs": max(1, (time.monotonic_ns() - started) // 1_000_000),
        "logPath": log.relative_to(output).as_posix(), "logBytes": log.stat().st_size,
        "logSha256": RUNTIME.sha256_file(log), "executionError": error,
        "passed": exit_code == 0 and error is None,
    }


def complete_pass(plan, results, unchanged):
    if unchanged is not True or len(plan) != len(results):
        return False
    return all(
        row.get("name") == name and row.get("command") == command
        and row.get("workingDirectory") == cwd and row.get("passed") is True
        and type(row.get("exitCode")) is int and row["exitCode"] == 0
        and row.get("executionError") is None
        for (name, cwd, command), row in zip(plan, results)
    )


def host_identity():
    return {
        "system": platform.system(), "release": platform.release(),
        "machine": platform.machine(), "python": platform.python_version(),
        **{name: os.environ.get(name, "unavailable") for name in (
            "GITHUB_WORKFLOW_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT",
            "RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion",
        )},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--command-timeout-seconds", type=int, default=2700)
    args = parser.parse_args()
    if not 1 <= args.command_timeout_seconds <= 7200:
        parser.error("command timeout must be 1..=7200 seconds")
    identity = RUNTIME.load_identity(args.identity.resolve())
    output = args.output_dir.resolve()
    if output.is_relative_to(ROOT) or output.exists():
        parser.error("output-dir must be fresh and outside the source checkout")
    output.mkdir(parents=True)
    plan = command_plan()
    receipt = {
        "schema": "hepta.kernel-authority-native-checks.v1", "candidate": identity,
        "host": host_identity(), "plannedCommands": [name for name, _, _ in plan],
        "commands": [], "executionComplete": False, "sourceUnchanged": False,
        "passed": False, "qualificationOnly": True, "productionTrustProved": False,
        "independentAcceptance": False, "activationGranted": False, "releaseGranted": False,
    }
    path = output / "native-checks-receipt.json"
    RUNTIME.write_json(path, receipt)
    for name, cwd, command in plan:
        receipt["commands"].append(run_step(name, cwd, command, output, args.command_timeout_seconds))
        RUNTIME.write_json(path, receipt)
    try:
        unchanged = RUNTIME.load_identity(args.identity.resolve()) == identity
        identity_error = None
    except (RUNTIME.QualificationError, subprocess.CalledProcessError, OSError) as error:
        unchanged, identity_error = False, str(error)
    receipt["executionComplete"] = True
    receipt["sourceUnchanged"] = unchanged
    receipt["identityError"] = identity_error
    receipt["passed"] = complete_pass(plan, receipt["commands"], unchanged)
    RUNTIME.write_json(path, receipt)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
