#!/usr/bin/env python3
"""Run and verify exact runtime.codex qualification receipts.

The receipt records the checked-out candidate identity, every command and log
hash, selected source-object hashes, and the resulting qualification status.
The workflow additionally subjects the JSON receipt to GitHub build-provenance
attestation; this script never treats an unsigned local JSON file as release
authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SCHEMA = "hepta.runtime-codex.qualification.v1"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_LOG_BYTES = 8 * 1024 * 1024

SOURCE_PATHS = (
    "codex-rs/hepta-codex-adapter/src/lib.rs",
    "codex-rs/hepta-infer-core/src/native_control.rs",
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs",
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs",
    "docs/modules/runtime.codex/TECHNICAL.md",
    "docs/modules/runtime.codex/FAULT_MATRIX.md",
    "docs/modules/runtime.codex/IMPLEMENTATION_MAP.json",
)


class QualificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandSpec:
    name: str
    argv: tuple[str, ...]
    timeout_seconds: int


COMMANDS = (
    CommandSpec(
        "format",
        ("cargo", "fmt", "--all", "--", "--check"),
        600,
    ),
    CommandSpec(
        "compile",
        (
            "cargo",
            "check",
            "--locked",
            "-p",
            "codex-hepta-codex-adapter",
            "-p",
            "codex-hepta-infer-core",
            "-p",
            "codex-hepta-agent-protocol",
            "-p",
            "codex-hepta-agentd",
            "-p",
            "codex-hepta-infer-worker-host",
            "--all-targets",
        ),
        3600,
    ),
    CommandSpec(
        "adapter-tests",
        ("cargo", "test", "--locked", "-p", "codex-hepta-codex-adapter"),
        1800,
    ),
    CommandSpec(
        "durable-control-tests",
        ("cargo", "test", "--locked", "-p", "codex-hepta-infer-core"),
        1800,
    ),
    CommandSpec(
        "agentd-state-tests",
        (
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-hepta-agentd",
            "lane_b_runtime",
            "--",
            "--test-threads=1",
        ),
        1800,
    ),
    CommandSpec(
        "worker-boundary-tests",
        (
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-hepta-infer-worker-host",
            "--",
            "--test-threads=1",
        ),
        2400,
    ),
    CommandSpec(
        "product-e2e",
        (
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-hepta-agentd",
            "--test",
            "runtime_codex_product_e2e",
            "runtime_codex_product_caller_commits_one_authorized_terminal_turn",
            "--",
            "--test-threads=1",
        ),
        2400,
    ),
    CommandSpec(
        "strict-clippy",
        (
            "cargo",
            "clippy",
            "--locked",
            "-p",
            "codex-hepta-codex-adapter",
            "-p",
            "codex-hepta-infer-core",
            "-p",
            "codex-hepta-agent-protocol",
            "-p",
            "codex-hepta-agentd",
            "-p",
            "codex-hepta-infer-worker-host",
            "--all-targets",
            "--",
            "-D",
            "warnings",
        ),
        3600,
    ),
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_digest(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {
        "path": path.as_posix(),
        "bytes": len(data),
        "sha256": sha256_bytes(data),
    }


def git(*args: str, cwd: Path) -> str:
    completed = subprocess.run(
        ("git", *args),
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def bounded_log(value: bytes) -> tuple[bytes, bool]:
    if len(value) <= MAX_LOG_BYTES:
        return value, False
    head = value[: MAX_LOG_BYTES // 2]
    tail = value[-MAX_LOG_BYTES // 2 :]
    marker = b"\n--- runtime.codex log truncated ---\n"
    return head + marker + tail, True


def run_command(root: Path, evidence_dir: Path, spec: CommandSpec) -> dict[str, object]:
    log_path = evidence_dir / f"{spec.name}.log"
    started_ns = time.monotonic_ns()
    timed_out = False
    try:
        completed = subprocess.run(
            spec.argv,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=spec.timeout_seconds,
            check=False,
            env={**os.environ, "CARGO_TERM_COLOR": "never"},
        )
        exit_code = completed.returncode
        raw = completed.stdout
    except subprocess.TimeoutExpired as error:
        timed_out = True
        exit_code = 124
        raw = (error.stdout or b"") + b"\nqualification command timed out\n"
    elapsed_ms = (time.monotonic_ns() - started_ns) // 1_000_000
    retained, truncated = bounded_log(raw)
    log_path.write_bytes(retained)
    sys.stdout.buffer.write(retained)
    sys.stdout.buffer.flush()
    return {
        "name": spec.name,
        "argv": list(spec.argv),
        "exitCode": exit_code,
        "timedOut": timed_out,
        "timeoutSeconds": spec.timeout_seconds,
        "elapsedMs": elapsed_ms,
        "log": {
            "path": log_path.relative_to(root).as_posix(),
            "bytes": len(retained),
            "sha256": sha256_bytes(retained),
            "truncated": truncated,
        },
    }


def candidate_identity(root: Path) -> tuple[str, str]:
    return git("rev-parse", "HEAD", cwd=root), git("rev-parse", "HEAD^{tree}", cwd=root)


def source_objects(root: Path) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for relative in SOURCE_PATHS:
        path = root / relative
        if not path.is_file():
            raise QualificationError(f"required runtime.codex source is missing: {relative}")
        entry = file_digest(path)
        entry["path"] = relative
        entry["gitObject"] = git("hash-object", relative, cwd=root)
        output.append(entry)
    return output


def emit_receipt(
    root: Path,
    output: Path,
    mode: str,
    source_sha: str,
    source_tree: str,
    base_sha: str | None,
    expected_candidate_sha: str,
    expected_candidate_tree: str,
) -> int:
    head, tree = candidate_identity(root)
    for label, value in (
        ("sourceSha", source_sha),
        ("sourceTree", source_tree),
        ("candidateSha", head),
        ("candidateTree", tree),
        ("expectedCandidateSha", expected_candidate_sha),
        ("expectedCandidateTree", expected_candidate_tree),
    ):
        if not HEX40.fullmatch(value):
            raise QualificationError(f"{label} is not a full SHA-1 identity")
    if base_sha is not None and not HEX40.fullmatch(base_sha):
        raise QualificationError("baseSha is not a full SHA-1 identity")
    if head != expected_candidate_sha or tree != expected_candidate_tree:
        raise QualificationError("checked-out candidate identity does not match workflow binding")
    if mode == "exact-head" and (head != source_sha or tree != source_tree):
        raise QualificationError("exact-head mode is not executing the source candidate")
    if mode == "synthetic-merge":
        if base_sha is None:
            raise QualificationError("synthetic-merge mode requires baseSha")
        parents = git("rev-list", "--parents", "-n", "1", "HEAD", cwd=root).split()
        if parents != [head, base_sha, source_sha]:
            raise QualificationError("synthetic merge parent order is not base then source")

    evidence_dir = output.parent
    evidence_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    for spec in COMMANDS:
        result = run_command(root, evidence_dir, spec)
        results.append(result)
        if result["exitCode"] != 0:
            break

    success = len(results) == len(COMMANDS) and all(item["exitCode"] == 0 for item in results)
    receipt = {
        "schema": SCHEMA,
        "module": "runtime.codex",
        "mode": mode,
        "sourceSha": source_sha,
        "sourceTree": source_tree,
        "baseSha": base_sha,
        "candidateSha": head,
        "candidateTree": tree,
        "workflow": {
            "repository": os.environ.get("GITHUB_REPOSITORY", "local"),
            "runId": os.environ.get("GITHUB_RUN_ID"),
            "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "job": os.environ.get("GITHUB_JOB"),
            "runnerOs": os.environ.get("RUNNER_OS"),
            "runnerArch": os.environ.get("RUNNER_ARCH"),
        },
        "toolchain": {
            "rustc": subprocess.run(
                ("rustc", "--version", "--verbose"),
                cwd=root,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout,
            "cargo": subprocess.run(
                ("cargo", "--version", "--verbose"),
                cwd=root,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout,
        },
        "sourceObjects": source_objects(root),
        "commands": results,
        "status": "passed" if success else "failed",
        "claims": {
            "repositoryCandidateQualified": success,
            "targetHostQualified": False,
            "realProviderQualified": False,
            "independentAcceptance": False,
            "activation": False,
            "promotion": False,
            "release": False,
        },
    }
    canonical_without_digest = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    receipt["receiptSha256"] = sha256_bytes(canonical_without_digest)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verify_receipt(root, output)
    return 0 if success else 1


def verify_receipt(root: Path, path: Path) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != SCHEMA or value.get("module") != "runtime.codex":
        raise QualificationError("unsupported runtime.codex qualification receipt")
    expected_digest = value.pop("receiptSha256", None)
    if not isinstance(expected_digest, str) or not HEX64.fullmatch(expected_digest):
        raise QualificationError("receipt digest is missing or malformed")
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    if sha256_bytes(canonical) != expected_digest:
        raise QualificationError("receipt digest mismatch")
    if value.get("mode") not in {"exact-head", "synthetic-merge"}:
        raise QualificationError("invalid qualification mode")
    for field in ("sourceSha", "sourceTree", "candidateSha", "candidateTree"):
        if not isinstance(value.get(field), str) or not HEX40.fullmatch(value[field]):
            raise QualificationError(f"invalid {field}")
    commands = value.get("commands")
    if not isinstance(commands, list) or not commands:
        raise QualificationError("qualification receipt has no command evidence")
    for command in commands:
        if command.get("exitCode") != 0 or command.get("timedOut") is not False:
            if value.get("status") == "passed":
                raise QualificationError("passed receipt contains a failed command")
        log = command.get("log", {})
        log_path = root / str(log.get("path", ""))
        if not log_path.is_file():
            raise QualificationError(f"qualification log is missing: {log_path}")
        data = log_path.read_bytes()
        if len(data) != log.get("bytes") or sha256_bytes(data) != log.get("sha256"):
            raise QualificationError(f"qualification log digest mismatch: {log_path}")
    objects = value.get("sourceObjects")
    if not isinstance(objects, list) or {item.get("path") for item in objects} != set(SOURCE_PATHS):
        raise QualificationError("closed-world source object inventory mismatch")
    for item in objects:
        path_value = item["path"]
        current = file_digest(root / path_value)
        if current["bytes"] != item.get("bytes") or current["sha256"] != item.get("sha256"):
            raise QualificationError(f"source object changed after execution: {path_value}")
        if git("hash-object", path_value, cwd=root) != item.get("gitObject"):
            raise QualificationError(f"source git object changed after execution: {path_value}")
    passed = value.get("status") == "passed"
    claims = value.get("claims", {})
    if claims.get("repositoryCandidateQualified") is not passed:
        raise QualificationError("repository qualification claim does not match status")
    for forbidden in (
        "targetHostQualified",
        "realProviderQualified",
        "independentAcceptance",
        "activation",
        "promotion",
        "release",
    ):
        if claims.get(forbidden) is not False:
            raise QualificationError(f"repository receipt illegally grants {forbidden}")


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser()
    sub = top.add_subparsers(dest="command", required=True)
    emit = sub.add_parser("run")
    emit.add_argument("--mode", choices=("exact-head", "synthetic-merge"), required=True)
    emit.add_argument("--source-sha", required=True)
    emit.add_argument("--source-tree", required=True)
    emit.add_argument("--base-sha")
    emit.add_argument("--candidate-sha", required=True)
    emit.add_argument("--candidate-tree", required=True)
    emit.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("receipt", type=Path)
    return top


def main() -> int:
    args = parser().parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        if args.command == "run":
            return emit_receipt(
                root,
                root / args.output,
                args.mode,
                args.source_sha,
                args.source_tree,
                args.base_sha,
                args.candidate_sha,
                args.candidate_tree,
            )
        verify_receipt(root, root / args.receipt)
        return 0
    except (QualificationError, OSError, subprocess.SubprocessError, ValueError) as error:
        print(f"runtime.codex qualification error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
