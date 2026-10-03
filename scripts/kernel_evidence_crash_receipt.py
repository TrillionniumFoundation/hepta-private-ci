#!/usr/bin/env python3
"""Execute one crash-consistency scenario and retain a canonical receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time

OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
SCENARIOS = (
    "sqlite_process_kill",
    "wal_rollback_journal",
    "fsync_rename_directory_fsync",
    "disk_full",
    "damaged_frontier",
    "damaged_database",
    "stale_valid_frontier",
    "legacy_import",
    "simultaneous_database_frontier_rollback",
    "backup_restore",
    "multi_process_contention",
    "repair_append_concurrency",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".crash-receipt-")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    parser.add_argument("--tested-sha", required=True)
    parser.add_argument("--target-triple", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if OID.fullmatch(args.tested_sha) is None or not args.target_triple:
        parser.error("tested SHA and target triple must be canonical")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("one command is required after --")

    args.log.parent.mkdir(parents=True, exist_ok=True)
    started = int(time.time() * 1000)
    timed_out = False
    with args.log.open("wb") as log:
        try:
            completed = subprocess.run(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=args.timeout_seconds,
                check=False,
            )
            exit_code = completed.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = 124
    finished = int(time.time() * 1000)
    receipt: dict[str, object] = {
        "schemaVersion": 1,
        "module": "kernel.evidence",
        "scenario": args.scenario,
        "testedSha": args.tested_sha,
        "targetTriple": args.target_triple,
        "status": "passed" if exit_code == 0 and not timed_out else "failed",
        "command": shlex.join(command),
        "exitCode": exit_code,
        "timedOut": timed_out,
        "startedAtUnixMs": started,
        "finishedAtUnixMs": finished,
        "logPath": str(args.log),
        "logSha256": sha256_file(args.log),
        "qualificationGranted": False,
    }
    atomic_json(args.output, receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0 if exit_code == 0 and not timed_out else 1


if __name__ == "__main__":
    raise SystemExit(main())
