#!/usr/bin/env python3
"""Run and validate the exact two-process Agentd authority recovery product test.

This receipt proves only one exact repository candidate test execution. It never
manufactures deployment trust, target-host qualification, independent
acceptance, activation, promotion, or release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CODEX_ROOT = ROOT / "codex-rs"
TEST_NAME = (
    "two_agentd_processes_preserve_pending_nonce_attempt_witness_and_terminal_receipt"
)
IDENTITY_FIELDS = {
    "schema",
    "mode",
    "sourceCommit",
    "baseCommit",
    "candidateCommit",
    "candidateTree",
    "activationGranted",
    "releaseGranted",
}
SHA1 = re.compile(r"[0-9a-f]{40}")
RESULT = re.compile(r"^test ([A-Za-z_][A-Za-z0-9_:]*) \.\.\. (ok|FAILED|ignored(?:,.*)?)$")
SUMMARY = re.compile(
    r"^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; "
    r"(\d+) measured; (\d+) filtered out; finished in .+$"
)


class QualificationError(RuntimeError):
    """The candidate identity or exact test execution is invalid."""


def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise QualificationError(f"duplicate JSON field: {key}")
        output[key] = value
    return output


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".next")
    temporary.write_bytes(canonical_bytes(value))
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    completed = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout.strip()


def load_identity(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise QualificationError(f"invalid candidate identity: {error}") from error
    if not isinstance(value, dict) or set(value) != IDENTITY_FIELDS:
        raise QualificationError("candidate identity fields are not exact")
    if value["schema"] != "hepta.kernel-authority-candidate.v1":
        raise QualificationError("unsupported candidate identity schema")
    if value["mode"] not in {"exact-head", "synthetic-merge"}:
        raise QualificationError("unsupported candidate mode")
    for field in ("sourceCommit", "baseCommit", "candidateCommit", "candidateTree"):
        candidate = value[field]
        if not isinstance(candidate, str) or SHA1.fullmatch(candidate) is None:
            raise QualificationError(f"{field} is not an exact lowercase SHA-1")
    if value["activationGranted"] is not False or value["releaseGranted"] is not False:
        raise QualificationError("candidate identity cannot grant activation or release")
    if git("rev-parse", "HEAD") != value["candidateCommit"]:
        raise QualificationError("candidate identity does not match checkout HEAD")
    if git("rev-parse", "HEAD^{tree}") != value["candidateTree"]:
        raise QualificationError("candidate identity does not match checkout tree")
    if git("status", "--porcelain"):
        raise QualificationError("product-process qualification requires a clean checkout")
    return value


def parse_execution(text: str) -> dict[str, Any]:
    observed: dict[str, str] = {}
    totals = [0, 0, 0, 0]
    summaries = 0
    for line in text.splitlines():
        match = RESULT.fullmatch(line)
        if match:
            name, result = match.groups()
            if name in observed:
                raise QualificationError(f"duplicate test execution: {name}")
            observed[name] = result
            continue
        match = SUMMARY.fullmatch(line)
        if match:
            status, passed, failed, ignored, measured, _filtered = match.groups()
            if status != "ok":
                raise QualificationError("test suite reported failure")
            totals = [
                current + int(observed_total)
                for current, observed_total in zip(
                    totals, (passed, failed, ignored, measured), strict=True
                )
            ]
            summaries += 1
    if observed != {TEST_NAME: "ok"}:
        raise QualificationError(
            "required product-process test was missing, renamed, ignored, duplicated, or unexpected"
        )
    if summaries != 1 or totals != [1, 0, 0, 0]:
        raise QualificationError("libtest summary does not prove one exact passing test")
    return {
        "schema": "hepta.kernel-authority-product-process-test-execution.v1",
        "test": TEST_NAME,
        "passedCount": 1,
        "failedCount": 0,
        "ignoredCount": 0,
        "measuredCount": 0,
        "suiteSummaries": 1,
    }


def command() -> tuple[str, ...]:
    return (
        "cargo",
        "test",
        "--locked",
        "-p",
        "codex-hepta-agentd",
        "--test",
        "authority_effect_process_restart",
        TEST_NAME,
        "--",
        "--exact",
        "--format=pretty",
        "--color=never",
        "--test-threads=1",
    )


def run(identity: dict[str, Any], output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "logs" / "authority-effect-process-restart.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic_ns()
    environment = {
        **os.environ,
        "CARGO_INCREMENTAL": "0",
        "CARGO_TERM_COLOR": "never",
        "RUST_BACKTRACE": "1",
    }
    with log_path.open("wb") as log:
        completed = subprocess.run(
            list(command()),
            cwd=CODEX_ROOT,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    duration_ms = max(1, (time.monotonic_ns() - started) // 1_000_000)
    execution = None
    validation_error = None
    try:
        execution = parse_execution(log_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, QualificationError) as error:
        validation_error = str(error)
    passed = completed.returncode == 0 and validation_error is None
    receipt = {
        "schema": "hepta.kernel-authority-product-process-recovery.v1",
        "schemaVersion": 1,
        "candidate": identity,
        "scope": "two-normal-agentd-product-processes",
        "command": list(command()),
        "workingDirectory": "codex-rs",
        "exitCode": completed.returncode,
        "durationMs": duration_ms,
        "logPath": log_path.relative_to(output_dir).as_posix(),
        "logBytes": log_path.stat().st_size,
        "logSha256": sha256_file(log_path),
        "testExecution": execution,
        "validationError": validation_error,
        "twoNormalProductProcesses": passed,
        "pendingRevocationPreserved": passed,
        "nonceHistoryPreserved": passed,
        "attemptIdentityPreserved": passed,
        "authorityWitnessPreserved": passed,
        "terminalReceiptRecovered": passed,
        "providerRedispatchRejected": passed,
        "passed": passed,
        "productionTrustProved": False,
        "targetHostQualified": False,
        "independentAcceptance": False,
        "activationGranted": False,
        "releaseGranted": False,
    }
    write_json(output_dir / "product-process-recovery-receipt.json", receipt)
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        identity = load_identity(args.identity)
        return run(identity, args.output_dir)
    except (QualificationError, OSError, subprocess.CalledProcessError) as error:
        print(f"kernel.authority product-process recovery failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
