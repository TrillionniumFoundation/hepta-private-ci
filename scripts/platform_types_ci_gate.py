#!/usr/bin/env python3
"""Run platform.types qualification gates without losing failure evidence.

The runner deliberately records a gate result and returns success so later gates and
artifact upload can still execute.  A separate summary/assert phase is the only job
verdict.  This keeps diagnostics complete without weakening any required gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import threading
from datetime import datetime, timezone
from typing import BinaryIO, Iterable

SCHEMA = "hepta.platform-types-qualification-summary.v1"
GATE_SCHEMA = "hepta.platform-types-qualification-gate.v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_name(value: str) -> str:
    if not value or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in value):
        raise ValueError(f"unsafe gate name: {value!r}")
    return value


def _git(*arguments: str) -> str | None:
    completed = subprocess.run(
        ["git", *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tail(path: Path, maximum_lines: int = 80, maximum_bytes: int = 16_384) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()
    if len(data) > maximum_bytes:
        data = data[-maximum_bytes:]
    text = data.decode("utf-8", errors="replace")
    return "\n".join(text.splitlines()[-maximum_lines:])


def _copy_stream(source: BinaryIO, destination: BinaryIO, console: BinaryIO) -> None:
    try:
        for chunk in iter(lambda: source.read(64 * 1024), b""):
            destination.write(chunk)
            destination.flush()
            console.write(chunk)
            console.flush()
    finally:
        source.close()


def _write_generated_diff(root: Path, gate_name: str) -> tuple[Path, str, str]:
    patch_path = root / "gates" / f"{gate_name}.generated-diff.patch"
    status = _git("status", "--porcelain=v1", "--untracked-files=all") or ""
    unstaged = subprocess.run(
        ["git", "diff", "--binary", "--no-ext-diff"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    staged = subprocess.run(
        ["git", "diff", "--cached", "--binary", "--no-ext-diff"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    body = bytearray()
    body.extend(b"# git status --porcelain=v1 --untracked-files=all\n")
    body.extend(status.encode("utf-8", errors="replace"))
    body.extend(b"\n# git diff --binary --no-ext-diff\n")
    body.extend(unstaged.stdout)
    body.extend(b"\n# git diff --cached --binary --no-ext-diff\n")
    body.extend(staged.stdout)
    if unstaged.stderr or staged.stderr:
        body.extend(b"\n# diff stderr\n")
        body.extend(unstaged.stderr)
        body.extend(staged.stderr)
    patch_path.write_bytes(bytes(body))
    return patch_path, hashlib.sha256(body).hexdigest(), status


def _candidate_identity() -> dict[str, str | None]:
    return {
        "checkedOutCommit": _git("rev-parse", "HEAD"),
        "checkedOutTree": _git("rev-parse", "HEAD^{tree}"),
        "sourceSha": os.environ.get("SOURCE_SHA"),
        "baseSha": os.environ.get("BASE_SHA"),
        "mergeSha": os.environ.get("MERGE_SHA"),
        "workflowSha": os.environ.get("GITHUB_WORKFLOW_SHA"),
    }


def _runner_identity() -> dict[str, str | None]:
    keys = (
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
        "GITHUB_WORKFLOW",
        "GITHUB_JOB",
        "RUNNER_OS",
        "RUNNER_ARCH",
        "ImageOS",
        "ImageVersion",
    )
    return {key: os.environ.get(key) for key in keys}


def run_gate(arguments: argparse.Namespace) -> int:
    gate_name = _safe_name(arguments.name)
    if not arguments.command:
        raise ValueError("gate command is empty")
    command = list(arguments.command)
    if command[0] == "--":
        command = command[1:]
    if not command:
        raise ValueError("gate command is empty")

    root = Path(arguments.evidence_root).resolve()
    gates = root / "gates"
    gates.mkdir(parents=True, exist_ok=True)
    stdout_path = gates / f"{gate_name}.stdout.log"
    stderr_path = gates / f"{gate_name}.stderr.log"
    result_path = gates / f"{gate_name}.json"
    command_text = shlex.join(command)
    started_at = _utc_now()
    started_commit = _candidate_identity()

    return_code = 127
    launch_error: str | None = None
    try:
        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            assert process.stdout is not None
            assert process.stderr is not None
            stdout_thread = threading.Thread(
                target=_copy_stream,
                args=(process.stdout, stdout_file, sys.stdout.buffer),
                daemon=True,
            )
            stderr_thread = threading.Thread(
                target=_copy_stream,
                args=(process.stderr, stderr_file, sys.stderr.buffer),
                daemon=True,
            )
            stdout_thread.start()
            stderr_thread.start()
            return_code = process.wait()
            stdout_thread.join()
            stderr_thread.join()
    except OSError as error:
        launch_error = f"{type(error).__name__}: {error}"
        stderr_path.write_text(launch_error + "\n", encoding="utf-8")
        stdout_path.touch()

    patch_path, patch_digest, status = _write_generated_diff(root, gate_name)
    completed_at = _utc_now()
    result = {
        "schema": GATE_SCHEMA,
        "gate": gate_name,
        "required": not arguments.optional,
        "status": "passed" if return_code == 0 else "failed",
        "exitCode": return_code,
        "command": command,
        "commandLine": command_text,
        "minimalReproduction": f"cd {shlex.quote(str(Path.cwd()))} && {command_text}",
        "startedAt": started_at,
        "completedAt": completed_at,
        "candidateAtStart": started_commit,
        "candidateAtCompletion": _candidate_identity(),
        "runner": _runner_identity(),
        "stdout": str(stdout_path.relative_to(root)),
        "stderr": str(stderr_path.relative_to(root)),
        "stderrSummary": _tail(stderr_path),
        "generatedDiff": str(patch_path.relative_to(root)),
        "generatedDiffSha256": patch_digest,
        "gitStatus": status.splitlines(),
        "launchError": launch_error,
    }
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"platform.types gate {gate_name}: {result['status']} (exit {return_code})")
    return return_code if arguments.propagate else 0


def _load_gate(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != GATE_SCHEMA:
        raise ValueError(f"unsupported gate schema in {path}")
    return value


def build_summary(arguments: argparse.Namespace) -> int:
    root = Path(arguments.evidence_root).resolve()
    gates_dir = root / "gates"
    gates = [_load_gate(path) for path in sorted(gates_dir.glob("*.json"))] if gates_dir.exists() else []
    by_name = {str(gate["gate"]): gate for gate in gates}
    required = list(dict.fromkeys(arguments.required or []))
    missing = [name for name in required if name not in by_name]
    failed = [
        str(gate["gate"])
        for gate in gates
        if bool(gate.get("required", True)) and gate.get("status") != "passed"
    ]
    failed.extend(f"missing:{name}" for name in missing)
    status = "passed" if not failed else "failed"
    summary = {
        "schema": SCHEMA,
        "candidateKind": arguments.candidate_kind,
        "status": status,
        "failureReasons": failed,
        "candidate": _candidate_identity(),
        "runner": _runner_identity(),
        "generatedAt": _utc_now(),
        "requiredGates": required,
        "gates": gates,
    }
    output = Path(arguments.output) if arguments.output else root / "qualification-summary.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"platform.types qualification summary: {status}")
    for failure in failed:
        print(f"required gate failure: {failure}", file=sys.stderr)
    return 0


def assert_summary(arguments: argparse.Namespace) -> int:
    path = Path(arguments.summary)
    summary = json.loads(path.read_text(encoding="utf-8"))
    if summary.get("schema") != SCHEMA:
        raise ValueError(f"unsupported summary schema in {path}")
    if summary.get("status") != "passed":
        for failure in summary.get("failureReasons", []):
            print(f"required gate failure: {failure}", file=sys.stderr)
        return 1
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subparsers = root.add_subparsers(dest="subcommand", required=True)

    run = subparsers.add_parser("run", help="execute and record one gate")
    run.add_argument("--name", required=True)
    run.add_argument("--evidence-root", required=True)
    run.add_argument("--optional", action="store_true")
    run.add_argument("--propagate", action="store_true")
    run.add_argument("command", nargs=argparse.REMAINDER)
    run.set_defaults(handler=run_gate)

    summary = subparsers.add_parser("summary", help="write the aggregate qualification summary")
    summary.add_argument("--evidence-root", required=True)
    summary.add_argument("--candidate-kind", required=True)
    summary.add_argument("--required", action="append", default=[])
    summary.add_argument("--output")
    summary.set_defaults(handler=build_summary)

    assertion = subparsers.add_parser("assert", help="fail if the aggregate summary failed")
    assertion.add_argument("--summary", required=True)
    assertion.set_defaults(handler=assert_summary)
    return root


def main(argv: Iterable[str] | None = None) -> int:
    arguments = parser().parse_args(list(argv) if argv is not None else None)
    return int(arguments.handler(arguments))


if __name__ == "__main__":
    raise SystemExit(main())
