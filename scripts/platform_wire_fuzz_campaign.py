#!/usr/bin/env python3
"""Read-only, exact-source libFuzzer campaign; never issues lifecycle acceptance."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import time

TARGETS = ("decode_frames", "managed_records", "policy_admission")
SEED_MODES = {
    "decode_frames": range(5),
    "managed_records": range(7),
    "policy_admission": range(5),
}
SCHEMA = "hepta.platform-wire.fuzz-campaign.v2"
SHA = re.compile(r"[0-9a-f]{40}")
EXECUTIONS = re.compile(r"stat::number_of_executed_units:\s*(\d+)")
CONTEXT = {
    "toolchain": "FUZZ_TOOLCHAIN",
    "cargo_fuzz_version": "CARGO_FUZZ_VERSION",
    "installer_toolchain": "FUZZ_INSTALL_TOOLCHAIN",
    "workflow_sha": "GITHUB_WORKFLOW_SHA",
    "workflow_ref": "GITHUB_WORKFLOW_REF",
    "run_id": "GITHUB_RUN_ID",
    "run_attempt": "GITHUB_RUN_ATTEMPT",
    "event": "GITHUB_EVENT_NAME",
    "runner_image": "ImageOS",
    "runner_image_version": "ImageVersion",
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def inventory(root: Path) -> list[dict]:
    return (
        [
            {
                "path": str(p.relative_to(root)),
                "bytes": p.stat().st_size,
                "sha256": digest(p),
            }
            for p in sorted(root.rglob("*"))
            if p.is_file() and not p.is_symlink()
        ]
        if root.exists()
        else []
    )


def seconds(event: str, requested: str) -> int:
    raw = (
        requested
        if event == "workflow_dispatch"
        else {
            "pull_request": "180",
            "schedule": "900",
        }.get(event, "360")
    )
    if not re.fullmatch(r"[0-9]{1,4}", raw) or not 60 <= int(raw) <= 1800:
        raise ValueError("total campaign duration must be 60..1800 seconds")
    return int(raw)


def command(target: str, duration: int, *, toolchain: str | None = None) -> list[str]:
    if target not in TARGETS or type(duration) is not int or not 20 <= duration <= 600:
        raise ValueError("invalid bounded target or duration")
    if toolchain is None:
        toolchain = os.environ.get("FUZZ_TOOLCHAIN", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", toolchain):
        raise ValueError("missing or invalid fuzz toolchain")
    return [
        "cargo",
        "+" + toolchain,
        "fuzz",
        "run",
        target,
        "fuzz/corpus/" + target,
        "--",
        f"-max_total_time={duration}",
        "-timeout=10",
        "-rss_limit_mb=2048",
        "-max_len=65536",
        "-seed=1",
        "-print_final_stats=1",
        f"-artifact_prefix=fuzz/artifacts/{target}/",
    ]


def executed_units(path: Path) -> int:
    count = 0
    with path.open(errors="replace") as handle:
        for line in handle:
            match = EXECUTIONS.search(line)
            if match:
                count = max(count, int(match.group(1)))
    return count


def subject(root: Path) -> dict:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    source = os.environ.get("SOURCE_SHA", "")
    tested = git("rev-parse", "HEAD")
    if SHA.fullmatch(source) is None or source != tested:
        raise ValueError("campaign must test the exact requested source SHA")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("tracked source must be clean")
    return {
        "source_sha": source,
        "tested_sha": tested,
        "source_tree": git("rev-parse", "HEAD^{tree}"),
    }


def save(path: Path, receipt: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def context() -> dict:
    return {field: os.environ.get(variable) for field, variable in CONTEXT.items()}


def validate_binding(root: Path, receipt: dict) -> int:
    if receipt.get("schema") != SCHEMA:
        raise ValueError("campaign schema mismatch")
    for key, value in {**subject(root), **context()}.items():
        if key not in receipt or receipt[key] != value:
            raise ValueError(f"campaign {key} mismatch")
    duration = seconds(
        os.environ.get("GITHUB_EVENT_NAME", ""), os.environ.get("REQUESTED_SECONDS", "")
    )
    if (
        type(receipt.get("duration_seconds")) is not int
        or receipt["duration_seconds"] != duration
    ):
        raise ValueError("campaign duration mismatch")
    if receipt.get("engine") != "libFuzzer" or receipt.get("sanitizer") != "address":
        raise ValueError("campaign engine or sanitizer mismatch")
    return duration // len(TARGETS)


def initialize(root: Path, path: Path) -> dict:
    receipt = {
        "schema": SCHEMA,
        "status": "not_run",
        "created_at": utc_now(),
        "source_sha": os.environ.get("SOURCE_SHA"),
        "tested_sha": None,
        **context(),
        "engine": "libFuzzer",
        "sanitizer": "address",
        "targets": {
            t: {"status": "not_run", "reason": "preparation_incomplete"}
            for t in TARGETS
        },
        "production_activation": False,
        "independent_acceptance": False,
        "real_transport_acceptance": False,
    }
    # Write before parsing inputs or invoking git: preparation failure is evidence.
    save(path, receipt)
    try:
        receipt["duration_seconds"] = seconds(
            os.environ.get("GITHUB_EVENT_NAME", ""),
            os.environ.get("REQUESTED_SECONDS", ""),
        )
        receipt.update(subject(root))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        receipt["status"] = "failed"
        receipt["preparation_error"] = str(error)
        save(path, receipt)
        raise
    save(path, receipt)
    return receipt


def seed(root: Path) -> None:
    fuzz = root / "codex-rs/hepta-wire/fuzz"
    for target in TARGETS:
        (fuzz / "corpus" / target).mkdir(parents=True, exist_ok=True)
        (fuzz / "artifacts" / target).mkdir(parents=True, exist_ok=True)
        for mode in SEED_MODES[target]:
            (fuzz / "corpus" / target / f"mode-{mode}").write_bytes(
                bytes([mode, 13]) + b"wire-seed"
            )
    vector = json.loads(
        (
            root / "docs/lane-a-foundation/platform.wire/HPTA_V2_CONFORMANCE.json"
        ).read_text()
    )
    corpus = fuzz / "corpus/decode_frames"
    (corpus / "hpta-v2-canonical").write_bytes(bytes.fromhex(vector["frameHex"]))
    (corpus / "hptn-current").write_bytes(
        bytes.fromhex("4850544e00010200000000000000000700010002")
    )
    (corpus / "truncated-header").write_bytes(b"HPTA\x00\x02")
    (corpus / "empty").write_bytes(b"")


def run_bounded(argv: list[str], *, cwd: Path, stdout, timeout: float) -> int:
    """Retire Cargo and its entire process group, not just the wrapper process.

    Qualification uses a Linux runner. Do not silently use weaker termination
    on unsupported hosts. Popen.wait always reaps the directly owned child.
    """
    if os.name != "posix":
        raise OSError("POSIX process-group ownership required")
    env = os.environ.copy()
    env["RUSTUP_TOOLCHAIN"] = os.environ["FUZZ_TOOLCHAIN"]
    with subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdout=stdout,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    ) as process:
        try:
            return process.wait(timeout=timeout)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def run(root: Path, path: Path) -> None:
    receipt = json.loads(path.read_text())
    duration = validate_binding(root, receipt)
    receipt["status"] = "running"
    receipt["targets"] = {t: {"status": "not_run"} for t in TARGETS}
    save(path, receipt)  # Invalidate old successes before the first child starts.
    for target in TARGETS:
        validate_binding(root, receipt)
        log = path.parent / (target + ".log")
        argv = command(target, duration)
        row = {
            "status": "running",
            "command": argv,
            "started_at": utc_now(),
            "cwd": "codex-rs/hepta-wire",
            "duration_seconds": duration,
            "timeout_seconds": duration + 120,
        }
        receipt["targets"][target] = row
        save(path, receipt)
        started = time.monotonic()
        try:
            with log.open("w") as output:
                code = run_bounded(
                    argv,
                    cwd=root / "codex-rs/hepta-wire",
                    stdout=output,
                    timeout=duration + 120,
                )
            row["exit_code"] = code
            row["executed_units"] = executed_units(log)
            row["status"] = (
                "passed" if code == 0 and row["executed_units"] > 0 else "failed"
            )
            if row["status"] != "passed":
                row["reason"] = "nonzero_exit_or_no_execution_statistics"
        except (OSError, subprocess.TimeoutExpired) as error:
            row.update(status="failed", reason=type(error).__name__, exit_code=None)
        row["elapsed_seconds"] = time.monotonic() - started
        row["finished_at"] = utc_now()
        row["log_sha256"] = digest(log) if log.is_file() else None
        save(path, receipt)
        print(f"{target}: {row['status']}", flush=True)
    # A failing target does not prevent the other scenarios from executing.


def valid_execution(
    row: dict,
    target: str,
    duration: int,
    log: Path,
    *,
    toolchain: str | None = None,
) -> bool:
    elapsed = row.get("elapsed_seconds")
    return (
        row.get("command") == command(target, duration, toolchain=toolchain)
        and row.get("cwd") == "codex-rs/hepta-wire"
        and type(row.get("duration_seconds")) is int
        and row["duration_seconds"] == duration
        and type(row.get("timeout_seconds")) is int
        and row["timeout_seconds"] == duration + 120
        and type(row.get("exit_code")) is int
        and row["exit_code"] == 0
        and type(row.get("executed_units")) is int
        and row["executed_units"] > 0
        and type(elapsed) in (int, float)
        and math.isfinite(elapsed)
        and elapsed > 0
        and not log.is_symlink()
        and log.is_file()
        and digest(log) == row.get("log_sha256")
        and executed_units(log) == row["executed_units"]
    )


def finalize(root: Path, path: Path) -> bool:
    # A malformed/stale receipt must replace, never preserve, a passing result.
    try:
        receipt = json.loads(path.read_text())
        if not isinstance(receipt, dict):
            raise ValueError("campaign receipt must be an object")
    except (OSError, ValueError) as error:
        receipt = {
            "schema": SCHEMA,
            "targets": {},
            "status": "failed",
            "finalization_error": type(error).__name__,
        }
    bound = False
    duration = 0
    try:
        duration = validate_binding(root, receipt)
        bound = True
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        receipt["finalization_error"] = str(error)
    if not isinstance(receipt.get("targets"), dict):
        receipt["targets"] = {}
        bound = False
    for target in TARGETS:
        row = receipt["targets"].setdefault(target, {"status": "not_run"})
        if not isinstance(row, dict):
            row = receipt["targets"][target] = {
                "status": "failed",
                "reason": "malformed_target",
            }
        if row.get("status") in ("not_run", "running"):
            row["reason"] = "preparation_failed_or_execution_interrupted"
        if row.get("status") == "running":
            row["status"] = "failed"
        log = path.parent / (target + ".log")
        if row.get("status") == "passed":
            try:
                valid = bound and valid_execution(row, target, duration, log)
            except (OSError, ValueError):
                valid = False
            if not valid:
                row.update(status="failed", reason="execution_evidence_mismatch")
        for kind in ("corpus", "artifacts"):
            row[kind] = inventory(root / "codex-rs/hepta-wire/fuzz" / kind / target)
    passed = bound and all(
        receipt["targets"][t].get("status") == "passed" for t in TARGETS
    )
    receipt.update(
        status="passed" if passed else "failed",
        finalized_at=utc_now(),
        production_activation=False,
        independent_acceptance=False,
        real_transport_acceptance=False,
    )
    receipt["logs"] = inventory(path.parent / "preparation")
    lock = root / "codex-rs/hepta-wire/fuzz/Cargo.lock"
    receipt["fuzz_lock_sha256"] = digest(lock) if lock.is_file() else None
    save(path, receipt)
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "seed", "run", "finalize", "check"))
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    root = args.root.resolve()
    path = root / ".hepta-evidence/platform-wire-fuzz/campaign.json"
    if args.command == "init":
        initialize(root, path)
    elif args.command == "seed":
        seed(root)
    elif args.command == "run":
        run(root, path)
    elif args.command == "finalize":
        finalize(root, path)  # Always retain failed evidence before enforcing.
    else:
        return 0 if finalize(root, path) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
