#!/usr/bin/env python3
"""Create and verify explicit execution stages and their retained logs.

Recorded exit codes and hashes are source-controlled execution witnesses. They
prove local evidence consistency; independent acceptance needs its own issuer.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALID = {"passed", "failed", "not_run"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repository_path(value: str) -> Path:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"stage path escapes root: {value!r}")
    resolved = ROOT / path
    if not resolved.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError(f"stage path resolves outside root: {value!r}")
    return resolved


def verify_value(
    value: object, expected_stage: str, expected_identity: dict | None = None
) -> dict:
    if not isinstance(value, dict) or (
        value.get("schema") != "hepta.learning-operator-stage.v1"
        or type(value.get("schemaVersion")) is not int
        or value.get("schemaVersion") != 1
        or value.get("module") != "learning.operator"
        or value.get("stage") != expected_stage
    ):
        raise ValueError(f"malformed stage receipt: {expected_stage}")
    identity = value.get("executionIdentity")
    if (
        not isinstance(identity, dict)
        or set(identity) != {"sourceSha", "sourceTree", "workflowRunId", "runAttempt"}
        or any(
            not isinstance(identity.get(key), str)
            or re.fullmatch(r"[0-9a-f]{40}", identity[key]) is None
            or identity[key] == "0" * 40
            for key in ("sourceSha", "sourceTree")
        )
        or any(
            not isinstance(identity.get(key), str) or not identity[key]
            for key in ("workflowRunId", "runAttempt")
        )
        or expected_identity is not None
        and identity != expected_identity
    ):
        raise ValueError(f"stage execution identity mismatch: {expected_stage}")
    status = value.get("status")
    code = value.get("exitCode")
    if status not in VALID or (
        status == "passed"
        and (type(code) is not int or code != 0)
        or status == "failed"
        and (type(code) is not int or code == 0)
        or status == "not_run"
        and code is not None
    ):
        raise ValueError(f"stage status/exit code mismatch: {expected_stage}")
    command = value.get("command")
    reason = value.get("reason")
    if not isinstance(command, str) or not command or not isinstance(reason, str):
        raise ValueError(f"stage command/reason absent: {expected_stage}")
    if status != "passed" and not reason:
        raise ValueError(f"non-passing stage requires a reason: {expected_stage}")
    if (
        value.get("commandSha256")
        != hashlib.sha256(command.encode("utf-8")).hexdigest()
    ):
        raise ValueError(f"stage command hash drift: {expected_stage}")
    log = value.get("log")
    if log is None:
        if status != "not_run":
            raise ValueError(f"executed stage log absent: {expected_stage}")
        return value
    if not isinstance(log, dict) or not isinstance(log.get("path"), str):
        raise ValueError(f"malformed stage log: {expected_stage}")
    path = repository_path(log["path"])
    if not path.is_file():
        raise ValueError(f"stage log absent: {expected_stage}")
    if (
        log.get("present") is not True
        or log.get("sha256") != sha256(path)
        or type(log.get("bytes")) is not int
        or log.get("bytes") != path.stat().st_size
    ):
        raise ValueError(f"stage log hash/size drift: {expected_stage}")
    return value


def record(args: argparse.Namespace) -> None:
    output = repository_path(args.output)
    log = repository_path(args.log) if args.log else None
    payload = {
        "schema": "hepta.learning-operator-stage.v1",
        "schemaVersion": 1,
        "module": "learning.operator",
        "stage": args.stage,
        "executionIdentity": {
            "sourceSha": args.source_sha,
            "sourceTree": args.source_tree,
            "workflowRunId": args.workflow_run_id,
            "runAttempt": args.run_attempt,
        },
        "status": args.status,
        "exitCode": args.exit_code,
        "reason": args.reason,
        "command": args.command,
        "commandSha256": hashlib.sha256(args.command.encode("utf-8")).hexdigest(),
        "log": None
        if log is None
        else {
            "path": args.log,
            "present": log.is_file(),
            "sha256": sha256(log) if log.is_file() else None,
            "bytes": log.stat().st_size if log.is_file() else 0,
        },
    }
    verify_value(payload, args.stage)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def verify(args: argparse.Namespace) -> None:
    root = repository_path(args.directory)
    required = [value for value in args.required.split(",") if value]
    if not required or len(required) != len(set(required)):
        raise ValueError("required stage inventory must be nonempty and unique")
    non_passed = []
    for stage in required:
        if not stage.replace("_", "").isalnum():
            raise ValueError(f"invalid stage identifier: {stage}")
        path = root / f"{stage}.json"
        if not path.is_file():
            non_passed.append(f"{stage}=missing")
            continue
        value = verify_value(json.loads(path.read_text(encoding="utf-8")), stage)
        if value["status"] != "passed":
            non_passed.append(f"{stage}={value['status']}")
    if non_passed:
        raise SystemExit(
            "qualification stages are not all passed: " + ", ".join(non_passed)
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    write = subparsers.add_parser("record")
    write.add_argument("--stage", required=True)
    write.add_argument("--status", required=True, choices=sorted(VALID))
    for field in ("source-sha", "source-tree", "workflow-run-id", "run-attempt"):
        write.add_argument("--" + field, required=True)
    write.add_argument("--exit-code", type=int)
    write.add_argument("--reason", default="")
    write.add_argument("--command", required=True)
    write.add_argument("--log")
    write.add_argument("--output", required=True)
    check = subparsers.add_parser("verify")
    check.add_argument("--directory", required=True)
    check.add_argument("--required", required=True)
    args = parser.parse_args()
    if args.action == "record":
        record(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
