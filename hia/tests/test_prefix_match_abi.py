#!/usr/bin/env python3
"""Exercise native prefix matching, complete frame validation, and ABI isolation."""

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
SCHEMA = "codex.hia.prefix-match-abi.v1"


def word(value):
    return struct.pack("<Q", value)


def encode(commands, groups, *, command_count=None):
    count = len(commands) if command_count is None else command_count
    assert len(commands) >= min(count, len(groups))
    parts = [word(count), word(len(groups))]
    for alternatives in groups:
        parts.append(word(len(alternatives)))
        for token in alternatives:
            parts.extend((word(len(token)), token))
    for token in commands[:min(count, len(groups))]:
        parts.extend((word(len(token)), token))
    return b"".join(parts)


def expected(source):
    """Decode independently before applying ordinary Python byte membership."""
    cursor = 0

    def take_word():
        nonlocal cursor
        if len(source) - cursor < 8:
            raise ValueError("truncated word")
        value = struct.unpack_from("<Q", source, cursor)[0]
        cursor += 8
        return value

    def take_token():
        nonlocal cursor
        length = take_word()
        if length > len(source) - cursor:
            raise ValueError("truncated token")
        token = source[cursor:cursor + length]
        cursor += length
        return token

    try:
        command_count, pattern_count = take_word(), take_word()
        if not pattern_count or pattern_count > (len(source) - cursor) // 8:
            raise ValueError("invalid pattern count")
        groups = []
        for index in range(pattern_count):
            alternatives = take_word()
            if index == 0 and alternatives != 1:
                raise ValueError("invalid first group")
            if alternatives > (len(source) - cursor) // 8:
                raise ValueError("impossible alternative count")
            groups.append([take_token() for _ in range(alternatives)])
        commands = [take_token() for _ in range(min(command_count, pattern_count))]
        if cursor != len(source):
            raise ValueError("trailing bytes")
    except ValueError:
        return INVALID, None
    matched = command_count >= pattern_count and all(
        token in alternatives for token, alternatives in zip(commands, groups)
    )
    return 8, pattern_count if matched else 0


class Native:
    def __init__(self, path):
        self.library = ctypes.CDLL(str(path))
        self.entry = self.library.f0
        self.entry.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        self.entry.restype = ctypes.c_uint64
        self.counts = Counter()
        self.lock = threading.Lock()

    def call(self, source, *, category="valid_cases", output_size=8,
             workspace=b"\x5a" * 67, offset=33, null_empty=False):
        status, result = expected(source)
        if output_size < 8:
            # Output admission precedes frame validation, even for invalid input.
            status, result = SHORT, None
        prefix = GUARD[:offset]
        raw_source = bytearray(prefix + source + GUARD)
        raw_output = bytearray(prefix + b"\xa5" * (max(8, output_size) + 19) + GUARD)
        raw_workspace = bytearray(prefix + workspace + GUARD)
        before = tuple(map(bytes, (raw_source, raw_output, raw_workspace)))
        arrays = [(ctypes.c_ubyte * len(data)).from_buffer(data)
                  for data in (raw_source, raw_output, raw_workspace)]
        pointers = [ctypes.addressof(array) + offset for array in arrays]
        if null_empty:
            if not source:
                pointers[0] = None
            if not output_size:
                pointers[1] = None
            if not workspace:
                pointers[2] = None
        actual = self.entry(pointers[0], len(source), pointers[1], output_size,
                            pointers[2], len(workspace))
        with self.lock:
            self.counts["native_calls"] += 1
            self.counts["maximum_input_bytes"] = max(
                self.counts["maximum_input_bytes"], len(source))
        label = f"{category}: bytes={len(source)} sha256={hashlib.sha256(source).hexdigest()}"
        assert actual == status, f"{label}: status {actual:#x}, expected {status:#x}"
        desired_output = before[1]
        if status == 8:
            desired_output = before[1][:offset] + word(result) + before[1][offset + 8:]
        assert bytes(raw_source) == before[0], f"{label}: source or source canary changed"
        assert bytes(raw_output) == desired_output, f"{label}: output or output canary differs"
        assert bytes(raw_workspace) == before[2], f"{label}: workspace or workspace canary changed"
        with self.lock:
            self.counts[category] += 1
            if pointers[2] is None:
                self.counts["null_workspace_cases"] += 1
            if status == 8:
                self.counts["match_cases" if result else "mismatch_cases"] += 1
            else:
                self.counts["error_no_write_cases"] += 1
                self.counts["invalid_frame_cases" if status == INVALID else "short_output_cases"] += 1
        return actual, result


def verify(path):
    native = Native(path)
    tokens = [b"", b"git", b"status", b"--help", b"Git", b"g", b"git\0",
              b"*", b"a b", b"\0", "é汉😀".encode(), "e\u0301".encode(),
              b"\xff\xc0\x80\xed\xa0\x80\xf4\x90\x80\x80", bytes(range(256))]
    basic = []
    for command, pattern in itertools.product(tokens, repeat=2):
        source = encode([command], [[pattern]])
        native.call(source)
        basic.append(source)
    for first, second in itertools.product(tokens[:7], repeat=2):
        for group in [[], [second], [b"unused", second], [second, second, b"unused"]]:
            native.call(encode([first, second, b"ignored"], [[first], group]))
            native.call(encode([first], [[first], group]))
            native.call(encode([], [[first], group]))
    for count in [1, 2, (1 << 32) - 1, 1 << 32, 1 << 63, MAX - 1, MAX]:
        native.call(encode([b"git"], [[b"git"]], command_count=count))
        native.call(encode([b"not-git"], [[b"git"]], command_count=count))
    for count in [1, 2, 63, 256, 1024]:
        commands = [str(index).encode() for index in range(count)]
        groups = [[token] for token in commands]
        native.call(encode(commands, groups))
        native.call(encode(commands[:-1], groups))
        native.call(encode(commands[:-1] + [b"wrong"], groups))
    alternatives = [word(index) for index in range(1024)]
    for token in [alternatives[0], alternatives[511], alternatives[-1], b"absent"]:
        native.call(encode([b"run", token], [[b"run"], alternatives]))

    rng = random.Random(0x4849415052454649)
    for _ in range(1024):
        groups = [[rng.choice(tokens)]] + [
            [rng.choice(tokens) for _ in range(rng.randrange(5))]
            for _ in range(rng.randrange(8))
        ]
        commands = [rng.choice(tokens) for _ in range(rng.randrange(12))]
        native.call(encode(commands, groups), category="random_cases")

    # Every byte boundary of representative frames, including early mismatches
    # and missing command prefixes, must still require the complete frame.
    truncation_frames = [
        encode([], [[b""]]), encode([b"git"], [[b"git"]]),
        encode([b"other", b"status"], [[b"git"], [b"status", b"diff"]]),
        encode([b"git"], [[b"git"], [b"status", b""]]),
        encode([], [[b"git"], [b"status"], []]),
        encode([bytes(range(256)), b"\0"], [[bytes(range(256))], [b"", b"\0"]]),
        encode(["é汉😀".encode()], [["é汉😀".encode()]]),
    ]
    for source in truncation_frames:
        for end in range(len(source)):
            truncated = source[:end]
            assert expected(truncated)[0] == INVALID
            native.call(truncated, category="byte_truncation_cases")
        for suffix in [b"\0", b"\xff", word(0), word(MAX), b"tail" * 31]:
            native.call(source + suffix, category="trailing_byte_cases")

    malformed = [word(0) + word(0), encode([], []),
                 encode([b"git"], [[]]), encode([b"git"], [[b"git", b"sh"]])]
    base = encode([b"wrong", b"status"], [[b"git"], [b"status", b"diff"]])
    # Locate every structural u64 in this independently constructed frame.
    structural_offsets = [0, 8, 16, 24, 35, 43, 57, 69, 82]
    for offset in structural_offsets:
        for value in [0, 1, 2, 7, 8, 63, 1 << 32, 1 << 61, 1 << 63, MAX - 7, MAX]:
            changed = base[:offset] + word(value) + base[offset + 8:]
            native.call(changed, category="structural_mutation_cases")
    for value in [1 << 32, 1 << 61, 1 << 63, MAX - 7, MAX]:
        malformed.extend([
            word(0) + word(value),
            word(0) + word(1) + word(value),
            word(0) + word(1) + word(1) + word(value),
            word(0) + word(2) + word(1) + word(0) + word(value),
            word(1) + word(1) + word(1) + word(0) + word(value),
        ])
    for source in malformed:
        assert expected(source)[0] == INVALID
        native.call(source, category="malformed_count_length_cases")
    # A mismatch must not hide corruption later in commands or alternatives.
    for source in [base, encode([], [[b"git"], [b"status", b"diff"]]),
                   encode([b"wrong"], [[b"git"], []])]:
        for end in range(16, len(source)):
            assert expected(source[:end])[0] == INVALID
            native.call(source[:end], category="early_mismatch_tail_cases")
    for source in basic[::9]:
        for offset in range(len(source)):
            changed = source[:offset] + bytes([source[offset] ^ 0x80]) + source[offset + 1:]
            native.call(changed, category="byte_mutation_cases")

    for source in [encode([b"git"], [[b"git"]]),
                   encode([b"sh"], [[b"git"]]), encode([], [[b"git"]])]:
        for size in range(8):
            native.call(source, output_size=size, category="short_output_capacity_cases")
        for output_size, workspace_size, offset in itertools.product(
                [8, 9, 31, 64], [0, 1, 31, 256], [1, 7, 16, 33]):
            native.call(source, output_size=output_size,
                        workspace=bytes(index % 256 for index in range(workspace_size)),
                        offset=offset, null_empty=True, category="buffer_layout_cases")
    native.call(b"", workspace=b"", null_empty=True, category="null_empty_cases")
    for source in [b"", word(0), *malformed, base[:-1], base + b"tail"]:
        assert expected(source)[0] == INVALID
        for size in range(8):
            native.call(source, output_size=size, workspace=b"", null_empty=True,
                        category="short_output_precedence_cases")

    large = b"a" * (2 * 1024 * 1024) + b"\0" + "汉😀".encode()
    for command in [large, large[:-1] + b"x", large[:-1], b"x" + large[1:]]:
        native.call(encode([command], [[large]]), category="multi_mib_cases")
    native.call(encode([b"git", large], [[b"git"], [b"small", large]]),
                category="multi_mib_cases")

    barrier = threading.Barrier(8)
    concurrent_frames = basic[::7] + [base[:-1], base + b"tail"]

    def concurrent_worker(worker):
        barrier.wait(timeout=10)
        for index in range(64):
            source = concurrent_frames[(worker * 13 + index) % len(concurrent_frames)]
            native.call(source, workspace=bytes([worker]) * (index % 17),
                        offset=1 + index % 32, category="concurrent_calls")

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(concurrent_worker, range(8)))
    return {"passed": True, **native.counts, "skipped": 0,
            "library_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "test_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "oracle": "Independent complete frame decoder and Python byte membership",
            "scope": "Raw ABI; original Rust public-owner differential is a separate gate",
            "error_precedence": "Short output is rejected before validating the source frame",
            "error_contract": "All errors leave output unchanged; source and workspace never change",
            "success_contract": "Only output bytes 0..8 change, including non-match result zero"}


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    report = {"schema": SCHEMA, "passed": False}
    if args.worker:
        try:
            report.update(verify(args.library.resolve(strict=True)))
        except (AssertionError, AttributeError, OSError, ValueError) as error:
            report["error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            write_report(args.report, report)
        print(json.dumps(report))
        return
    # One bounded child protects the runner from an erroneous native loop or
    # crash on adversarial counts. No fabricated pass survives a timeout.
    write_report(args.report, report)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker",
               "--library", str(args.library.resolve()), "--report", str(args.report.resolve())]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        report["error"] = "Native ABI suite exceeded its 120 second process budget"
        write_report(args.report, report)
        raise SystemExit(report["error"]) from None
    if completed.returncode:
        report = json.loads(args.report.read_text())
        report.update(passed=False, child_exit_code=completed.returncode)
        report.setdefault("error", "Native ABI child terminated before completing verification")
        write_report(args.report, report)
        sys.stderr.write(completed.stderr[-8000:])
        raise SystemExit(1)
    report = json.loads(args.report.read_text())
    if report.get("passed") is not True:
        raise SystemExit("Native ABI child did not publish a passing report")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
