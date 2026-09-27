#!/usr/bin/env python3
"""Run cognitive.types qualification commands and emit an immutable JSON receipt."""

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
EVIDENCE_ROOTS = (
    ".github/workflows/cognitive-types-exact-qualification.yml",
    ".github/workflows/cognitive-types-fuzz.yml",
    ".github/workflows/cognitive-types-mutation.yml",
    "codex-rs/hepta-cognitive-types",
    "codex-rs/hepta-cognitive-read/tests/canonical_consumer_v1.rs",
    "codex-rs/hepta-cognitive-store/src/canonical_adapter.rs",
    "codex-rs/hepta-cognitive-store/tests/canonical_consumer_v1.rs",
    "codex-rs/hepta-memory-retrieval/tests/canonical_consumer_v1.rs",
    "codex-rs/hepta-compact-engine/tests/canonical_consumer_v1.rs",
    "codex-rs/hepta-intelligence/tests/canonical_consumer_v1.rs",
    "docs/modules/cognitive.types",
    "qualification/cognitive-types-v1",
    "scripts/cognitive-types-qualification-receipt.py",
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def run_text(command: list[str]) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return result.stdout.strip()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def source_manifest() -> dict[str, Any]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", *EVIDENCE_ROOTS],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    files = sorted(
        entry.decode("utf-8")
        for entry in result.stdout.split(b"\0")
        if entry
    )
    entries: dict[str, str] = {}
    for relative in files:
        path = ROOT / relative
        entries[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "fileCount": len(entries),
        "files": entries,
        "manifestSha256": hashlib.sha256(canonical_json(entries)).hexdigest(),
    }


def tool_identity(command: list[str]) -> dict[str, Any]:
    try:
        output = run_text(command)
        return {
            "command": command,
            "available": True,
            "output": output,
            "outputSha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        }
    except (OSError, subprocess.CalledProcessError) as error:
        return {
            "command": command,
            "available": False,
            "error": str(error),
        }


def run_qualification(command: str) -> dict[str, Any]:
    print(f"::group::{command}", flush=True)
    started_at = utc_now()
    monotonic_start = time.monotonic()
    digest = hashlib.sha256()
    process = subprocess.Popen(
        shlex.split(command),
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert process.stdout is not None
    for chunk in iter(lambda: process.stdout.read(64 * 1024), b""):
        sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
        digest.update(chunk)
    return_code = process.wait()
    duration_ms = int((time.monotonic() - monotonic_start) * 1_000)
    print("::endgroup::", flush=True)
    return {
        "command": command,
        "startedAt": started_at,
        "finishedAt": utc_now(),
        "durationMs": duration_ms,
        "returnCode": return_code,
        "status": "passed" if return_code == 0 else "failed",
        "outputSha256": digest.hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-kind", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--command", action="append", default=[])
    args = parser.parse_args()
    if not args.command:
        parser.error("at least one --command is required")

    started_at = utc_now()
    commands = [run_qualification(command) for command in args.command]
    passed = all(command["returnCode"] == 0 for command in commands)
    receipt: dict[str, Any] = {
        "schema": "hepta.qualification.cognitive-types.v1",
        "schemaVersion": 1,
        "candidateKind": args.candidate_kind,
        "repository": os.environ.get(
            "GITHUB_REPOSITORY", "TrillionniumFoundation/hepta-private-ci"
        ),
        "commitSha": run_text(["git", "rev-parse", "HEAD"]),
        "treeSha": run_text(["git", "rev-parse", "HEAD^{tree}"]),
        "baseSha": os.environ.get("GITHUB_BASE_SHA"),
        "headSha": os.environ.get("GITHUB_HEAD_SHA"),
        "ref": os.environ.get("GITHUB_REF"),
        "eventName": os.environ.get("GITHUB_EVENT_NAME"),
        "runId": os.environ.get("GITHUB_RUN_ID"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "job": os.environ.get("GITHUB_JOB"),
        "runnerOs": os.environ.get("RUNNER_OS"),
        "runnerArch": os.environ.get("RUNNER_ARCH"),
        "startedAt": started_at,
        "finishedAt": utc_now(),
        "status": "passed" if passed else "failed",
        "tools": {
            "rustc": tool_identity(["rustc", "--version", "--verbose"]),
            "cargo": tool_identity(["cargo", "--version", "--verbose"]),
            "clippy": tool_identity(["cargo", "clippy", "--version"]),
            "python": tool_identity(["python3", "--version"]),
            "node": tool_identity(["node", "--version"]),
        },
        "sourceManifest": source_manifest(),
        "commands": commands,
    }
    receipt["receiptSha256"] = hashlib.sha256(canonical_json(receipt)).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "candidateKind": args.candidate_kind,
                "commitSha": receipt["commitSha"],
                "treeSha": receipt["treeSha"],
                "receiptSha256": receipt["receiptSha256"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
