#!/usr/bin/env python3
"""Exact execution proof for Agentd's bounded authority-effect task owner.

These cases prove repository-controlled ownership semantics only: client
cancellation does not detach work, unrelated Tokio tasks still progress, panics
are joined, shutdown closes admission before constructing work, timeout retains
unjoined tasks, and a cancelled drain cannot abort the owner. No provider
terminal result, target-host acceptance, activation or release is inferred.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import subprocess
import time
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[2]
CODEX_ROOT = ROOT / "codex-rs"

_RUNTIME_SPEC = importlib.util.spec_from_file_location(
    "kernel_authority_runtime_qualification",
    Path(__file__).with_name("runtime_qualification.py"),
)
assert _RUNTIME_SPEC is not None and _RUNTIME_SPEC.loader is not None
RUNTIME = importlib.util.module_from_spec(_RUNTIME_SPEC)
_RUNTIME_SPEC.loader.exec_module(RUNTIME)

_EXECUTION_SPEC = importlib.util.spec_from_file_location(
    "kernel_authority_pilot_execution",
    Path(__file__).with_name("pilot_execution.py"),
)
assert _EXECUTION_SPEC is not None and _EXECUTION_SPEC.loader is not None
EXECUTION = importlib.util.module_from_spec(_EXECUTION_SPEC)
_EXECUTION_SPEC.loader.exec_module(EXECUTION)


class QualificationError(RuntimeError):
    """An expected owner-task case did not execute and pass exactly once."""


class Case(NamedTuple):
    name: str
    test: str


PREFIX = "automation_effect_host::effect_tasks::tests::"
CASES = (
    Case(
        "cancelled-waiter-retains-capacity",
        PREFIX + "cancelled_waiter_does_not_release_inflight_capacity",
    ),
    Case(
        "unrelated-runtime-progress",
        PREFIX + "unrelated_runtime_task_progresses_while_effect_waits",
    ),
    Case(
        "worker-panic-is-joined",
        PREFIX + "worker_panic_is_joined_before_capacity_reuse",
    ),
    Case(
        "shutdown-closes-before-construction",
        PREFIX + "shutdown_rejects_before_constructing_new_effect_work",
    ),
    Case(
        "shutdown-timeout-retains-owner",
        PREFIX + "shutdown_timeout_keeps_unjoined_tasks_owned",
    ),
    Case(
        "cancelled-drain-retains-owner",
        PREFIX + "cancelling_drain_does_not_abort_or_detach_the_effect_owner",
    ),
    Case(
        "submit-close-race-is-fenced",
        PREFIX + "racing_submit_and_close_never_admits_after_the_close_cut",
    ),
)


def command(case: Case) -> tuple[str, ...]:
    raw = (
        "cargo",
        "test",
        "--locked",
        "-p",
        "codex-hepta-agentd",
        case.test,
        "--",
        "--exact",
    )
    return EXECUTION.checked_command(raw)


def run_case(case: Case, output_dir: Path) -> dict[str, Any]:
    log_path = output_dir / "logs" / f"{case.name}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    actual_command = command(case)
    started = time.monotonic_ns()
    with log_path.open("wb") as log:
        completed = subprocess.run(
            list(actual_command),
            cwd=CODEX_ROOT,
            env=RUNTIME.environment(),
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    execution = None
    validation_error = None
    try:
        execution = EXECUTION.validate_output(
            log_path.read_text(encoding="utf-8"),
            (case.test,),
        )
    except (EXECUTION.ExecutionError, UnicodeError, OSError) as error:
        validation_error = str(error)
    return {
        "name": case.name,
        "test": case.test,
        "command": list(actual_command),
        "workingDirectory": "codex-rs",
        "exitCode": completed.returncode,
        "durationMs": max(1, (time.monotonic_ns() - started) // 1_000_000),
        "logPath": log_path.relative_to(output_dir).as_posix(),
        "logBytes": log_path.stat().st_size,
        "logSha256": RUNTIME.sha256_file(log_path),
        "testExecution": execution,
        "validationError": validation_error,
        "passed": completed.returncode == 0 and validation_error is None,
    }


def claims(results: list[dict[str, Any]]) -> dict[str, bool]:
    expected = {case.name: case for case in CASES}
    observed: dict[str, dict[str, Any]] = {}
    for row in results:
        name = row.get("name")
        if not isinstance(name, str) or name not in expected or name in observed:
            raise QualificationError(
                "owner-task case set is missing, unknown or duplicated"
            )
        case = expected[name]
        if type(row.get("passed")) is not bool:
            raise QualificationError(f"{name}: passed must be an exact boolean")
        if row["passed"]:
            if type(row.get("exitCode")) is not int or row["exitCode"] != 0:
                raise QualificationError(f"{name}: success without zero exit")
            if not EXECUTION.validate_receipt(
                row.get("testExecution"),
                (case.test,),
            ):
                raise QualificationError(
                    f"{name}: success without exact executed identity"
                )
        observed[name] = row
    if set(observed) != set(expected):
        raise QualificationError("owner-task case set is incomplete")

    def passed(name: str) -> bool:
        return observed[name]["passed"] is True

    return {
        "boundedAdmissionExercised": passed("cancelled-waiter-retains-capacity")
        and passed("submit-close-race-is-fenced"),
        "clientCancellationOwnershipExercised": passed(
            "cancelled-waiter-retains-capacity"
        )
        and passed("cancelled-drain-retains-owner"),
        "runtimeProgressExercised": passed("unrelated-runtime-progress"),
        "panicJoinExercised": passed("worker-panic-is-joined"),
        "shutdownAdmissionCutExercised": passed(
            "shutdown-closes-before-construction"
        )
        and passed("submit-close-race-is-fenced"),
        "shutdownTimeoutOwnershipExercised": passed(
            "shutdown-timeout-retains-owner"
        )
        and passed("cancelled-drain-retains-owner"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        identity = RUNTIME.load_identity(args.identity.resolve())
        output_dir = args.output_dir.resolve()
        if output_dir.is_relative_to(ROOT) or output_dir.exists():
            raise QualificationError(
                "output directory must be fresh and outside the source checkout"
            )
        output_dir.mkdir(parents=True)
        results = [run_case(case, output_dir) for case in CASES]
        derived = claims(results)
        passed = all(row["passed"] for row in results) and all(derived.values())
        receipt = {
            "schema": "hepta.kernel-authority-owned-effect-runtime.v1",
            "schemaVersion": 1,
            "candidate": identity,
            "scope": "repository-process-pilot",
            **derived,
            "passed": passed,
            "providerTerminalityProved": False,
            "targetHostQualified": False,
            "independentAcceptance": False,
            "activationGranted": False,
            "releaseGranted": False,
            "cases": results,
        }
        RUNTIME.write_json(
            output_dir / "owned-effect-runtime-receipt.json",
            receipt,
        )
        return 0 if passed else 1
    except (
        QualificationError,
        RUNTIME.QualificationError,
        subprocess.CalledProcessError,
        OSError,
    ) as error:
        print(f"kernel.authority owned-effect qualification failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
