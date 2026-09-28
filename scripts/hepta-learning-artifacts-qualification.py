#!/usr/bin/env python3
"""Run, emit and verify exact-head learning.artifacts qualification receipts.

A receipt is valid only when every named task executed for the same Git commit
and tree and returned success.  Missing, skipped, neutral and historical results
are rejected.  The receipt binds the exact source objects used by the owner,
writer service, storage boundary, product reader and module documentation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "hepta.learning-artifacts-exact-head-qualification.v1"
TASK_SCHEMA = "hepta.learning-artifacts-qualification-task.v1"
REQUIRED_TASKS = (
    "build",
    "strict_clippy",
    "owner_regression",
    "security",
    "property",
    "boundary_sequence",
    "service_e2e",
    "read_boundary",
    "write_atomicity",
    "snapshot_fallback",
)
SOURCE_PATHS = (
    "codex-rs/hepta-learning-artifacts",
    "codex-rs/hepta-learning-artifacts/src/lib.rs",
    "codex-rs/hepta-learning-artifacts/src/owner_host.rs",
    "codex-rs/hepta-learning-artifacts/src/owner_service.rs",
    "codex-rs/hepta-learning-artifacts/src/storage.rs",
    "codex-rs/hepta-learning-artifacts/src/publication.rs",
    "codex-rs/hepta-learning-artifacts/src/selection.rs",
    "codex-rs/hepta-agentd/src/cognitive_ranker.rs",
    "docs/modules/learning.artifacts/IMPLEMENTATION_MAP.json",
    "docs/modules/learning.artifacts/TECHNICAL.md",
    "qualification/learning-artifacts/STATUS.json",
)
MAX_CAPTURE_BYTES = 16 * 1024 * 1024


class QualificationError(RuntimeError):
    pass


def git(*args: str) -> str:
    process = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    if process.returncode != 0:
        raise QualificationError(process.stderr.strip() or f"git {' '.join(args)} failed")
    return process.stdout.strip()


def exact_source() -> tuple[str, str]:
    return git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def receipt_digest(value: dict[str, Any]) -> str:
    unsigned = dict(value)
    unsigned.pop("receiptDigest", None)
    return hashlib.sha256(canonical_bytes(unsigned)).hexdigest()


def bounded_text(value: bytes) -> str:
    if len(value) > MAX_CAPTURE_BYTES:
        value = value[:MAX_CAPTURE_BYTES] + b"\n<qualification output truncated>\n"
    return value.decode("utf-8", errors="replace")


def run_task(args: argparse.Namespace) -> int:
    if args.task not in REQUIRED_TASKS:
        raise QualificationError(f"unknown qualification task: {args.task}")
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise QualificationError("run-task requires a command after --")

    source_sha, source_tree = exact_source()
    expected_sha = args.source_sha or os.environ.get("SOURCE_SHA")
    if expected_sha and expected_sha != source_sha:
        raise QualificationError(
            f"task source mismatch: expected {expected_sha}, checked out {source_sha}"
        )

    started_ns = time.time_ns()
    process = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    completed_ns = time.time_ns()
    output = bounded_text(process.stdout)
    sys.stdout.write(output)
    sys.stdout.flush()

    log_path = Path(args.output).with_suffix(".log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(output, encoding="utf-8")
    result = {
        "schema": TASK_SCHEMA,
        "task": args.task,
        "sourceSha": source_sha,
        "sourceTree": source_tree,
        "command": command,
        "startedUnixNs": started_ns,
        "completedUnixNs": completed_ns,
        "durationMs": (completed_ns - started_ns) // 1_000_000,
        "exitCode": process.returncode,
        "status": "success" if process.returncode == 0 else "failure",
        "skipped": False,
        "logSha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "logPath": log_path.name,
    }
    Path(args.output).write_bytes(canonical_bytes(result))
    return process.returncode


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise QualificationError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise QualificationError(f"{path} must contain a JSON object")
    return value


def validate_task(path: Path, task: str, source_sha: str, source_tree: str) -> dict[str, Any]:
    value = load_object(path)
    if value.get("schema") != TASK_SCHEMA or value.get("task") != task:
        raise QualificationError(f"{path} is not the {task} task result")
    if value.get("sourceSha") != source_sha or value.get("sourceTree") != source_tree:
        raise QualificationError(f"{task} result belongs to another source candidate")
    if value.get("status") != "success" or value.get("skipped") is not False:
        raise QualificationError(f"{task} did not execute successfully")
    if value.get("exitCode") != 0:
        raise QualificationError(f"{task} has a non-zero exit code")
    command = value.get("command")
    if not isinstance(command, list) or not command:
        raise QualificationError(f"{task} has no recorded command")
    if not isinstance(value.get("durationMs"), int) or value["durationMs"] < 0:
        raise QualificationError(f"{task} has an invalid duration")
    return value


def source_objects(source_sha: str) -> list[dict[str, str]]:
    objects: list[dict[str, str]] = []
    for path in SOURCE_PATHS:
        object_id = git("rev-parse", f"{source_sha}:{path}")
        objects.append({"path": path, "gitObject": object_id})
    return objects


def emit(args: argparse.Namespace) -> int:
    source_sha, source_tree = exact_source()
    if args.source_sha and args.source_sha != source_sha:
        raise QualificationError("--source-sha differs from the checked-out commit")
    if args.source_tree and args.source_tree != source_tree:
        raise QualificationError("--source-tree differs from the checked-out tree")
    results_dir = Path(args.results_dir)
    tasks = [
        validate_task(results_dir / f"{task}.json", task, source_sha, source_tree)
        for task in REQUIRED_TASKS
    ]
    value: dict[str, Any] = {
        "schema": SCHEMA,
        "qualificationState": "exact_head_passed",
        "sourceSha": source_sha,
        "sourceTree": source_tree,
        "baseSha": args.base_sha or "",
        "requiredTasks": list(REQUIRED_TASKS),
        "tasks": tasks,
        "sourceObjects": source_objects(source_sha),
        "claims": {
            "sourceQualification": True,
            "productActivation": False,
            "independentAcceptance": False,
            "release": False,
        },
    }
    value["receiptDigest"] = receipt_digest(value)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_bytes(value))
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


def verify_receipt(path: Path, require_checkout: bool) -> dict[str, Any]:
    value = load_object(path)
    if value.get("schema") != SCHEMA:
        raise QualificationError("unexpected qualification receipt schema")
    if value.get("qualificationState") != "exact_head_passed":
        raise QualificationError("receipt does not record an exact-head pass")
    if value.get("requiredTasks") != list(REQUIRED_TASKS):
        raise QualificationError("receipt task closed world differs from the required set")
    if value.get("receiptDigest") != receipt_digest(value):
        raise QualificationError("receipt digest mismatch")
    source_sha = value.get("sourceSha")
    source_tree = value.get("sourceTree")
    if not isinstance(source_sha, str) or not isinstance(source_tree, str):
        raise QualificationError("receipt source identity is missing")
    tasks = value.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != len(REQUIRED_TASKS):
        raise QualificationError("receipt task result count is invalid")
    by_name = {task.get("task"): task for task in tasks if isinstance(task, dict)}
    if set(by_name) != set(REQUIRED_TASKS):
        raise QualificationError("receipt task results are incomplete or duplicated")
    for task in REQUIRED_TASKS:
        record = by_name[task]
        if (
            record.get("sourceSha") != source_sha
            or record.get("sourceTree") != source_tree
            or record.get("status") != "success"
            or record.get("skipped") is not False
            or record.get("exitCode") != 0
        ):
            raise QualificationError(f"receipt task is not a successful exact-head run: {task}")
    claims = value.get("claims")
    if not isinstance(claims, dict) or claims.get("sourceQualification") is not True:
        raise QualificationError("receipt does not claim source qualification")
    for external in ("productActivation", "independentAcceptance", "release"):
        if claims.get(external) is not False:
            raise QualificationError(f"receipt may not self-certify {external}")
    objects = value.get("sourceObjects")
    if not isinstance(objects, list) or {item.get("path") for item in objects if isinstance(item, dict)} != set(SOURCE_PATHS):
        raise QualificationError("receipt source-object closed world is incomplete")
    if require_checkout:
        current_sha, current_tree = exact_source()
        if current_sha != source_sha or current_tree != source_tree:
            raise QualificationError("receipt belongs to another checkout")
        expected = {item["path"]: item["gitObject"] for item in objects}
        actual = {item["path"]: item["gitObject"] for item in source_objects(source_sha)}
        if actual != expected:
            raise QualificationError("receipt source-object binding mismatch")
    return value


def verify(args: argparse.Namespace) -> int:
    value = verify_receipt(Path(args.receipt), not args.allow_detached_receipt)
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command_name", required=True)

    run = commands.add_parser("run-task")
    run.add_argument("--task", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--source-sha")
    run.add_argument("command", nargs=argparse.REMAINDER)
    run.set_defaults(handler=run_task)

    emit_parser = commands.add_parser("emit")
    emit_parser.add_argument("--results-dir", required=True)
    emit_parser.add_argument("--output", required=True)
    emit_parser.add_argument("--source-sha")
    emit_parser.add_argument("--source-tree")
    emit_parser.add_argument("--base-sha")
    emit_parser.set_defaults(handler=emit)

    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("receipt")
    verify_parser.add_argument("--allow-detached-receipt", action="store_true")
    verify_parser.set_defaults(handler=verify)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.handler(args))
    except QualificationError as error:
        print(f"qualification error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
