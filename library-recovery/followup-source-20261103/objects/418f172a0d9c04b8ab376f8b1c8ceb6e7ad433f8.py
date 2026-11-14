#!/usr/bin/env python3
"""Read-only source admission + fail-closed native Rust qualification harness.

Source checkout must be trusted: cargo builds and tests can execute repository code.
No command result from this harness is independent production authorization.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

BLOCKED = "BLOCKED"
PASS = "PASS"
FAIL = "FAIL"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".hepta-gate-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name == "posix":
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run(argv: list[str], cwd: Path, timeout: int, *, stdout_file: Path | None = None) -> dict:
    started = time.monotonic()
    result = {"argv": argv, "started_utc": utc_now(), "timeout_seconds": timeout}
    try:
        completed = subprocess.run(argv, cwd=cwd, text=False, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, timeout=timeout, check=False)
        output = completed.stdout or b""
        result.update(exit_code=completed.returncode, status=PASS if completed.returncode == 0 else FAIL)
    except FileNotFoundError as exc:
        output = str(exc).encode()
        result.update(exit_code=None, status=BLOCKED, reason="command-not-found")
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or b"") + b"\nTIMEOUT: process was terminated by Python.\n"
        result.update(exit_code=None, status=FAIL, reason="timeout")
    except OSError as exc:
        output = str(exc).encode()
        result.update(exit_code=None, status=BLOCKED, reason="operating-system-error")
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    result["output_bytes"] = len(output)
    result["output_sha256"] = hashlib.sha256(output).hexdigest()
    result["output_tail"] = output[-1500:].decode("utf-8", "replace")
    if stdout_file is not None:
        stdout_file.parent.mkdir(parents=True, exist_ok=True)
        stdout_file.write_bytes(output)
        result["log_path"] = str(stdout_file)
        result["log_sha256"] = sha256(stdout_file)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed local Hepta Rust exact-head gate")
    parser.add_argument("--repo", required=True, help="Existing local checkout path")
    parser.add_argument("--expected-head", required=True, help="Exactly 40 hexadecimal Git commit characters")
    parser.add_argument("--kind", choices=("hepta-private-ci", "hepta-runtime"), required=True)
    parser.add_argument("--out", required=True, help="JSON receipt outside the source worktree")
    parser.add_argument("--timeout", type=int, default=1800, help="Timeout per Rust gate in seconds")
    args = parser.parse_args(argv)
    repo = Path(args.repo).expanduser().resolve()
    receipt_path = Path(args.out).expanduser().resolve()
    receipt = {
        "schema": "HeptaLocalSourceGateV1", "started_utc": utc_now(),
        "repo": str(repo), "kind": args.kind,
        "expected_head": args.expected_head, "status": BLOCKED,
        "source_exact": False, "worktree_clean": False,
        "native_gates": {}, "production_qualified": False,
        "independent_effect_evidence": "NOT_PROVIDED",
        "limitations": ["This harness does not verify physical SSH effect receipts, FinalUse, CellSplit CAS/CNS/fences, NDU efficacy or scale."],
    }

    def stop(reason: str) -> int:
        receipt["status"] = BLOCKED
        receipt["reason"] = reason
        receipt["finished_utc"] = utc_now()
        atomic_json(receipt_path, receipt)
        print(f"BLOCKED: {reason}. Receipt: {receipt_path}")
        return 2

    if not re.fullmatch(r"[0-9a-fA-F]{40}", args.expected_head):
        return stop("invalid-exact-40-character-commit")
    if args.timeout < 1 or args.timeout > 7200:
        return stop("invalid-gate-timeout")
    # Refuse the destination without writing anything into a checkout, even
    # on a malformed invocation or nonexistent checkout path.
    if receipt_path == repo or repo in receipt_path.parents:
        print("BLOCKED: receipt-must-be-outside-worktree", file=sys.stderr)
        return 2
    if not repo.is_dir() or not (repo / ".git").exists():
        return stop("local-worktree-missing")
    if shutil.which("git") is None:
        return stop("git-not-installed")

    # Never interpret source/sandbox hooks as neutral CI defaults.
    prohibited = [name for name in os.environ if name in {
        "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS",
        "LD_PRELOAD", "DYLD_INSERT_LIBRARIES", "GIT_CONFIG_COUNT", "BASH_ENV", "ENV"
    } or re.fullmatch(r"GIT_CONFIG_(?:KEY|VALUE)_\d+", name)]
    if prohibited:
        receipt["blocked_injected_environment_keys"] = sorted(prohibited)
        return stop("unqualified-executable-or-toolchain-environment")

    head = run(["git", "rev-parse", "--verify", "HEAD"], repo, 30)
    receipt["git_head_command"] = head
    if head["status"] != PASS:
        return stop("git-head-unavailable")
    actual = head["output_tail"].strip().lower()
    receipt["actual_head"] = actual
    if actual != args.expected_head.lower():
        return stop("exact-source-head-mismatch")
    receipt["source_exact"] = True

    status = run(["git", "status", "--porcelain=v1", "--untracked-files=all"], repo, 60)
    receipt["git_status_command"] = status
    if status["status"] != PASS:
        return stop("worktree-status-unavailable")
    if status["output_bytes"]:
        return stop("worktree-not-clean")
    receipt["worktree_clean"] = True

    root = repo / "codex-rs" if args.kind == "hepta-private-ci" else repo
    if not (root / "Cargo.toml").is_file() or not (root / "Cargo.lock").is_file():
        return stop("cargo-workspace-or-lockfile-missing")
    if shutil.which("cargo") is None or shutil.which("rustc") is None:
        return stop("rust-compiler-or-cargo-unavailable")
    for binary in ("cargo", "rustc", "rustfmt"):
        output = run([binary, "--version"], root, 30)
        receipt.setdefault("toolchain", {})[binary] = output
        if output["status"] != PASS:
            return stop(f"{binary}-version-check-failed")

    commands = {
        "format": ["cargo", "fmt", "--all", "--", "--check"],
        "check": ["cargo", "check", "--locked", "--all-targets"],
        "clippy": ["cargo", "clippy", "--locked", "--all-targets", "--", "-D", "warnings"],
        "tests": ["cargo", "test", "--locked", "--all-targets"],
        "release": ["cargo", "build", "--locked", "--release"],
    }
    logs_dir = receipt_path.parent / (receipt_path.stem + ".logs")
    any_failure = False
    for name, command in commands.items():
        if any_failure:
            receipt["native_gates"][name] = {"status": BLOCKED, "reason": "preceding-gate-failed"}
            continue
        result = run(command, root, args.timeout, stdout_file=logs_dir / (name + ".log"))
        receipt["native_gates"][name] = result
        if result["status"] != PASS:
            any_failure = True
    receipt["status"] = FAIL if any_failure else PASS
    receipt["finished_utc"] = utc_now()
    # Pass is limited to these five local Rust commands, not the release criteria.
    receipt["qualification_scope"] = "local-rust-source-only"
    atomic_json(receipt_path, receipt)
    print(f"{receipt['status']}: local native Rust gates (not production). Receipt: {receipt_path}")
    return 1 if any_failure else 0


if __name__ == "__main__":
    sys.exit(main())
