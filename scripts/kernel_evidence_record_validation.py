"""Validate bounded, same-run kernel.evidence command records and their logs.

This is repository execution validation, not external acceptance or a signature
verifier. The CI runner and the reviewed command plan remain the trust boundary.
"""

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any

MAX_RECORD_BYTES = 1024 * 1024
MAX_LOG_BYTES = 64 * 1024 * 1024
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
EXPECTED_COMMANDS = {
    "evidence-tests.json": [
        "bash",
        "-lc",
        "cd codex-rs && cargo test --locked -p codex-hepta-evidence",
    ],
    "agentd-product-test.json": [
        "bash",
        "-lc",
        "cd codex-rs && cargo test --locked -p codex-hepta-agentd --lib "
        "--test kernel_evidence_product --test kernel_evidence_profile "
        "--test kernel_evidence_paging_product --test kernel_evidence_publication_cli",
    ],
    "lane-a-truth.json": ["python3", "scripts/verify_lane_a_foundation.py", "verify"],
    "docs.json": ["python3", "scripts/hepta-docs.py", "verify"],
    "implementation-maps.json": [
        "python3",
        "scripts/hepta-implementation-maps.py",
        "verify",
    ],
}
TEST_RECORDS = frozenset({"evidence-tests.json", "agentd-product-test.json"})


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON field: {key}")
        value[key] = item
    return value


def _nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def read_bounded_file(root: Path, name: str, maximum: int) -> bytes:
    """Read a flat regular file without following links or blocking on a FIFO."""
    if not isinstance(name, str) or not name or name in {".", ".."}:
        raise ValueError("a nonempty flat filename is required")
    if any(character in name for character in ("/", "\\", ":", "\x00")):
        raise ValueError("record and log paths must be flat filenames")
    path = root / name
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError("record and log files must be regular, unlinked files")
    if not 0 < before.st_size <= maximum:
        raise ValueError("record or log size is outside its bound")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise ValueError("record or log identity changed while opening")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("record or log was replaced while opening")
        data = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    current = path.lstat()
    identity = lambda item: (
        item.st_dev,
        item.st_ino,
        item.st_size,
        item.st_mtime_ns,
        item.st_nlink,
    )
    if identity(before) != identity(after) or identity(after) != identity(current):
        raise ValueError("record or log changed while reading")
    if len(data) != before.st_size or len(data) > maximum:
        raise ValueError("record or log size changed while reading")
    return data


def _is_zero(value: Any) -> bool:
    return type(value) is int and value == 0


def inspect_execution_record(
    root: Path,
    name: str,
    *,
    expected: dict[str, str],
    identity: dict[str, Any],
    working_directory: str,
) -> dict[str, Any]:
    """Return a failed entry for every malformed input; never default to pass."""
    entry: dict[str, Any] = {
        "path": name,
        "present": False,
        "sha256": None,
        "bytes": None,
        "status": "missing",
        "exitCode": None,
        "commandExitCode": None,
        "log": None,
        "error": None,
        "passed": False,
    }
    try:
        raw = read_bounded_file(root, name, MAX_RECORD_BYTES)
        entry.update(
            present=True, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw)
        )
        record = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_nonfinite
        )
        if not isinstance(record, dict):
            raise ValueError("record root must be an object")
        entry.update(
            status=record.get("status", "malformed"),
            exitCode=record.get("exit_code"),
            commandExitCode=record.get("command_exit_code"),
        )
        if (
            type(record.get("schema_version")) is not int
            or record["schema_version"] != 1
        ):
            raise ValueError("unsupported record schema")
        if any(record.get(key) != value for key, value in expected.items()):
            raise ValueError("record candidate, lane, run, attempt or job differs")
        if record.get("command") != EXPECTED_COMMANDS[name]:
            raise ValueError("record does not execute the required command")
        if record.get("working_directory") != working_directory:
            raise ValueError("record has a different working directory")
        for boundary in ("before", "after"):
            observed = record.get(boundary)
            if (
                not isinstance(observed, dict)
                or observed != identity
                or observed.get("dirty") is not False
            ):
                raise ValueError("record lacks matching clean before/after identity")
        if (
            expected["lane"] == "base-merge"
            and record.get("recomputed_merge_tree") != identity["tree"]
        ):
            raise ValueError("record lacks the recomputed deterministic merge tree")
        if record.get("status") != "passed" or record.get("error") not in (None, ""):
            raise ValueError("execution did not complete successfully")
        if not all(
            _is_zero(record.get(key))
            for key in (
                "exit_code",
                "command_exit_code",
                "returncode",
                "observed_failed_tests",
            )
        ):
            raise ValueError("exit or failed-test counts are not integer zero")
        if (
            record.get("timed_out") is not False
            or record.get("output_limit_exceeded") is not False
        ):
            raise ValueError("execution timeout/output state is absent or failed")
        passed_tests = record.get("observed_passed_tests")
        minimum = 1 if name in TEST_RECORDS else 0
        if type(passed_tests) is not int or passed_tests < minimum:
            raise ValueError("required passing tests were not observed")
        started = datetime.fromisoformat(record["started_at"])
        finished = datetime.fromisoformat(record["finished_at"])
        if (
            started.utcoffset() is None
            or finished.utcoffset() is None
            or finished < started
        ):
            raise ValueError("execution timestamps are not ordered and timezone-aware")
        if (finished - datetime.now(timezone.utc)).total_seconds() > 300:
            raise ValueError("execution timestamp is in the future")
        elapsed = record.get("elapsed_seconds")
        if (
            type(elapsed) not in (int, float)
            or not math.isfinite(elapsed)
            or elapsed < 0
        ):
            raise ValueError("execution duration is invalid")
        log_name = record.get("log_file")
        log = read_bounded_file(root, log_name, MAX_LOG_BYTES)
        digest = hashlib.sha256(log).hexdigest()
        entry["log"] = {
            "path": log_name,
            "present": True,
            "sha256": digest,
            "bytes": len(log),
        }
        if type(record.get("log_bytes")) is not int or record["log_bytes"] != len(log):
            raise ValueError("log byte count differs from execution record")
        if (
            not isinstance(record.get("log_sha256"), str)
            or not DIGEST.fullmatch(record["log_sha256"])
            or record["log_sha256"] != digest
        ):
            raise ValueError("log digest differs from execution record")
        entry["passed"] = True
    except FileNotFoundError as error:
        entry.update(status="missing", error=str(error))
    except (
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
        KeyError,
        RecursionError,
    ) as error:
        entry.update(status="rejected", error=str(error))
    return entry
