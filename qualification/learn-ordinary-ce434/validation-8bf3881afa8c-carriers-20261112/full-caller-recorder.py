#!/usr/bin/env python3
"""Record the fixed full caller proof; never signal a process."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
import tomllib
import uuid

SOURCE_SHA = "8bf3881afa8cccff286fc58909995c96f3e0b260"
SOURCE_TREE = "c8730bab75eabe47a3b0b3260a6203a0d86d1443"
PINS = {
    "CALLERS.toml": "95c8261a6c3eec23d038ba5aec754d618731d222",
    "scripts/verify_hepta_callers.py": "c66fb1f90a61deaa6461f0c7155209ed32903e62",
    "scripts/hepta_typed_callers.py": "e23bb8aa42241b429ef5dbce5a4660853b66eb2f",
    "scripts/hepta_ci_exec.py": "c9434b3a4afb31f80e323d543936386a2fa738de",
    ".github/workflows/hepta-daemon-learning-native.yml":
        "380b6d50f871e7eaa5a8bbc12fb75e59d45b868d",
    "AGENTS.md": "faa57cc0db48123e1011f1eb47692cd3bbbcfc3a",
}
EXPECTED_RUST_FILES = 6655
EXPECTED_BOUNDARIES = 737
EXPECTED_PROTECTED_RECORDS = 506
PHASES = (("self-test", 300), ("verify", 4800))
ORIGINAL_OUTPUT_LIMIT = 64 * 1024 * 1024
MAX_OBSERVATION_SECONDS = 10800
POLL_SECONDS = 0.25
HEARTBEAT_SECONDS = 10


class RecordingRejected(Exception):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def require(condition, code):
    if not condition:
        raise RecordingRejected(code)


def git_blob(data):
    return hashlib.sha1(
        b"blob " + str(len(data)).encode("ascii") + b"\0" + data
    ).hexdigest()


def write_bytes(path, data):
    with path.open("xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def save_json(path, value, *, exclusive=False):
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if exclusive:
        write_bytes(path, data)
        return
    descriptor, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    pending = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)


def file_snapshot(path, *, complete):
    """Hash a fixed prefix using a separate descriptor."""
    before = path.stat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
            "record_file_not_private_regular")
    remaining = before.st_size
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while remaining:
            chunk = source.read(min(1024 * 1024, remaining))
            require(bool(chunk), "record_file_shrank_during_hash")
            remaining -= len(chunk)
            digest.update(chunk)
    after = path.stat()
    stable = (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns
    ) == (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
    )
    require(not complete or stable, "terminal_log_changed_during_hash")
    return {
        "file": path.name,
        "prefix_bytes": before.st_size,
        "prefix_sha256": digest.hexdigest(),
        "size_after_snapshot": after.st_size,
        "stable_during_snapshot": stable,
        "complete": bool(complete and stable),
    }


def git_output(repo, *args):
    result = subprocess.run(
        ["git", "--no-optional-locks", "-c", "core.fsmonitor=false",
         "-c", "core.untrackedCache=false", *args],
        cwd=repo, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        raise RecordingRejected(
            "git_identity_failed:" + str(result.returncode) + ":" + args[0]
        )
    return result.stdout


def source_snapshot(repo, records, label):
    head = git_output(repo, "rev-parse", "HEAD").decode("ascii").strip()
    tree = git_output(repo, "rev-parse", "HEAD^{tree}").decode("ascii").strip()
    status = git_output(
        repo, "status", "--porcelain=v1", "--untracked-files=all"
    )
    write_bytes(records / (label + ".status.txt"), status)
    pins = {}
    manifest_bytes = None
    for relative, expected in PINS.items():
        path = repo / relative
        require(path.is_file() and not path.is_symlink(),
                "source_pin_not_regular:" + relative)
        data = path.read_bytes()
        pins[relative] = {
            "git_blob": git_blob(data),
            "expected_git_blob": expected,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        if relative == "CALLERS.toml":
            manifest_bytes = data
    value = {
        "head": head, "tree": tree, "clean": not status,
        "status_file": label + ".status.txt",
        "status_bytes": len(status),
        "status_sha256": hashlib.sha256(status).hexdigest(),
        "pins": pins,
    }
    save_json(records / (label + ".json"), value, exclusive=True)
    require(head == SOURCE_SHA and tree == SOURCE_TREE and not status,
            "fixed_clean_source_required")
    require(all(row["git_blob"] == row["expected_git_blob"]
                for row in pins.values()), "fixed_source_pin_mismatch")
    manifest = tomllib.loads(manifest_bytes.decode("utf-8"))
    roots = manifest["source_roots"]
    files = []
    for relative_root in roots:
        source_root = (repo / relative_root).resolve()
        require(source_root.is_relative_to(repo), "source_root_escapes_repo")
        for path in source_root.rglob("*.rs"):
            require(not path.is_symlink(), "rust_source_symlink")
            files.append(path)
    names = [path.relative_to(repo).as_posix() for path in sorted(files)]
    path_bytes = ("\n".join(names) + "\n").encode("utf-8")
    write_bytes(records / (label + ".rust-paths.txt"), path_bytes)
    boundaries = manifest["boundary"]
    protected = manifest["protected_file"]
    inventory = {
        "source_roots": roots,
        "ignored_path_fragments": manifest["ignored_path_fragments"],
        "rust_files": len(names),
        "rust_paths_file": label + ".rust-paths.txt",
        "rust_paths_sha256": hashlib.sha256(path_bytes).hexdigest(),
        "boundary_records": len(boundaries),
        "boundary_ids": [row["id"] for row in boundaries],
        "required_boundary_ids": manifest["privileged_inventory"]["required_boundary_ids"],
        "protected_records": len(protected),
        "protected_paths_with_multiplicity": [row["path"] for row in protected],
    }
    save_json(records / (label + ".inventory.json"), inventory, exclusive=True)
    if label == "source-before":
        write_bytes(records / "CALLERS.source.toml", manifest_bytes)
    require(len(names) == EXPECTED_RUST_FILES, "unexpected_rust_inventory")
    require(len(boundaries) == EXPECTED_BOUNDARIES, "unexpected_boundary_inventory")
    require(len(protected) == EXPECTED_PROTECTED_RECORDS,
            "unexpected_protected_record_inventory")
    return value, inventory


def validate_receipt(phase, stdout_path, inventory):
    value = json.loads(stdout_path.read_bytes())
    if phase == "self-test":
        require(value.get("status") == "PASS_HEPTA_CALLER_PROOF_SELF_TEST",
                "self_test_receipt_missing")
        return {"status": value["status"]}
    require(value.get("schema") == "hepta.caller-proof-receipt.v2"
            and value.get("status") == "PASS_HEPTA_CALLER_CLOSED_SET"
            and value.get("authorityGranted") is False,
            "full_caller_receipt_missing")
    require(value.get("rustFilesScanned") == EXPECTED_RUST_FILES,
            "receipt_rust_inventory_mismatch")
    require([row["id"] for row in value["boundaries"]]
            == inventory["boundary_ids"], "receipt_boundary_inventory_mismatch")
    require(value.get("privilegedInventory")
            == sorted(inventory["required_boundary_ids"]),
            "receipt_required_inventory_mismatch")
    require(value.get("protectedFiles")
            == inventory["protected_paths_with_multiplicity"],
            "receipt_complete_protected_records_mismatch")
    return {
        "status": value["status"],
        "rust_files": value["rustFilesScanned"],
        "boundary_records": len(value["boundaries"]),
        "protected_records": len(value["protectedFiles"]),
        "authority_granted": False,
    }


def run_phase(repo, records, phase, budget, inventory, observation_deadline, run_id):
    command = ["python3", "scripts/verify_hepta_callers.py", phase]
    stdout_path = records / (phase + ".stdout.log")
    stderr_path = records / (phase + ".stderr.log")
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["TMPDIR"] = str(records / "tmp")
    started = time.monotonic()
    started_at = utc_now()
    gate = None
    actual_exit = None
    original_complete = False
    heartbeat = 0.0

    with stdout_path.open("xb", buffering=0) as stdout, \
            stderr_path.open("xb", buffering=0) as stderr:
        process = subprocess.Popen(
            command, cwd=repo, env=environment, stdin=subprocess.DEVNULL,
            stdout=stdout, stderr=stderr, start_new_session=True,
        )
        ownership = {
            "run_id": run_id, "phase": phase, "command": command,
            "child_pid": process.pid, "recorder_pid": os.getpid(),
            "started_at": started_at, "started_monotonic": started,
            "source_sha": SOURCE_SHA, "source_tree": SOURCE_TREE,
            "budget_seconds": budget,
            "classification_exit_is_not_child_exit": True,
        }
        save_json(records / (phase + ".started.json"), ownership, exclusive=True)
        while True:
            now = time.monotonic()
            elapsed = now - started
            actual_exit = process.poll()
            total_output = os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size
            if gate is None and (elapsed >= budget or total_output > ORIGINAL_OUTPUT_LIMIT):
                timed_out = elapsed >= budget
                gate = {
                    **ownership,
                    "status": ("original_budget_timeout" if timed_out
                               else "original_output_limit_exceeded"),
                    "classification_exit_code": 124 if timed_out else 1,
                    "observed_elapsed_seconds": elapsed,
                    "child_exit_at_observation": actual_exit,
                    "logs": [
                        file_snapshot(stdout_path, complete=False),
                        file_snapshot(stderr_path, complete=False),
                    ],
                }
                save_json(records / (phase + ".gate.json"), gate, exclusive=True)
            if actual_exit is not None:
                actual_exit = process.wait()
                original_complete = True
                break
            if now >= observation_deadline:
                break
            if now - heartbeat >= HEARTBEAT_SECONDS:
                save_json(records / (phase + ".status.json"), {
                    **ownership,
                    "status": "observing_after_gate_failure" if gate else "running",
                    "elapsed_seconds": elapsed,
                    "stdout_bytes": os.fstat(stdout.fileno()).st_size,
                    "stderr_bytes": os.fstat(stderr.fileno()).st_size,
                    "child_exit": None,
                    "gate_status": gate["status"] if gate else "pending",
                    "maximum_run_observation_seconds": MAX_OBSERVATION_SECONDS,
                })
                heartbeat = now
            time.sleep(min(POLL_SECONDS, max(0.0, observation_deadline - now)))

        finished = time.monotonic()
        stdout.flush()
        stderr.flush()
        os.fsync(stdout.fileno())
        os.fsync(stderr.fileno())
        logs = [
            file_snapshot(stdout_path, complete=original_complete),
            file_snapshot(stderr_path, complete=original_complete),
        ]

    receipt = None
    receipt_error = None
    if original_complete and actual_exit == 0 and total_output <= ORIGINAL_OUTPUT_LIMIT:
        try:
            receipt = validate_receipt(phase, stdout_path, inventory)
        except Exception as error:
            receipt_error = {"type": type(error).__name__, "code": str(error)
                             if isinstance(error, RecordingRejected) else "receipt_parse_failed"}
    if gate is None:
        passed = original_complete and actual_exit == 0 and receipt is not None
        gate = {
            **ownership,
            "status": ("passed" if passed else "observation_limit" if not
                       original_complete else "original_command_or_receipt_failed"),
            "classification_exit_code": 0 if passed else 124 if not original_complete else 1,
            "observed_elapsed_seconds": finished - started,
            "child_exit_at_observation": actual_exit,
            "logs": logs,
        }
        save_json(records / (phase + ".gate.json"), gate, exclusive=True)

    result = {
        **ownership,
        "status": "terminal" if original_complete else "observation_limit_child_not_reaped",
        "finished_observing_at": utc_now(),
        "elapsed_seconds": finished - started,
        "original_process_complete": original_complete,
        "actual_child_exit": actual_exit if original_complete else None,
        "gate_status": gate["status"],
        "gate_classification_exit": gate["classification_exit_code"],
        "late_success_does_not_change_gate": True,
        "logs": logs, "receipt": receipt, "receipt_error": receipt_error,
        "signals_sent": [],
    }
    save_json(records / (phase + ".original.json"), result, exclusive=True)
    save_json(records / (phase + ".status.json"), result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    records = args.evidence_dir
    require(repo.is_dir(), "existing_worktree_required")
    require(records.is_absolute(), "absolute_new_evidence_directory_required")
    parent = records.parent.resolve(strict=True)
    require(parent == records.parent and not records.is_relative_to(repo),
            "evidence_parent_must_be_real_and_outside_source")
    require(not records.exists() and not records.is_symlink(),
            "evidence_directory_must_not_exist")
    os.mkdir(records, mode=0o700)
    os.mkdir(records / "tmp", mode=0o700)
    run_id = uuid.uuid4().hex
    started = time.monotonic()
    result = {
        "schema": "hepta.original-full-caller-record.v1",
        "run_id": run_id, "source_sha": SOURCE_SHA, "source_tree": SOURCE_TREE,
        "worktree": str(repo), "evidence_directory": str(records),
        "started_at": utc_now(), "recorder_pid": os.getpid(),
        "status": "running", "phases": [],
        "original_budgets": dict(PHASES),
        "original_output_limit_bytes": ORIGINAL_OUTPUT_LIMIT,
        "maximum_run_observation_seconds": MAX_OBSERVATION_SECONDS,
        "ordinary_acceptance": 0, "signals_sent": [],
    }
    save_json(records / "started.json", result, exclusive=True)
    exit_code = 2
    before = after = None
    inventory_before = inventory_after = None
    try:
        before, inventory_before = source_snapshot(repo, records, "source-before")
        result["source_before"] = before
        for phase, budget in PHASES:
            if time.monotonic() >= started + MAX_OBSERVATION_SECONDS:
                raise RecordingRejected("observation_limit_before_next_phase")
            observed = run_phase(
                repo, records, phase, budget, inventory_before,
                started + MAX_OBSERVATION_SECONDS, run_id,
            )
            result["phases"].append(observed)
            save_json(records / "status.json", result)
            if observed["gate_classification_exit"] != 0:
                break
        after, inventory_after = source_snapshot(repo, records, "source-after")
        result["source_after"] = after
        before_identity = dict(before)
        after_identity = dict(after)
        before_identity.pop("status_file")
        after_identity.pop("status_file")
        require(before_identity == after_identity, "source_identity_or_pins_changed")
        before_inventory = dict(inventory_before)
        after_inventory = dict(inventory_after)
        before_inventory.pop("rust_paths_file")
        after_inventory.pop("rust_paths_file")
        require(before_inventory == after_inventory, "source_inventory_changed")
        complete = len(result["phases"]) == 2 and all(
            row["original_process_complete"] and row["gate_classification_exit"] == 0
            for row in result["phases"]
        )
        exit_code = 0 if complete else (
            124 if any(row["gate_classification_exit"] == 124
                       for row in result["phases"]) else 1
        )
        result["status"] = "passed_original_gates" if complete else "failed_original_gates"
    except Exception as error:
        result["status"] = "recorder_rejected_or_incomplete"
        result["error"] = {
            "type": type(error).__name__,
            "code": str(error) if isinstance(error, RecordingRejected)
                    else "recording_failed",
        }
    finally:
        if after is None:
            try:
                saved_after = records / "source-after.json"
                if saved_after.exists():
                    after = json.loads(saved_after.read_bytes())
                else:
                    after, inventory_after = source_snapshot(repo, records, "source-after")
                result["source_after"] = after
            except Exception as error:
                result["source_after_error"] = {"type": type(error).__name__}
        result["finished_observing_at"] = utc_now()
        result["elapsed_seconds"] = time.monotonic() - started
        result["exit_code"] = exit_code
        save_json(records / "result.json", result, exclusive=True)
        save_json(records / "status.json", result)
        result_bytes = (records / "result.json").read_bytes()
        write_bytes(records / "result.sha256",
                    (hashlib.sha256(result_bytes).hexdigest() + "\n").encode("ascii"))
        print(json.dumps({
            "run_id": run_id, "status": result["status"], "exit_code": exit_code,
            "result_file": str(records / "result.json"),
            "result_sha256": hashlib.sha256(result_bytes).hexdigest(),
        }, sort_keys=True), flush=True)
    return exit_code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RecordingRejected as error:
        print(json.dumps({"status": "not_dispatched", "code": str(error)}), flush=True)
        raise SystemExit(2)
