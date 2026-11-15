#!/usr/bin/env python3
"""Qualify the typed native HIA token-budget ABI with full-width u64 inputs.

Boundary and deterministic random cases cover both valid operations. Unknown
operations must trap in isolated children with core dumps disabled. Every u64
value is a valid operand, and u64::MAX is a valid result, never an error code.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import ctypes
import hashlib
import json
from pathlib import Path
import random
import signal
import struct
import subprocess
import sys
import tempfile
from threading import Barrier


ROOT = Path(__file__).resolve().parents[2]
HIA_SOURCE = ROOT / "hia/token_budget.hepta"
SYMBOL = "codex_hia_token_budget"
U64_MAX = (1 << 64) - 1
RANDOM_SEED = 0x544F4B454E425544
RANDOM_CASES = 20_000
WORKERS, ITERATIONS = 8, 1_024
TRAP_PROBE = """
import ctypes
import os
import resource
import sys

resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
prctl = ctypes.CDLL(None, use_errno=True).prctl
prctl.argtypes = [ctypes.c_int] + [ctypes.c_ulong] * 4
prctl.restype = ctypes.c_int
if prctl(4, 0, 0, 0, 0) != 0 or prctl(3, 0, 0, 0, 0) != 0:
    raise RuntimeError("could not disable child core dumps")
if resource.getrlimit(resource.RLIMIT_CORE) != (0, 0):
    raise RuntimeError("child core size limit is not zero")
library = ctypes.CDLL(sys.argv[1])
function = library.codex_hia_token_budget
function.argtypes = [ctypes.c_uint64, ctypes.c_uint64]
function.restype = ctypes.c_uint64
os.write(1, b"core=0;dumpable=0\\n")
returned = function(int(sys.argv[2]), int(sys.argv[3]))
raise RuntimeError(f"unknown operation returned {returned} instead of trapping")
"""


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(function, value, operation):
    # Python's arbitrary precision computes the specification independently
    # of the native overflow-detection branches and machine integer width.
    expected = min(value * 4, U64_MAX) if operation == 0 else min(value + 3, U64_MAX) // 4
    actual = function(value, operation)
    if actual != expected:
        raise RuntimeError(
            f"scalar mismatch: value={value:#018x}, operation={operation}, "
            f"actual={actual}, expected={expected}"
        )
    return actual


def verify(library_dir, report):
    build_path = library_dir / "build.json"
    build = json.loads(build_path.read_text())
    if build.get("status") != "built" or build.get("compiler_fixed_point") is not True:
        raise RuntimeError("the typed ABI requires an actual fixed-point HIA build")
    component = build["modules"]["token_budget"]
    abi = component["codex_link_abi"]
    library_path = library_dir / f"lib{SYMBOL}.so"
    archive_path = library_dir / f"lib{SYMBOL}.a"
    if abi["symbol"] != SYMBOL:
        raise RuntimeError("the typed ABI symbol differs from its build report")
    inputs = {
        "hia_source_sha256": sha256(HIA_SOURCE),
        "library_sha256": sha256(library_path),
        "archive_sha256": sha256(archive_path),
        "build_report_sha256": sha256(build_path),
        "test_source_sha256": sha256(Path(__file__)),
    }
    if component["source_sha256"] != inputs["hia_source_sha256"]:
        raise RuntimeError("the typed ABI artifact has a different HIA source")
    for kind in ("library", "archive"):
        if abi[f"{kind}_sha256"] != inputs[f"{kind}_sha256"]:
            raise RuntimeError(f"the typed ABI {kind} differs from its build report")
    report["inputs"] = inputs
    report["compiler_sha256"] = build["compiler_sha256"]
    library = ctypes.CDLL(str(library_path))
    function = library.codex_hia_token_budget
    function.argtypes = [ctypes.c_uint64, ctypes.c_uint64]
    function.restype = ctypes.c_uint64

    # These distinguish saturated addition from mathematical ceil(value/4),
    # and prove that MAX is accepted as both an operand and a successful result.
    explicit = [
        (0, 0, 0), (1, 0, 4), (17, 0, 68),
        (U64_MAX // 4, 0, U64_MAX - 3),
        (U64_MAX // 4 + 1, 0, U64_MAX), (U64_MAX, 0, U64_MAX),
        (0, 1, 0), (1, 1, 1), (4, 1, 1), (5, 1, 2),
        (U64_MAX - 3, 1, U64_MAX // 4),
        (U64_MAX - 2, 1, U64_MAX // 4),
        (U64_MAX - 1, 1, U64_MAX // 4),
        (U64_MAX, 1, U64_MAX // 4),
    ]
    for value, operation, expected in explicit:
        if check(function, value, operation) != expected:
            raise RuntimeError("an explicit full-width scalar result differs")
    report["explicit_calls"] = len(explicit)
    report["u64_max_is_valid_value_and_result"] = True

    boundaries = set(range(4_096)) | {U64_MAX - offset for offset in range(4_096)}
    centers = [1 << bit for bit in range(65)] + [U64_MAX // 4, U64_MAX - 3]
    for center in centers:
        boundaries.update(
            value for value in range(center - 8, center + 9) if 0 <= value <= U64_MAX
        )
    for value in sorted(boundaries):
        check(function, value, 0)
        check(function, value, 1)
    report["boundary_values"] = len(boundaries)
    report["boundary_calls"] = 2 * len(boundaries)

    rng = random.Random(RANDOM_SEED)
    random_digest = hashlib.sha256()
    for _ in range(RANDOM_CASES):
        value = rng.getrandbits(64)
        random_digest.update(struct.pack("<Q", value))
        check(function, value, 0)
        check(function, value, 1)
    report["random_values"] = RANDOM_CASES
    report["random_calls"] = 2 * RANDOM_CASES
    report["random_seed"] = RANDOM_SEED
    report["random_values_sha256"] = random_digest.hexdigest()

    barrier = Barrier(WORKERS)
    ordered_boundaries = sorted(boundaries)

    def concurrent_calls(worker):
        worker_rng = random.Random(RANDOM_SEED + worker + 1)
        barrier.wait(timeout=30)
        for iteration in range(ITERATIONS):
            value = (
                ordered_boundaries[(iteration + worker) % len(ordered_boundaries)]
                if iteration % 4 == 0 else worker_rng.getrandbits(64)
            )
            operation = (worker + iteration) & 1
            check(function, value, operation)
            check(function, value, operation ^ 1)
        return 2 * ITERATIONS

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        report["concurrent_calls"] = sum(pool.map(concurrent_calls, range(WORKERS)))
    report["concurrent_workers"] = WORKERS

    # High-bit modes that truncate to 0 or 1 must still trap. Children use a
    # fresh interpreter and no preexec_fn; they cannot change parent limits.
    invalid_operations = [2, 3, 255, 1 << 32, (1 << 32) + 1, 1 << 63, (1 << 63) + 1, U64_MAX]
    report["unknown_operation_traps"] = []
    with tempfile.TemporaryDirectory(prefix="codex-hia-token-budget-traps-") as directory:
        for operation in invalid_operations:
            for value in (0, U64_MAX):
                result = subprocess.run(
                    [sys.executable, "-I", "-S", "-c", TRAP_PROBE, str(library_path), str(value), str(operation)],
                    cwd=directory, capture_output=True, timeout=10,
                )
                passed = (
                    result.returncode == -signal.SIGILL
                    and result.stdout == b"core=0;dumpable=0\n"
                    and not result.stderr
                )
                report["unknown_operation_traps"].append({
                    "operation": operation, "value": value,
                    "returncode": result.returncode, "passed": passed,
                    "child_core_dumps_disabled": result.stdout == b"core=0;dumpable=0\n",
                })
                if not passed:
                    raise RuntimeError(
                        f"unknown operation did not produce the isolated SIGILL contract: "
                        f"operation={operation}, value={value}, status={result.returncode}, "
                        f"stdout={result.stdout!r}, stderr={result.stderr!r}"
                    )
        if list(Path(directory).iterdir()):
            raise RuntimeError("an invalid-operation child created unexpected files")
    report["successful_native_calls"] = sum(
        report[key] for key in ("explicit_calls", "boundary_calls", "random_calls", "concurrent_calls")
    )
    report["unknown_operation_trap_calls"] = len(report["unknown_operation_traps"])
    report["native_calls"] = report["successful_native_calls"] + report["unknown_operation_trap_calls"]
    report["passed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = {
        "schema": "codex.hia.token-budget-abi.v1", "passed": False, "skipped": 0,
        "abi": "SysV AMD64 (value:u64, operation:u64) -> u64",
        "operations": {"0": "min(value * 4, u64::MAX)", "1": "min(value + 3, u64::MAX) / 4", "other": "SIGILL"},
    }
    try:
        verify(args.library_dir.resolve(strict=True), report)
    except (OSError, RuntimeError, AttributeError, KeyError, ValueError, subprocess.TimeoutExpired) as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(report["error"], file=sys.stderr)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
