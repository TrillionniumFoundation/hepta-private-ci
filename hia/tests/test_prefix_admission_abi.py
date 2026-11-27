#!/usr/bin/env python3
"""Qualify the native prefix-count admission ABI with independent u64 cases.

The scalar takes command_count and pattern_count and returns 0xffffffff when
pattern_count is zero, zero when command_count is smaller, and one otherwise.
A bounded child contains native crashes or hangs; counters are updated only as
calls actually progress. Full artifact admission is a separate gate.
"""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import ctypes
import hashlib
import itertools
import json
import os
from pathlib import Path
import random
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import traceback


ROOT = Path(__file__).resolve().parents[2]
HIA_SOURCE = ROOT / "hia/prefix_admission.hepta"
SCHEMA = "codex.hia.prefix-admission-abi.v1"
INVALID = 0xFFFFFFFF
U64_MAX = (1 << 64) - 1
RANDOM_SEED = 0x48494141444D4954
RANDOM_CASES = 20_000
WORKERS, ITERATIONS = 8, 1_024
TIMEOUT_SECONDS = 120


def expected(command_count, pattern_count):
    """Ordinary Python integers specify the three outcomes without narrowing."""
    if pattern_count == 0:
        return INVALID
    return int(command_count >= pattern_count)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp",
                                         delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(report, indent=2) + "\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_report(path, fallback):
    try:
        value = json.loads(path.read_text())
        if isinstance(value, dict) and value.get("schema") == SCHEMA:
            return value
    except (OSError, ValueError):
        pass
    return dict(fallback)


class Native:
    def __init__(self, path):
        self.library = ctypes.CDLL(str(path))
        self.entry = self.library.f0
        self.entry.argtypes = [ctypes.c_uint64, ctypes.c_uint64]
        self.entry.restype = ctypes.c_uint64
        self.counts = Counter()
        self.lock = threading.Lock()

    def call(self, command_count, pattern_count, category, explicit=None):
        if not (0 <= command_count <= U64_MAX and 0 <= pattern_count <= U64_MAX):
            raise AssertionError("test input would be narrowed by ctypes")
        answer = expected(command_count, pattern_count)
        if explicit is not None and answer != explicit:
            raise AssertionError("explicit case differs from the independent oracle")
        with self.lock:
            self.counts["attempted_native_calls"] += 1
        actual = self.entry(command_count, pattern_count)
        with self.lock:
            self.counts["native_calls"] += 1
        if actual != answer:
            raise AssertionError(
                f"{category}: command_count={command_count:#018x}, "
                f"pattern_count={pattern_count:#018x}, "
                f"actual={actual:#018x}, expected={answer:#018x}"
            )
        with self.lock:
            self.counts["verified_native_calls"] += 1
            self.counts[category] += 1
            outcome = "invalid_pattern_calls" if answer == INVALID else (
                "admitted_calls" if answer else "insufficient_command_calls")
            self.counts[outcome] += 1

    def snapshot(self):
        with self.lock:
            return dict(self.counts)


def boundary_values():
    values = set(range(32)) | {U64_MAX - offset for offset in range(32)}
    for bit in range(65):
        center = 1 << bit
        values.update(value for value in (center - 1, center, center + 1)
                      if 0 <= value <= U64_MAX)
    return sorted(values)


def verify(path, report, report_path):
    inputs = {
        path: path.read_bytes(),
        HIA_SOURCE: HIA_SOURCE.read_bytes(),
        Path(__file__).resolve(): Path(__file__).read_bytes(),
    }
    report["library_sha256"] = digest(inputs[path])
    report["source_sha256"] = digest(inputs[HIA_SOURCE])
    report["test_sha256"] = digest(inputs[Path(__file__).resolve()])
    native = Native(path)

    def checkpoint(phase):
        report.update(native.snapshot())
        report["completed_phase"] = phase
        # A later signal or timeout may interrupt uncheckpointed calls.
        report["counts_are_lower_bounds"] = True
        write_report(report_path, report)

    try:
        explicit = [
            (0, 0, INVALID), (1, 0, INVALID), (U64_MAX, 0, INVALID),
            (1 << 32, 0, INVALID), (1 << 63, 0, INVALID),
            (0, 1, 0), (1, 1, 1), (2, 1, 1), (1, 2, 0),
            (0, U64_MAX, 0), (U64_MAX - 1, U64_MAX, 0),
            (U64_MAX, U64_MAX, 1), (U64_MAX, U64_MAX - 1, 1),
            (U64_MAX, 1, 1), (1 << 32, 1, 1), (1, 1 << 32, 0),
            ((1 << 32) - 1, 1 << 32, 0), (1 << 32, (1 << 32) - 1, 1),
            ((1 << 63) - 1, 1 << 63, 0), (1 << 63, (1 << 63) - 1, 1),
        ]
        report["active_phase"] = "explicit"
        for command_count, pattern_count, answer in explicit:
            native.call(command_count, pattern_count, "explicit_calls", answer)
        checkpoint("explicit")

        boundaries = boundary_values()
        report["boundary_values"] = len(boundaries)
        report["active_phase"] = "boundary_cross_product"
        for command_count, pattern_count in itertools.product(boundaries, repeat=2):
            native.call(command_count, pattern_count, "boundary_calls")
        checkpoint("boundary_cross_product")

        # Dense adjacent counts exercise ordinary public sizes between powers
        # of two; the cross product above also covers all 64 significant bits.
        report["active_phase"] = "adjacent"
        for pattern_count in range(1, 4_097):
            for command_count in (pattern_count - 1, pattern_count, pattern_count + 1):
                native.call(command_count, pattern_count, "adjacent_calls")
        checkpoint("adjacent")

        rng = random.Random(RANDOM_SEED)
        random_digest = hashlib.sha256()
        report["active_phase"] = "random"
        report["random_seed"] = RANDOM_SEED
        for _ in range(RANDOM_CASES):
            command_count, pattern_count = rng.getrandbits(64), rng.getrandbits(64)
            random_digest.update(struct.pack("<QQ", command_count, pattern_count))
            native.call(command_count, pattern_count, "random_independent_calls")
            native.call(pattern_count, command_count, "random_reversed_calls")
            native.call(command_count, command_count, "random_equal_calls")
            native.call(command_count, 0, "random_invalid_pattern_calls")
        report["random_pairs"] = RANDOM_CASES
        report["random_pairs_sha256"] = random_digest.hexdigest()
        checkpoint("random")

        barrier = threading.Barrier(WORKERS)
        report["active_phase"] = "concurrent"

        def concurrent_worker(worker):
            worker_rng = random.Random(RANDOM_SEED + worker + 1)
            barrier.wait(timeout=10)
            for iteration in range(ITERATIONS):
                command_count = worker_rng.getrandbits(64)
                mode = (worker + iteration) % 5
                pattern_count = (
                    0 if mode == 0 else
                    command_count if mode == 1 else
                    command_count - 1 if mode == 2 and command_count else
                    command_count + 1 if mode == 3 and command_count < U64_MAX else
                    worker_rng.getrandbits(64)
                )
                native.call(command_count, pattern_count, "concurrent_calls")

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            list(pool.map(concurrent_worker, range(WORKERS)))
        report["concurrent_workers"] = WORKERS
        checkpoint("concurrent")

        report["active_phase"] = "input_integrity"
        for input_path, original in inputs.items():
            if input_path.read_bytes() != original:
                raise AssertionError(f"input changed during native verification: {input_path}")
        report["inputs_unchanged"] = True
        counts = native.snapshot()
        categories = (
            "explicit_calls", "boundary_calls", "adjacent_calls",
            "random_independent_calls", "random_reversed_calls",
            "random_equal_calls", "random_invalid_pattern_calls", "concurrent_calls",
        )
        outcomes = ("invalid_pattern_calls", "admitted_calls", "insufficient_command_calls")
        total = counts["verified_native_calls"]
        if not (counts["attempted_native_calls"] == counts["native_calls"] == total
                == sum(counts.get(key, 0) for key in categories)
                == sum(counts.get(key, 0) for key in outcomes)):
            raise AssertionError("native call counters do not reconcile")
        report["passed"] = True
        report["statistics_complete"] = True
        report["completed_phase"] = "all"
    finally:
        report.update(native.snapshot())
        report["counts_are_lower_bounds"] = False


def disable_core_dumps():
    import resource

    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    prctl = ctypes.CDLL(None, use_errno=True).prctl
    prctl.argtypes = [ctypes.c_int] + [ctypes.c_ulong] * 4
    prctl.restype = ctypes.c_int
    if (prctl(4, 0, 0, 0, 0) != 0 or prctl(3, 0, 0, 0, 0) != 0
            or resource.getrlimit(resource.RLIMIT_CORE) != (0, 0)):
        raise RuntimeError("could not disable native child core dumps")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    library, destination = args.library.resolve(), args.report.resolve()
    if destination == ROOT or ROOT in destination.parents:
        parser.error("report must be outside the source tree")
    if destination in (library, library.parent / "build.json"):
        parser.error("report must not overwrite a native input")
    report = {
        "schema": SCHEMA, "passed": False, "skipped": 0,
        "abi": "SysV AMD64 (command_count:u64, pattern_count:u64) -> u64",
        "contract": {"pattern_count_zero": INVALID, "command_count_less_than_pattern_count": 0,
                     "command_count_at_least_nonzero_pattern_count": 1},
        "oracle": "Python arbitrary-precision comparison with an explicit zero-pattern outcome",
        "scope": "Raw scalar ABI; complete build admission and public-owner differential are separate gates",
        "attempted_native_calls": 0, "native_calls": 0, "verified_native_calls": 0,
        "statistics_complete": False, "counts_are_lower_bounds": True,
        "counter_semantics": "native_calls counts returned calls; verified_native_calls counts oracle matches",
    }
    if args.worker:
        try:
            disable_core_dumps()
            report["child_core_dumps_disabled"] = True
            verify(library.resolve(strict=True), report, destination)
        except Exception as error:
            report["error"] = f"{type(error).__name__}: {error}"
            traceback.print_exc()
        finally:
            report["child_finished"] = True
            write_report(destination, report)
        return 0 if report["passed"] else 1

    # The parent never loads the native library. Atomic checkpoints preserve
    # honest lower-bound counters if a native signal or loop kills the child.
    write_report(destination, report)
    command = [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--worker",
               "--library", str(library), "--report", str(destination)]
    try:
        with tempfile.TemporaryDirectory(prefix="codex-hia-prefix-admission-") as temporary:
            completed = subprocess.run(
                command, cwd=temporary, capture_output=True, text=True,
                timeout=TIMEOUT_SECONDS,
            )
    except subprocess.TimeoutExpired:
        report = read_report(destination, report)
        report.update(passed=False, statistics_complete=False, counts_are_lower_bounds=True,
                      child_timeout_seconds=TIMEOUT_SECONDS,
                      error=f"Native ABI suite exceeded its {TIMEOUT_SECONDS} second process budget")
        write_report(destination, report)
        print(json.dumps(report))
        return 1
    except OSError as error:
        report.update(error=f"{type(error).__name__}: {error}")
        write_report(destination, report)
        print(json.dumps(report))
        return 1
    report = read_report(destination, report)
    if completed.returncode or report.get("passed") is not True or report.get("child_finished") is not True:
        report.update(passed=False, child_exit_code=completed.returncode, statistics_complete=False)
        if completed.returncode < 0:
            report["child_signal"] = signal.Signals(-completed.returncode).name
        if report.get("child_finished") is not True:
            report["counts_are_lower_bounds"] = True
        report.setdefault("error", "Native ABI child terminated without a complete passing report")
        write_report(destination, report)
        sys.stderr.write(completed.stderr[-8000:])
        print(json.dumps(report))
        return 1
    report["child_exit_code"] = 0
    write_report(destination, report)
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
