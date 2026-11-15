#!/usr/bin/env python3
"""Check HIA admission, rendering, stable ordering and atomic buffer errors."""

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

INVALID, SHORT, WORKSPACE, OVERFLOW = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFC
MAX = (1 << 64) - 1
GUARD = bytes(range(1, 34))


def word(value):
    return struct.pack("<Q", value)


def admit(decision):
    return word(0) + word(decision)


def single(value):
    return (0, (value,))


def alts(*values):
    return (1, values)


def frame(patterns, mode=2):
    return word(mode) + word(len(patterns)) + b"".join(
        word(len(tokens)) + b"".join(word(kind) + word(len(values)) + b"".join(
            word(len(value)) + value for value in values) for kind, values in tokens)
        for tokens in patterns)


def decode(source):
    """Independent exact wire grammar, not the public Rust owner oracle."""
    count = struct.unpack_from("<Q", source, 8)[0]
    if count > (len(source) - 16) // 32:
        raise ValueError("rule count")
    patterns, at = [], 16
    for _ in range(count):
        if len(source) - at < 8:
            raise ValueError("token count header")
        tokens = struct.unpack_from("<Q", source, at)[0]
        at += 8
        if tokens == 0 or tokens > (len(source) - at) // 16:
            raise ValueError("token count")
        rendered = []
        for index in range(tokens):
            if len(source) - at < 16:
                raise ValueError("token header")
            kind, items = struct.unpack_from("<QQ", source, at)
            at += 16
            if (kind not in (0, 1) or (kind == 0 and items != 1)
                    or (index == 0 and kind != 0) or items > (len(source) - at) // 8):
                raise ValueError("token kind or item count")
            values = []
            for _ in range(items):
                if len(source) - at < 8:
                    raise ValueError("item header")
                length = struct.unpack_from("<Q", source, at)[0]
                at += 8
                if length > len(source) - at:
                    raise ValueError("item bytes")
                values.append(source[at:at + length])
                at += length
            rendered.append(values[0] if kind == 0 else b"[" + b"|".join(values) + b"]")
        patterns.append(tuple(rendered))
    if at != len(source):
        raise ValueError("trailing bytes")
    return patterns


def layout(patterns):
    count = len(patterns)
    rendered = [word(len(tokens)) + b"".join(word(len(value)) + value for value in tokens)
                for tokens in patterns]
    offsets = [24 * count + 8]
    for value in rendered:
        offsets.append(offsets[-1] + len(value))
    a, b = list(range(count)), [0] * count
    source, dest, width = a, b, 1
    while width < count:
        for start in range(0, count, 2 * width):
            end = min(start + 2 * width, count)
            dest[start:end] = sorted(source[start:end], key=lambda index: patterns[index])
        source, dest, width = dest, source, 2 * width
    ordered = sorted(range(count), key=lambda index: patterns[index])
    unique = [index for position, index in enumerate(ordered)
              if position == 0 or patterns[index] != patterns[ordered[position - 1]]]
    scratch = b"".join(map(word, offsets + a + b)) + b"".join(rendered)
    result = word(len(unique)) + b"".join(map(word, unique))
    return sum(map(len, rendered)), scratch, result


def expected(source, output_size, workspace_size):
    if output_size < 8:
        return SHORT, None, None
    if len(source) < 16:
        return INVALID, None, None
    operation = struct.unpack_from("<Q", source)[0]
    if operation == 0:
        decision = struct.unpack_from("<Q", source, 8)[0]
        if len(source) != 16 or decision > 2:
            return INVALID, None, None
        return 0, word(int(decision == 0)), None
    if operation not in (1, 2):
        return INVALID, None, None
    try:
        patterns = decode(source)
    except ValueError:
        return INVALID, None, None
    rendered, scratch, result = layout(patterns)
    output_capacity = 8 + 8 * len(patterns)
    if len(scratch) > MAX or output_capacity > MAX:
        return OVERFLOW, None, None
    if operation == 1:
        if output_size < 24:
            return SHORT, None, None
        return 0, word(rendered) + word(len(scratch)) + word(output_capacity), None
    if output_size < output_capacity:
        return SHORT, None, None
    if workspace_size < len(scratch):
        return WORKSPACE, None, None
    return 0, result, scratch


class Native:
    def __init__(self, library):
        self.library = ctypes.CDLL(str(library))
        self.entry = self.library.f0
        self.entry.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        self.entry.restype = ctypes.c_uint64
        self.counts = Counter()
        self.lock = threading.Lock()

    def call(self, source, category="valid", output_size=4096, workspace_size=16384,
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

    def complete(patterns, category):
        encoded = frame(patterns)
        _, scratch, _ = layout(decode(encoded))
        native.call(frame(patterns, 1), category + "_plan", output_size=24, workspace_size=0)
        native.call(encoded, category + "_run", output_size=8 + 8 * len(patterns),
                    workspace_size=len(scratch))

    for decision in [0, 1, 2, 3, 255, 1 << 32, 1 << 63, MAX]:
        native.call(admit(decision), "admission", output_size=8, workspace_size=0)
    choices = [(single(b""),), (single(b"a"),), (single(b"A"),),
               (single(b"a"), single(b"")), (single(b"a"), alts()),
               (single(b"a"), alts(b"x", b"y")), (single(b"a"), single(b"[x|y]"))]
    for count in range(4):
        for patterns in itertools.product(choices, repeat=count):
            complete(patterns, "rule_enumerated")
    token_choices = [single(b""), single(b"a"), single(b"[]"), single(b"[a|b]"),
                     alts(), alts(b""), alts(b"a", b"b"), alts(b"a|b"), alts(b"a", b"a")]
    for count in range(4):
        for tokens in itertools.product(token_choices, repeat=count):
            complete([(single(b"program"), *tokens)], "token_enumerated")
    rng = random.Random(0x484941414C4C4F57)
    values = [b"", b"a", b"A", b"\0", b"[a|b]", b"[]", b"|", b"\xff", "汉é\0e\u0301".encode()]
    for _ in range(384):
        patterns = []
        for _ in range(rng.randrange(66)):
            tokens = [single(rng.choice(values))]
            for _ in range(rng.randrange(5)):
                tokens.append(single(rng.choice(values)) if rng.randrange(2)
                              else alts(*(rng.choice(values) for _ in range(rng.randrange(5)))))
            patterns.append(tuple(tokens))
        complete(patterns, "deterministic_random")
    frames = [admit(0), admit(2), frame([], 1), frame([]),
              frame(choices[4:], 1), frame(choices), frame([(single(b"a"), alts(b"", b"x"))])]
    for source in frames:
        for end in range(len(source)):
            native.call(source[:end], "truncation")
        for suffix in [b"\0", b"\xff", word(0), word(MAX)]:
            native.call(source + suffix, "trailing")
        for at in range(len(source)):
            native.call(source[:at] + bytes([source[at] ^ 0x80]) + source[at + 1:], "byte_mutation")
        for at in range(0, min(len(source), 48), 8):
            for value in [0, 1, 2, 64, 65, 1 << 32, 1 << 63, MAX]:
                native.call(source[:at] + word(value) + source[at + 8:], "word_mutation")
    invalid = [frame([()]), frame([(alts(b"a"),)]),
               frame([(single(b"a"), (2, (b"ignored",)))]),
               frame([(single(b"a"), (0, ()))])]
    for source in invalid:
        native.call(source, "invalid_shape")
    for source in [b"", b"\0" * 15, *frames, *invalid]:
        for output_size in [0, 1, 7, 8, 9, 23, 24, 25, 64, 512]:
            for workspace_size in [0, 7, 8, 31, 32, 511, 512]:
                native.call(source, "capacity_precedence", output_size=output_size,
                            workspace_size=workspace_size, offset=1, null_empty=True)
        for offset in [1, 7, 16, 33]:
            native.call(source, "unaligned", offset=offset, null_empty=True)
    for count in [0, 1, 2, 3, 7, 8, 9, 15, 16, 17, 31, 32, 33, 63, 64, 65]:
        patterns = [(single(str(count - index).encode()), alts(b"", b"a")) for index in range(count)]
        complete(patterns, "merge_boundary")
        encoded = frame(patterns)
        _, scratch, _ = layout(decode(encoded))
        native.call(encoded, "short_workspace", output_size=8 + 8 * count,
                    workspace_size=len(scratch) - 1)
    for size in [0, 1, 7, 8, 9, 463, 464, 465, 2097153]:
        value = b"x" * size
        complete([(single(value),), (single(value), alts()),
                  (single(b"y" + value[1:]),), (single(value + b"y"),)], "byte_boundaries")
    barrier = threading.Barrier(8)

    def worker(index):
        barrier.wait(timeout=10)
        for iteration in range(32):
            native.call(frames[(index + iteration) % len(frames)], "concurrent", offset=1 + iteration % 32)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(worker, range(8)))
    root = Path(__file__).resolve().parents[2]
    inputs = [library, library.with_name("libcodex_hia_allowed_prefixes.a"),
              library.with_name("build.json"), root / "hia/allowed_prefixes.hepta", Path(__file__)]
    return {"passed": True, **native.counts, "skipped": 0,
            "input_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs},
            "oracle": "independent complete byte-wire model; actual original Rust is a separate public gate",
            "error_contract": "minimum output8, complete exact frame, layout, output capacity, workspace capacity; no writes on errors",
            "buffer_contract": "ADMIT/PLAN workspace untouched; RUN deterministic full scratch, output only unique-index prefix; source/canaries unchanged",
            "layout": "24*N+8+R; stable iterative merge sort with two N-index arrays",
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
    report = {"schema": "codex.hia.allowed-prefixes-abi.v1", "passed": False}
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
