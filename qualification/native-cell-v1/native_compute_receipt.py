#!/usr/bin/env python3
"""Strict read-only auditing of V6 original native CPU timing JSON.

Only explicit physical execution on an identified host creates timing evidence.
This consumer verifies a schema and source bytes. It is NOT host attestation,
independent measurement or any authorization for OS actions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat

SCHEMA = "hepta.nativecell.cpu-local-vs-ipc.v1"
RECEIPT_SCHEMA = "hepta.nativecell.cpu-source-receipt.v1"
KEYS = {
    "schema", "measured_calls_per_repetition", "warmup_calls", "repetitions_per_arm",
    "input_frame_bytes", "result_frame_bytes", "kernel", "in_process", "two_process",
    "same_original_input_and_kernel", "all_original_outputs_match", "separate_processes",
    "mcp_comparison", "os_ui_effect", "model_executed", "jit_or_executable_memory",
    "peer_authentication_verified", "production_authorized",
}
METRICS = {"setup_ns", "p50_ns", "p95_ns", "p99_ns"}
TRUE_FLAGS = {"same_original_input_and_kernel", "all_original_outputs_match", "separate_processes"}
FALSE_FLAGS = {
    "mcp_comparison", "os_ui_effect", "model_executed", "jit_or_executable_memory",
    "peer_authentication_verified", "production_authorized",
}


class AuditError(ValueError):
    pass


def no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise AuditError("ambiguous duplicate JSON key")
        output[key] = value
    return output


def _reject_constant(value: str) -> None:
    raise AuditError(f"non-finite literal: {value}")


def read_regular_file(path: Path, maximum_bytes: int = 131_072) -> bytes:
    # Avoid symlink / FIFO and changed-in-read input. No network or artifact download.
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum_bytes:
            raise AuditError("source must be bounded regular file")
        data = handle.read(maximum_bytes + 1)
        after = os.fstat(handle.fileno())
        if len(data) != before.st_size or len(data) > maximum_bytes or (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns
        ) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
        ):
            raise AuditError("source changed during read or exceeds bound")
        return data


def load_original(path: Path, count: int) -> tuple[dict[str, object], str]:
    raw = read_regular_file(path)
    try:
        row = json.loads(raw, object_pairs_hook=no_duplicate_keys, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise AuditError("invalid original JSON") from exc
    if type(row) is not dict or set(row) != KEYS:
        raise AuditError("unexpected benchmark schema or keys")
    if row["schema"] != SCHEMA or row["kernel"] != "compiled-q24-dot16":
        raise AuditError("wrong source-defined benchmark identity")
    numeric = {
        "measured_calls_per_repetition": count,
        "warmup_calls": 16,
        "repetitions_per_arm": 2,
        "input_frame_bytes": 256,
        "result_frame_bytes": 64,
    }
    for key, target in numeric.items():
        if type(row[key]) is not int or row[key] != target:
            raise AuditError("wrong bounded original workload")
    for key in TRUE_FLAGS:
        if row[key] is not True:
            raise AuditError("original output verification was not successful")
    for key in FALSE_FLAGS:
        if row[key] is not False:
            raise AuditError("research result forged production or effect claims")
    for arm in ("in_process", "two_process"):
        runs = row[arm]
        if type(runs) is not list or len(runs) != 2:
            raise AuditError("original repeated CPU records incomplete")
        for run in runs:
            if type(run) is not dict or set(run) != METRICS:
                raise AuditError("missing performance metrics")
            if any(type(value) is not int or value < 0 for value in run.values()):
                raise AuditError("invalid performance metric")
            if (run["p50_ns"] == 0 or run["p50_ns"] > run["p95_ns"]
                    or run["p95_ns"] > run["p99_ns"]):
                raise AuditError("invalid percentile ordering")
            if arm == "in_process" and run["setup_ns"] != 0:
                raise AuditError("in-process original setup must not be charged")
            if arm == "two_process" and run["setup_ns"] <= 0:
                raise AuditError("missing original OS subprocess startup")
    return row, hashlib.sha256(raw).hexdigest()


def make_receipt(
    smoke: Path, full: Path, source: Path, head: str, architecture: str,
) -> dict[str, object]:
    if len(head) != 40 or any(c not in "0123456789abcdef" for c in head):
        raise AuditError("missing immutable Git source SHA")
    if architecture not in ("x86_64", "aarch64"):
        raise AuditError("unregistered CPU host architecture")
    small, small_sha = load_original(smoke, 64)
    large, large_sha = load_original(full, 1024)
    if small_sha == large_sha:
        raise AuditError("two distinct measurements are required")
    rust_bytes = read_regular_file(source, maximum_bytes=250_000)
    return {
        "schema": RECEIPT_SCHEMA,
        "exact_head_sha": head,
        "runner_architecture": architecture,
        "rust_benchmark_source_sha256": hashlib.sha256(rust_bytes).hexdigest(),
        "arms": {
            "smoke_64": {"raw_sha256": small_sha, "observed": small},
            "full_1024": {"raw_sha256": large_sha, "observed": large},
        },
        "only_declared_compiled_native_cpu_work": True,
        "host_cryptographically_attested": False,
        "mcp_or_external_computer_use_compared": False,
        "os_ui_effect_authorized": False,
        "production_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", type=Path, required=True)
    parser.add_argument("--full", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--architecture", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    receipt = make_receipt(args.smoke, args.full, args.source, args.head, args.architecture)
    # Exclusive create; never overwrite another evidence capture. Caller selects
    # an owned, private output directory. This does not authenticate capture.
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    descriptor = os.open(args.out, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, sort_keys=True, allow_nan=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps({
        "head": args.head, "architecture": args.architecture,
        "source_sha256": receipt["rust_benchmark_source_sha256"],
        "original_roundtrips": [64, 1024],
        "mcp_comparison": False, "production_authorized": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
