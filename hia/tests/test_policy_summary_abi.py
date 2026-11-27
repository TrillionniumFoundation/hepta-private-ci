#!/usr/bin/env python3
"""Check complete HIA policy result reduction and its borrowed-buffer contract."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import ctypes
import hashlib
import itertools
import json
from pathlib import Path
import random
import struct
import subprocess
import sys
import threading


INVALID, SHORT = 0xFFFFFFFF, 0xFFFFFFFE
MAX = (1 << 64) - 1
GUARD = bytes(range(1, 34))


def word(value):
    return struct.pack("<Q", value)


def encode(records):
    return word(len(records)) + b"".join(word(kind) + word(decision)
                                        for kind, decision in records)


def expected(source):
    """Decode every record independently, including records after Forbidden."""
    if len(source) < 8:
        return INVALID, None
    count = struct.unpack_from("<Q", source)[0]
    if len(source) != 8 + 16 * count:
        return INVALID, None
    records = list(struct.iter_unpack("<QQ", source[8:]))
    if any(kind > 1 or decision > 2 for kind, decision in records):
        return INVALID, None
    result = (bool(records), max((decision for _, decision in records), default=0),
              any(kind == 0 for kind, _ in records))
    return 24, b"".join(word(int(value)) for value in result)


class Native:
    def __init__(self, library):
        self.library = ctypes.CDLL(str(library))
        self.entry = self.library.f0
        self.entry.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        self.entry.restype = ctypes.c_uint64
        self.counts = Counter()
        self.lock = threading.Lock()

    def call(self, source, category="valid", output_size=24, workspace=b"\x5a" * 31,
             offset=33, null_empty=False):
        status, result = expected(source)
        if output_size < 24:
            status, result = SHORT, None
        prefix = GUARD[:offset]
        buffers = [bytearray(prefix + source + GUARD),
                   bytearray(prefix + b"\xa5" * (max(24, output_size) + 19) + GUARD),
                   bytearray(prefix + workspace + GUARD)]
        before = tuple(map(bytes, buffers))
        arrays = [(ctypes.c_ubyte * len(data)).from_buffer(data) for data in buffers]
        pointers = [ctypes.addressof(array) + offset for array in arrays]
        if null_empty:
            for index, length in enumerate((len(source), output_size, len(workspace))):
                if length == 0:
                    pointers[index] = None
        actual = self.entry(pointers[0], len(source), pointers[1], output_size,
                            pointers[2], len(workspace))
        with self.lock:
            self.counts["native_calls"] += 1
        label = f"{category} bytes={len(source)} sha256={hashlib.sha256(source).hexdigest()}"
        assert actual == status, f"{label}: status {actual:#x}, expected {status:#x}"
        output = before[1] if result is None else before[1][:offset] + result + before[1][offset + 24:]
        assert bytes(buffers[0]) == before[0], f"{label}: source changed"
        assert bytes(buffers[1]) == output, f"{label}: output or canary differs"
        assert bytes(buffers[2]) == before[2], f"{label}: workspace changed"
        with self.lock:
            self.counts[category] += 1
            self.counts["success" if status == 24 else "error_no_write"] += 1
            self.counts["maximum_input_bytes"] = max(self.counts["maximum_input_bytes"], len(source))


def verify(library):
    native = Native(library)
    choices = list(itertools.product(range(2), range(3)))
    for length in range(5):
        for records in itertools.product(choices, repeat=length):
            native.call(encode(records), "enumerated")
    rng = random.Random(0x48494153554D4D)
    for _ in range(1024):
        native.call(encode([rng.choice(choices) for _ in range(rng.randrange(129))]), "random")
    frames = [encode([]), encode([(0, 0)]), encode([(1, 2), (0, 0), (1, 1)]),
              encode([(0, 2), (1, 0), (0, 2), (1, 2)])]
    for source in frames:
        for end in range(len(source)):
            native.call(source[:end], "truncation")
        for suffix in [b"\0", b"\xff", word(0), word(MAX), encode([(0, 0)])]:
            native.call(source + suffix, "trailing_bytes")
        for offset in range(len(source)):
            native.call(source[:offset] + bytes([source[offset] ^ 0x80]) + source[offset + 1:],
                        "byte_mutation")
    # Invalid tails must never be hidden by an earlier explicit Forbidden match.
    for position in range(4):
        for invalid in [2, 3, 255, 1 << 32, 1 << 63, MAX]:
            for field in range(2):
                records = [(0, 2)] * 4
                record = list(records[position])
                record[field] = invalid
                records[position] = tuple(record)
                native.call(encode(records), "record_mutation")
    for count in [0, 1, 2, 31, 32, 1 << 32, 1 << 61, 1 << 63, MAX]:
        for source in frames:
            native.call(word(count) + source[8:], "count_mutation")
    for source in [b"", b"\0" * 7, *frames, encode([(0, 2), (2, 0)])]:
        for size in range(24):
            native.call(source, "short_output_precedence", output_size=size,
                        workspace=b"", null_empty=True)
        for output_size, workspace_size, offset in itertools.product(
                [24, 25, 64], [0, 1, 32], [1, 7, 16, 33]):
            native.call(source, "buffer_layout", output_size=output_size,
                        workspace=bytes(range(workspace_size)), offset=offset, null_empty=True)
    for count in [31, 32, 33, 1024, 131073]:
        records = [(1, 0)] * count
        for position in (0, count // 2, count - 1):
            changed = records.copy()
            changed[position] = (0, 2)
            native.call(encode(changed), "large_or_threshold")
        invalid = records + [(0, 3)]
        native.call(encode(invalid), "invalid_tail")
    barrier = threading.Barrier(8)

    def worker(index):
        barrier.wait(timeout=10)
        for iteration in range(64):
            source = frames[(index + iteration) % len(frames)]
            if iteration % 3 == 0:
                source += b"\0"
            native.call(source, "concurrent", offset=1 + iteration % 32)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(worker, range(8)))
    return {"passed": True, **native.counts, "skipped": 0,
            "library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
            "test_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "oracle": "Independent Python complete-frame decoder and result reduction",
            "error_contract": "Output capacity first; all errors write nothing; entire frame validated",
            "buffer_contract": "Success changes only output bytes 0..24; source/workspace unchanged",
            "full_policy_qualification": False, "performance_qualification": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.report = args.report.resolve()
    root = Path(__file__).resolve().parents[2]
    if args.report == root or root in args.report.parents:
        parser.error("reports must be outside the source checkout")
    report = {"schema": "codex.hia.policy-summary-abi.v1", "passed": False}
    if args.worker:
        try:
            report.update(verify(args.library.resolve(strict=True)))
        except BaseException as error:
            report["error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            args.report.write_text(json.dumps(report, indent=2) + "\n")
        return
    if args.report.exists():
        parser.error("retain existing evidence; select a new report path")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "--worker",
               "--library", str(args.library.resolve()), "--report", str(args.report)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        report = json.loads(args.report.read_text())
        report["process"] = {"command": command, "returncode": result.returncode,
                             "stdout": result.stdout, "stderr": result.stderr}
        if result.returncode or report.get("passed") is not True:
            report["passed"] = False
            report.setdefault("error", "native ABI worker did not complete")
    except subprocess.TimeoutExpired as error:
        report.update(error="native ABI worker exceeded 120 seconds", passed=False)
        report["process"] = {"command": command, "stdout": (error.stdout or b"").decode(),
                             "stderr": (error.stderr or b"").decode()}
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
