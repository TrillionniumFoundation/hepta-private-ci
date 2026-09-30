#!/usr/bin/env python3
"""Execute the existing qualification contract and retain actual command evidence.

This is not a new qualification lane or an approval authority. The existing
shell entrypoint delegates to this recorder; attestation consumes its immutable
candidate, command outcomes and raw logs instead of trusting a success label.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shlex
import signal
import subprocess
import sys
import time
from typing import Any

SCHEMA = "hepta.memory-federation.command-execution.v1"
DIRECTORY = "memory-federation-execution"
MAX_RECORD_BYTES = 4 * 1024 * 1024
GITHUB_FIELDS = {
    "repository": "GITHUB_REPOSITORY", "runId": "GITHUB_RUN_ID",
    "runAttempt": "GITHUB_RUN_ATTEMPT", "job": "GITHUB_JOB",
    "workflowRef": "GITHUB_WORKFLOW_REF", "workflowSha": "GITHUB_WORKFLOW_SHA",
}


class ExecutionError(RuntimeError):
    pass


class ExecutionInterrupted(ExecutionError):
    def __init__(self, signum: int):
        super().__init__(f"qualification interrupted by signal {signum}")
        self.signum = signum


def command_failed(record: dict[str, Any]) -> bool:
    return (record["exitCode"] != 0 or record["timedOut"] or
            record.get("interruptedSignal") is not None or record.get("orphanedChildren", False))


def signal_group(process: subprocess.Popen, signum: int) -> bool:
    """Signal only the session created for this command, never the caller's group."""
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        return False
    return True


def digest(path: pathlib.Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def strict_json(path: pathlib.Path) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ExecutionError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ExecutionError(f"non-finite JSON constant: {value}")

    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_RECORD_BYTES:
        raise ExecutionError("invalid or oversized JSON evidence")
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs,
                          parse_constant=invalid_constant)
    except (OSError, UnicodeError, ValueError) as error:
        raise ExecutionError(f"invalid JSON evidence: {error}") from error


def safe_file(directory: pathlib.Path, name: Any) -> pathlib.Path:
    if not isinstance(name, str) or not name or pathlib.PurePosixPath(name).name != name:
        raise ExecutionError("evidence must name a file in its own directory")
    path = directory / name
    if path.is_symlink() or not path.is_file():
        raise ExecutionError("missing or symlinked execution evidence")
    return path


def atomic_write(path: pathlib.Path, value: Any) -> None:
    temporary = path.with_suffix(".pending")
    with temporary.open("xb") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def location(command: str) -> str:
    return "codex-rs" if command.startswith("cargo ") and "--manifest-path" not in command else "."


def command_record(index: int, command: str, expanded: str, cwd: pathlib.Path,
                   output: pathlib.Path, timeout: float = 1800) -> dict[str, Any]:
    path = output / f"command-{index:03d}.log"
    started = time.monotonic_ns()
    timed_out = False
    interrupted_signal = None
    orphaned_children = False
    print(f"[{index:03d}] {command}", flush=True)
    with path.open("xb") as log:
        process = subprocess.Popen(["bash", "-euo", "pipefail", "-c", expanded],
                                   cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        except ExecutionInterrupted as error:
            interrupted_signal = error.signum
        except KeyboardInterrupt:
            interrupted_signal = int(signal.SIGINT)
        finally:
            if process.poll() is None:
                signal_group(process, interrupted_signal or signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    signal_group(process, signal.SIGKILL)
                    process.wait()
            # The leader can exit while a descendant still owns the log or
            # build inputs. Terminate remaining in-session processes even when
            # the leader exited zero; such a command cannot qualify as a pass.
            orphaned_children = signal_group(process, signal.SIGKILL)
        log.flush()
        os.fsync(log.fileno())
    elapsed = time.monotonic_ns() - started
    # Only a bounded tail is printed. The full binary log is retained verbatim.
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 65536))
        tail = stream.read()
    sys.stdout.write(tail.decode("utf-8", errors="replace"))
    sys.stdout.flush()
    return {"index": index, "command": command, "cwd": location(command),
            "exitCode": process.returncode, "timedOut": timed_out,
            "interruptedSignal": interrupted_signal, "orphanedChildren": orphaned_children,
            "elapsedNanos": elapsed, "log": path.name,
            "logBytes": path.stat().st_size, "logSha256": digest(path)}


def validate(path: pathlib.Path, commands: list[str], candidate: dict[str, str],
             input_snapshot: dict[str, Any], require_success: bool) -> dict[str, Any]:
    document = strict_json(path)
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise ExecutionError("execution schema mismatch")
    if document.get("candidate") != candidate or document.get("inputs") != input_snapshot:
        raise ExecutionError("execution belongs to different source or command inputs")
    if document.get("commandManifestSha256") != hashlib.sha256(canonical(commands)).hexdigest():
        raise ExecutionError("execution command contract mismatch")
    records = document.get("commands")
    if not isinstance(records, list) or len(records) > len(commands):
        raise ExecutionError("invalid execution command count")
    failed = False
    for index, record in enumerate(records):
        if not isinstance(record, dict) or type(record.get("index")) is not int or record["index"] != index:
            raise ExecutionError("duplicate, reordered or invalid command index")
        if failed or record.get("command") != commands[index] or record.get("cwd") != location(commands[index]):
            raise ExecutionError("execution is not the exact command prefix")
        for field in ("exitCode", "elapsedNanos", "logBytes"):
            if type(record.get(field)) is not int:
                raise ExecutionError(f"invalid command {field}")
        if record["elapsedNanos"] < 0 or record["logBytes"] < 0 or type(record.get("timedOut")) is not bool:
            raise ExecutionError("invalid command measurement")
        interruption = record.get("interruptedSignal")
        if interruption is not None and (
                type(interruption) is not int or interruption not in (signal.SIGINT, signal.SIGTERM)):
            raise ExecutionError("invalid command interruption signal")
        if type(record.get("orphanedChildren", False)) is not bool:
            raise ExecutionError("invalid command descendant disposition")
        log = safe_file(path.parent, record.get("log"))
        if log.name != f"command-{index:03d}.log" or log.stat().st_size != record["logBytes"] or digest(log) != record.get("logSha256"):
            raise ExecutionError("command log binding mismatch")
        failed = command_failed(record)
    metrics_digest = document.get("capacityMetricsSha256")
    if metrics_digest is not None:
        if digest(safe_file(path.parent, "capacity.json")) != metrics_digest:
            raise ExecutionError("capacity evidence differs from measured execution")
    if document.get("conclusion") not in {"success", "failure"}:
        raise ExecutionError("execution did not finish")
    if require_success or document["conclusion"] == "success":
        if (document["conclusion"] != "success" or failed or not records or
                len(records) != len(commands) or document.get("finalInputs") != input_snapshot):
            raise ExecutionError("success requires every command and unchanged final inputs")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        observed = document.get("github")
        expected = {key: os.environ.get(env, "") for key, env in GITHUB_FIELDS.items()}
        if not all(expected.values()) or observed != expected:
            raise ExecutionError("execution workflow/run/attempt/job identity mismatch")
    return document


def run() -> int:
    # Late imports keep the recorder's parser reusable without a Git checkout.
    import memory_federation_execution_guard as guard
    import memory_federation_full_attestation as full

    root = pathlib.Path(__file__).resolve().parents[1]
    os.chdir(root)
    output = pathlib.Path(os.environ.get("RUNNER_TEMP", "/tmp")) / DIRECTORY
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    candidate = guard._candidate()
    # Build outputs are not source evidence and must never enter the checked
    # source roots or the uploaded command-log directory.
    os.environ["CARGO_TARGET_DIR"] = str(output.parent / ("memory-federation-build-" + candidate["sha"]))
    inputs = guard._snapshot(candidate["sha"], candidate["tree"])
    commands = list(full.base.COMMANDS)
    record = {"schema": SCHEMA, "candidate": candidate, "inputs": inputs,
              "commandManifestSha256": hashlib.sha256(canonical(commands)).hexdigest(),
              "github": {key: os.environ.get(env, "") for key, env in GITHUB_FIELDS.items()},
              "commands": [], "conclusion": "running"}
    path = output / "execution.json"
    atomic_write(path, record)
    replacements = {"<guard-state>": str(output / "guard.json"),
                    "<tested-sha>": candidate["sha"], "<tested-tree>": candidate["tree"],
                    "<capacity-metrics.json>": str(output / "capacity.json")}
    previous_handlers = {}

    def interrupt(signum, _frame):
        # A second TERM/INT must not interrupt process cleanup or the atomic
        # failure-receipt write. Restore the caller's handlers before returning.
        for watched in (signal.SIGTERM, signal.SIGINT):
            signal.signal(watched, signal.SIG_IGN)
        raise ExecutionInterrupted(signum)

    try:
        for watched in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[watched] = signal.signal(watched, interrupt)
        for index, command in enumerate(commands):
            expanded = command
            for placeholder, value in replacements.items():
                expanded = expanded.replace(placeholder, shlex.quote(value))
            entry = command_record(index, command, expanded, root / location(command), output)
            record["commands"].append(entry)
            atomic_write(path, record)
            if command_failed(entry):
                break
        record["finalInputs"] = guard._snapshot(candidate["sha"], candidate["tree"])
        record["conclusion"] = "success" if (
            len(record["commands"]) == len(commands) and
            all(not command_failed(row) for row in record["commands"]) and
            record["finalInputs"] == inputs) else "failure"
    except Exception as error:
        record["conclusion"] = "failure"
        record["error"] = f"{type(error).__name__}: {error}"
    finally:
        try:
            metrics = output / "capacity.json"
            if metrics.is_file() and not metrics.is_symlink():
                record["capacityMetricsSha256"] = digest(metrics)
            atomic_write(path, record)
        finally:
            for watched, handler in previous_handlers.items():
                signal.signal(watched, handler)
    print(f"execution receipt: {path}; conclusion={record['conclusion']}", flush=True)
    return 0 if record["conclusion"] == "success" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run"])
    parser.parse_args()
    try:
        raise SystemExit(run())
    except ExecutionError as error:
        raise SystemExit(f"FAIL_MEMORY_FEDERATION_EXECUTION: {error}") from error
