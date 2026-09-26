#!/usr/bin/env python3
"""Run and attest the exact-head context.compiler qualification commands.

The runner executes every required command even after an earlier failure. Each
command writes an immutable log, and the final JSON receipt binds the checked
Git commit/tree, command line, exit status, timing, log digest, truth-set files,
and the clean-worktree result. The process exits nonzero unless every required
check succeeds.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CODEX_RS = ROOT / "codex-rs"
MANIFEST = ROOT / "docs/modules/context.compiler/MODULE_MANIFEST.json"
TRUTH_FILES = (
    MANIFEST,
    ROOT / "docs/modules/context.compiler/TECHNICAL.md",
    ROOT / "docs/modules/context.compiler/IMPLEMENTATION_MAP.json",
    ROOT / "qualification/module-execution-dossiers/detail/context.compiler.md",
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_manifest_sha256() -> str:
    with MANIFEST.open(encoding="utf-8") as stream:
        value = json.load(stream)
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(canonical)


def git_output(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=ROOT,
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()


def command_specs() -> list[dict[str, Any]]:
    return [
        {
            "name": "generated-docs",
            "cwd": ROOT,
            "argv": [
                sys.executable,
                "scripts/generate_context_compiler_module_docs.py",
                "--check",
            ],
        },
        {
            "name": "rustfmt",
            "cwd": CODEX_RS,
            "argv": ["cargo", "fmt", "--all", "--", "--check"],
        },
        {
            "name": "unit-tests",
            "cwd": CODEX_RS,
            "argv": [
                "cargo",
                "test",
                "-p",
                "codex-hepta-context-compiler",
            ],
        },
        {
            "name": "strict-clippy",
            "cwd": CODEX_RS,
            "argv": [
                "cargo",
                "clippy",
                "-p",
                "codex-hepta-context-compiler",
                "--all-targets",
                "--",
                "-D",
                "warnings",
            ],
        },
        {
            "name": "cargo-deny",
            "cwd": CODEX_RS,
            "argv": ["cargo", "deny", "check"],
        },
        {
            "name": "bazel",
            "cwd": ROOT,
            "argv": [
                "bazel",
                "test",
                "//codex-rs/hepta-context-compiler:all",
                "--test_output=errors",
            ],
        },
        {
            "name": "source-readiness",
            "cwd": ROOT,
            "argv": [sys.executable, "scripts/hepta-readiness.py", "verify"],
        },
        {
            "name": "documentation-readiness",
            "cwd": ROOT,
            "argv": [sys.executable, "scripts/hepta-docs.py", "verify"],
        },
    ]


def run_command(spec: dict[str, Any], log_path: Path) -> dict[str, Any]:
    argv = [str(value) for value in spec["argv"]]
    cwd = Path(spec["cwd"])
    started_at = utc_now()
    started = time.monotonic()
    exit_code = 127
    launch_error: str | None = None

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as log:
        header = (
            f"command={shlex.join(argv)}\n"
            f"cwd={cwd.relative_to(ROOT) if cwd != ROOT else '.'}\n"
            f"started_at={started_at}\n\n"
        ).encode("utf-8")
        log.write(header)
        log.flush()
        try:
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=os.environ.copy(),
            )
            assert process.stdout is not None
            for block in iter(lambda: process.stdout.read(64 * 1024), b""):
                if not block:
                    break
                log.write(block)
                log.flush()
                sys.stdout.buffer.write(block)
                sys.stdout.buffer.flush()
            exit_code = process.wait()
        except OSError as error:
            launch_error = f"{type(error).__name__}: {error}"
            log.write(f"\nlaunch_error={launch_error}\n".encode("utf-8"))

    finished_at = utc_now()
    duration_ms = int((time.monotonic() - started) * 1000)
    result: dict[str, Any] = {
        "name": spec["name"],
        "command": shlex.join(argv),
        "argv": argv,
        "cwd": str(cwd.relative_to(ROOT)) if cwd != ROOT else ".",
        "startedAt": started_at,
        "finishedAt": finished_at,
        "durationMs": duration_ms,
        "exitCode": exit_code,
        "succeeded": exit_code == 0,
        "logPath": str(log_path.relative_to(log_path.parents[1])),
        "logBytes": log_path.stat().st_size,
        "logSha256": sha256_file(log_path),
    }
    if launch_error is not None:
        result["launchError"] = launch_error
    return result


def tool_version(argv: list[str], cwd: Path = ROOT) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"command": shlex.join(argv), "available": False, "detail": str(error)}
    output = (completed.stdout + completed.stderr).strip()
    return {
        "command": shlex.join(argv),
        "available": completed.returncode == 0,
        "exitCode": completed.returncode,
        "output": output[:4096],
    }


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    unsigned = json.dumps(
        receipt,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    receipt["receiptSha256"] = sha256_bytes(unsigned)
    encoded = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for logs and the JSON receipt.",
    )
    parser.add_argument(
        "--expected-head",
        default=os.environ.get("QUALIFICATION_HEAD_SHA") or os.environ.get("GITHUB_SHA"),
    )
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    logs_dir = output_dir / "logs"
    output_dir.mkdir(parents=True, exist_ok=True)

    head_sha = git_output("rev-parse", "HEAD")
    tree_sha = git_output("rev-parse", "HEAD^{tree}")
    expected_head = args.expected_head or head_sha
    head_matches = head_sha == expected_head
    initial_status = git_output("status", "--porcelain=v1")

    command_results = []
    for index, spec in enumerate(command_specs(), start=1):
        print(f"::group::{index:02d} {spec['name']}", flush=True)
        result = run_command(spec, logs_dir / f"{index:02d}-{spec['name']}.log")
        command_results.append(result)
        print("::endgroup::", flush=True)

    final_status = git_output("status", "--porcelain=v1")
    worktree_clean = initial_status == "" and final_status == ""
    truth_files = []
    for path in TRUTH_FILES:
        truth_files.append(
            {
                "path": str(path.relative_to(ROOT)),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    commands_succeeded = all(result["succeeded"] for result in command_results)
    succeeded = head_matches and worktree_clean and commands_succeeded
    receipt: dict[str, Any] = {
        "schema": "hepta.context-compiler-qualification-receipt.v1",
        "createdAt": utc_now(),
        "status": "passed" if succeeded else "failed",
        "headSha": head_sha,
        "expectedHeadSha": expected_head,
        "headMatchesExpected": head_matches,
        "treeSha": tree_sha,
        "baseSha": os.environ.get("QUALIFICATION_BASE_SHA"),
        "repository": os.environ.get("GITHUB_REPOSITORY"),
        "workflow": os.environ.get("GITHUB_WORKFLOW"),
        "workflowRunId": os.environ.get("GITHUB_RUN_ID"),
        "workflowRunAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "eventName": os.environ.get("GITHUB_EVENT_NAME"),
        "ref": os.environ.get("GITHUB_REF"),
        "manifestCanonicalSha256": canonical_manifest_sha256(),
        "truthFiles": truth_files,
        "toolchain": {
            "python": tool_version([sys.executable, "--version"]),
            "rustc": tool_version(["rustc", "--version"]),
            "cargo": tool_version(["cargo", "--version"]),
            "cargoDeny": tool_version(["cargo", "deny", "--version"], CODEX_RS),
            "bazel": tool_version(["bazel", "--version"]),
        },
        "worktree": {
            "cleanBefore": initial_status == "",
            "cleanAfter": final_status == "",
            "statusBefore": initial_status,
            "statusAfter": final_status,
        },
        "commands": command_results,
    }
    receipt_path = output_dir / "context-compiler-qualification-receipt.json"
    write_receipt(receipt_path, receipt)
    print(f"qualification receipt: {receipt_path}")
    print(f"qualification status: {receipt['status']}")
    return 0 if succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
