#!/usr/bin/env python3
"""Check HIA network-domain selection/reduction and atomic buffer errors."""

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


INVALID, SHORT, WORKSPACE = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD
MAX = (1 << 64) - 1
GUARD = bytes(range(1, 34))


def word(value):
    return struct.pack("<Q", value)


def select(tags):
    return word(0) + word(len(tags)) + bytes(tags)


def reduce(records, original_count=None):
    if original_count is None:
        original_count = max((index for index, _, _ in records), default=-1) + 1
    return word(1) + word(original_count) + word(len(records)) + b"".join(
        word(index) + word(decision) + word(len(host)) + host
        for index, decision, host in records)


def expected(source, output_size, workspace_size):
    """Independent wire model; actual default Rust is the separate public oracle."""
    if output_size < 8:
        return SHORT, None, None
    if len(source) < 8:
        return INVALID, None, None
    operation = struct.unpack_from("<Q", source)[0]
    if operation == 0:
        if len(source) < 16:
            return INVALID, None, None
        count = struct.unpack_from("<Q", source, 8)[0]
        if count > 64 or len(source) != 16 + count:
            return INVALID, None, None
        if output_size < 8 + count:
            return SHORT, None, None
        tags = source[16:]
        if any(tag > 2 for tag in tags):
            return INVALID, None, None
        indices = bytes(index for index, tag in enumerate(tags) if tag != 1)
        return 0, word(len(indices)) + indices, None
    if operation != 1 or len(source) < 24:
        return INVALID, None, None
    original_count, count = struct.unpack_from("<QQ", source, 8)
    if count > original_count or count > (len(source) - 24) // 24:
        return INVALID, None, None
    records, at = [], 24
    for _ in range(count):
        if len(source) - at < 24:
            return INVALID, None, None
        index, decision, length = struct.unpack_from("<QQQ", source, at)
        at += 24
        if (index >= original_count or decision not in (0, 2)
                or (records and index <= records[-1][0]) or length > len(source) - at):
            return INVALID, None, None
        records.append((index, decision, source[at:at + length]))
        at += length
    if at != len(source):
        return INVALID, None, None
    if output_size < 16 + 8 * count:
        return SHORT, None, None
    if workspace_size < count:
        return WORKSPACE, None, None
    last = {host: index for index, _, host in records}
    flags = bytes(0 if last[host] != index else 1 if decision == 0 else 2
                  for index, decision, host in records)
    allowed = [index for (index, _, _), flag in zip(records, flags) if flag == 1]
    denied = [index for (index, _, _), flag in zip(records, flags) if flag == 2]
    result = word(len(allowed)) + word(len(denied)) + b"".join(map(word, allowed + denied))
    return 0, result, flags


class Native:
    def __init__(self, library):
        self.library = ctypes.CDLL(str(library))
        self.entry = self.library.f0
        self.entry.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        self.entry.restype = ctypes.c_uint64
        self.counts = Counter()
        self.lock = threading.Lock()

    def call(self, source, category="valid", output_size=1040, workspace_size=128,
             offset=33, null_empty=False):
        status, result, workspace = expected(source, output_size, workspace_size)
        prefix = GUARD[:offset]
        buffers = [bytearray(prefix + source + GUARD),
                   bytearray(prefix + b"\xa5" * (output_size + 19) + GUARD),
                   bytearray(prefix + b"\x5a" * (workspace_size + 19) + GUARD)]
        before = tuple(map(bytes, buffers))
        arrays = [(ctypes.c_ubyte * len(data)).from_buffer(data) for data in buffers]
        pointers = [ctypes.addressof(array) + offset for array in arrays]
        if null_empty:
            for index, length in enumerate((len(source), output_size, workspace_size)):
                if length == 0:
                    pointers[index] = None
        actual = self.entry(pointers[0], len(source), pointers[1], output_size,
                            pointers[2], workspace_size)
        with self.lock:
            self.counts["native_calls"] += 1
        label = f"{category} bytes={len(source)} sha256={hashlib.sha256(source).hexdigest()}"
        assert actual == status, f"{label}: status {actual:#x}, expected {status:#x}"
        for index, changed in [(0, None), (1, result), (2, workspace)]:
            expected_bytes = before[index] if changed is None else (
                before[index][:offset] + changed + before[index][offset + len(changed):])
            assert bytes(buffers[index]) == expected_bytes, f"{label}: buffer {index} changed incorrectly"
        with self.lock:
            self.counts[category] += 1
            self.counts["success" if status == 0 else "error_no_write"] += 1
            self.counts["maximum_input_bytes"] = max(self.counts["maximum_input_bytes"], len(source))


def verify(library):
    native = Native(library)
    for count in range(7):
        for tags in itertools.product(range(3), repeat=count):
            native.call(select(tags), "select_enumerated", output_size=8 + count, workspace_size=0)
    hosts = [b"", b"a", b"A", "é\0汉e\u0301".encode()]
    choices = list(itertools.product((0, 2), hosts))
    for count in range(5):
        for selected in itertools.product(choices, repeat=count):
            native.call(reduce([(2 * i + 1, decision, host)
                                for i, (decision, host) in enumerate(selected)]),
                        "reduce_enumerated", output_size=16 + 8 * count, workspace_size=count)
    rng = random.Random(0x484941444F4D4149)
    for _ in range(512):
        tags = [rng.randrange(3) for _ in range(rng.randrange(65))]
        native.call(select(tags), "select_random")
        records = [(2 * i, rng.choice((0, 2)), rng.choice(hosts) + bytes([rng.randrange(4)]))
                   for i in range(rng.randrange(97))]
        native.call(reduce(records), "reduce_random")
    frames = [select([]), select([0, 1, 2, 1]), reduce([]),
              reduce([(1, 0, b"a"), (2, 2, b"a"), (5, 0, b"")]),
              reduce([(0, 0, b"a"), (1, 2, b"b"), (2, 0, b"a")])]
    for source in frames:
        for end in range(len(source)):
            native.call(source[:end], "truncation")
        for suffix in [b"\0", b"\xff", word(0), word(MAX)]:
            native.call(source + suffix, "trailing")
        for at in range(len(source)):
            native.call(source[:at] + bytes([source[at] ^ 0x80]) + source[at + 1:], "byte_mutation")
        for at in range(0, min(len(source), 24), 8):
            for value in [0, 1, 2, 64, 65, 1 << 32, 1 << 63, MAX]:
                native.call(source[:at] + word(value) + source[at + 8:], "header_mutation")
    for decision in [1, 3, 255, 1 << 32, MAX]:
        native.call(reduce([(0, 0, b"a"), (1, 2, b"a"), (2, decision, b"tail")]), "invalid_tail")
    for index in [0, 1, 3, MAX]:
        native.call(reduce([(1, 0, b"a"), (index, 2, b"b")], original_count=3), "index_mutation")
    for count in [63, 64, 65]:
        for tag in [0, 1, 2, 3, 255]:
            native.call(select([tag] * count), "select_boundary")
    for source in [b"", b"\0" * 7, *frames, select([0, 3]), reduce([(0, 1, b"")])]:
        for output_size in [0, 1, 7, 8, 9, 15, 16, 17, 23, 24, 39, 40, 72]:
            for workspace_size in [0, 1, 2, 3]:
                native.call(source, "capacity_precedence", output_size=output_size,
                            workspace_size=workspace_size, offset=1, null_empty=True)
        for offset in [1, 7, 16, 33]:
            native.call(source, "unaligned", offset=offset, null_empty=True)
    for count in [31, 32, 33, 62, 63, 512, 513]:
        records = [(i, 2 if i % 2 else 0, b"same") for i in range(count)]
        native.call(reduce(records), "metadata_boundary", output_size=16 + 8 * count,
                    workspace_size=count)
        native.call(reduce(records), "short_workspace", output_size=16 + 8 * count,
                    workspace_size=count - 1)
    for ending in [b"x", b"y"]:
        host = b"x" * 2097152 + ending
        native.call(reduce([(0, 0, b"x" * len(host)), (1, 2, host)]), "large_host",
                    output_size=32, workspace_size=2)
    barrier = threading.Barrier(8)

    def worker(index):
        barrier.wait(timeout=10)
        for iteration in range(32):
            native.call(frames[(index + iteration) % len(frames)], "concurrent",
                        offset=1 + iteration % 32)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(worker, range(8)))
    root = Path(__file__).resolve().parents[2]
    inputs = [library, library.with_name("libcodex_hia_network_domains.a"),
              library.with_name("build.json"), root / "hia/network_domains.hepta", Path(__file__)]
    return {"passed": True, **native.counts, "skipped": 0,
            "input_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs},
            "oracle": "Independent wire decoder; complete original Rust owner is checked by the public gate",
            "error_contract": "minimum output then header; SELECT capacity then tags; REDUCE entire frame then capacities; errors write nothing",
            "buffer_contract": "source unchanged; only encoded output prefix and REDUCE selected-count workspace bytes change",
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
    report = {"schema": "codex.hia.network-domains-abi.v1", "passed": False}
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
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        report = json.loads(args.report.read_text())
        report["process"] = {"command": command, "returncode": result.returncode,
                             "stdout": result.stdout, "stderr": result.stderr}
        if result.returncode or report.get("passed") is not True:
            report["passed"] = False
            report.setdefault("error", "native ABI worker did not complete")
    except subprocess.TimeoutExpired as error:
        report.update(error="native ABI worker exceeded 180 seconds", passed=False)
        report["process"] = {"command": command, "stdout": (error.stdout or b"").decode(),
                             "stderr": (error.stderr or b"").decode()}
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
