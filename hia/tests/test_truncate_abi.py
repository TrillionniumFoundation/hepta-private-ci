#!/usr/bin/env python3
"""Exercise native truncation framing, immutable inputs and error/no-write ABI."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import ctypes
import hashlib
import json
from pathlib import Path
import struct
from threading import Lock


INVALID, SHORT, INVALID_UTF8 = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD
U64_MAX = (1 << 64) - 1
CAPACITY, REQUEST_SIZE = 40, 16


def verify(library_dir):
    path = library_dir / "libcodex_hia_truncate.so"
    build = json.loads((library_dir / "build.json").read_text())
    assert build["status"] == "built" and build["compiler_fixed_point"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert build["modules"]["truncate"]["codex_link_abi"]["library_sha256"] == digest
    library = ctypes.CDLL(str(path))
    function = library.codex_hia_truncate
    function.restype = ctypes.c_uint64
    function.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    counts = {"native_calls": 0, "error_no_write_cases": 0, "valid_plans": 0,
              "trusted_plan_comparisons": 0}
    count_lock = Lock()

    def invoke(source, operation, budget, expected_status=CAPACITY, output_size=CAPACITY, request_size=REQUEST_SIZE):
        # Offset every buffer by one byte: no host-alignment assumption is valid.
        borrowed = (ctypes.c_ubyte * (len(source) + 2))()
        borrowed[0] = borrowed[-1] = 0xCC
        borrowed[1:-1] = source
        output = (ctypes.c_ubyte * (CAPACITY + 18))(*([0xA5] * (CAPACITY + 18)))
        request = (ctypes.c_ubyte * (REQUEST_SIZE + 18))(*([0x5A] * (REQUEST_SIZE + 18)))
        request[1:REQUEST_SIZE + 1] = struct.pack("<QQ", operation, budget)
        before = bytes(borrowed), bytes(output), bytes(request)
        status = function(
            ctypes.byref(borrowed, 1), len(source), ctypes.byref(output, 1), output_size,
            ctypes.byref(request, 1), request_size,
        )
        with count_lock:
            counts["native_calls"] += 1
        assert status == expected_status, (source[:32], operation, budget, status, expected_status)
        assert bytes(borrowed) == before[0], "the borrowed source changed"
        assert bytes(request) == before[2], "the read-only request changed"
        assert output[0] == 0xA5 and bytes(output)[CAPACITY + 1:] == before[1][CAPACITY + 1:]
        if status != CAPACITY:
            assert bytes(output) == before[1], "an error wrote to output"
            with count_lock:
                counts["error_no_write_cases"] += 1
            return None
        return struct.unpack("<5Q", bytes(output)[1:CAPACITY + 1])

    for size in range(CAPACITY):
        invoke(b"text", 0, 1, SHORT, output_size=size)
    for size in range(REQUEST_SIZE):
        invoke(b"text", 0, 1, SHORT, request_size=size)
    # Operations 4/5 are now the valid-&str-only extension. Keep the two
    # immediate unknown-operation checks at the new boundary, 6/7.
    for operation in [6, 7, 255, (1 << 32) - 1, 1 << 32, 1 << 63, U64_MAX]:
        invoke(b"text", operation, 0, INVALID)
    for operation in [2, 3]:
        invoke(b"text", operation, 0, INVALID)

    invalid_sequences = [bytes([byte]) for byte in range(128, 256)] + [
        b"\xc0\x80", b"\xc1\xbf", b"\xe0\x80\x80", b"\xed\xa0\x80",
        b"\xf0\x80\x80\x80", b"\xf4\x90\x80\x80", b"\xf5\x80\x80\x80",
        b"\xc2a", b"\xe1\x80a", b"\xf1\x80\x80a", b"\xe0\x80", b"\xed\xa0",
        b"\xf0\x90", b"\xf0\x90\x80", b"\xef\xbf", b"\xc2", b"\xf4\x8f\xbf",
    ]
    for bad in invalid_sequences:
        for operation in [0, 1]:
            for budget in [0, U64_MAX]:
                invoke(b"valid prefix" + bad, operation, budget, INVALID_UTF8)
    raw_and_scalar_errors = counts["error_no_write_cases"]

    # Trusted operations have exactly the same framing/no-write contract.
    # Their UTF-8 precondition comes from Rust &str. Invalid bytes never enter
    # this path and cannot supply evidence for raw-byte UTF-8 acceptance.
    for operation in [4, 5]:
        for size in range(CAPACITY):
            invoke(b"text", operation, 1, SHORT, output_size=size)
        for size in range(REQUEST_SIZE):
            invoke(b"text", operation, 1, SHORT, request_size=size)
    trusted_capacity_errors = counts["error_no_write_cases"] - raw_and_scalar_errors

    # Direct contract examples complement the full original-Rust differential
    # suite without reproducing its truncation algorithm in this test.
    cases = [
        ("", 0, 0, (0, 0, 0, 0, 0)),
        ("", 1, U64_MAX, (0, 0, 0, 0, 0)),
        ("é汉😀", 0, 9, (9, 9, 0, 3, 0)),
        ("é汉😀", 1, U64_MAX, (9, 9, 0, 3, 0)),
        ("abcdefg", 0, 3, (1, 5, 4, 2, 1)),
        ("😀😀😀", 0, 7, (0, 8, 2, 3, 1)),
        ("\0a\r\n", 0, 1, (0, 3, 3, 1, 1)),
        ("é汉😀", 1, 1, (2, 9, 2, 3, 2)),
        ("é汉😀", 1, 2, (2, 5, 1, 3, 2)),
        ("abcdef", 1, 0, (0, 6, 2, 2, 2)),
        ("a\u0301b", 0, 0, (0, 4, 3, 1, 1)),
    ]
    for text, operation, budget, expected in cases:
        for output_size, request_size in [(CAPACITY, REQUEST_SIZE), (CAPACITY + 8, REQUEST_SIZE + 8)]:
            assert invoke(text.encode(), operation, budget, output_size=output_size, request_size=request_size) == expected
            assert invoke(text.encode(), operation + 4, budget, output_size=output_size, request_size=request_size) == expected
            counts["trusted_plan_comparisons"] += 1
            counts["valid_plans"] += 1

    for value in list(range(256)) + [U64_MAX // 4 - 1, U64_MAX // 4, U64_MAX // 4 + 1, U64_MAX - 4, U64_MAX - 3, U64_MAX - 2, U64_MAX - 1, U64_MAX]:
        assert invoke(b"", 2, value) == (min(value * 4, U64_MAX), 0, 0, 0, 0)
        assert invoke(b"", 3, value) == (min(value + 3, U64_MAX) // 4, 0, 0, 0, 0)

    source = ("é汉😀a" * 150_000).encode()
    assert len(source) > 1 << 20
    assert invoke(source, 0, len(source)) == (len(source), len(source), 0, 375_000, 0)
    assert invoke(source, 0, 0) == (0, len(source), 600_000, 375_000, 1)
    assert invoke(source, 1, 0) == (0, len(source), 375_000, 375_000, 2)

    def compare_trusted(encoded, budget):
        for operation in [0, 1]:
            expected = invoke(encoded, operation, budget)
            assert invoke(encoded, operation + 4, budget) == expected
            with count_lock:
                counts["trusted_plan_comparisons"] += 1

    for text in ["", "a", "ascii\0\r\n", "aé汉😀z", "😀abc😀", "a\u0301b", "👩\u200d🔬", "\u007f\u0080\u07ff\u0800\ud7ff\ue000\uffff\U00010000\U0010ffff"]:
        encoded = text.encode()
        for budget in list(range(len(encoded) + 2)) + [U64_MAX // 4 - 1, U64_MAX // 4, U64_MAX // 4 + 1, U64_MAX]:
            compare_trusted(encoded, budget)
    for encoded in [b"a" * 1_048_581, source]:
        for budget in [0, 1, 5, len(encoded) // 2, len(encoded) - 1, len(encoded), U64_MAX]:
            compare_trusted(encoded, budget)

    def concurrent_calls(worker):
        for iteration in range(64):
            text, operation, budget, expected = cases[(worker + iteration) % len(cases)]
            assert invoke(text.encode(), operation, budget) == expected
            assert invoke(text.encode(), operation + 4, budget) == expected
        return 64

    with ThreadPoolExecutor(max_workers=8) as pool:
        concurrent_total = sum(pool.map(concurrent_calls, range(8)))
    return {
        "passed": True, **counts, "concurrent_calls": concurrent_total, "skipped": 0,
        "trusted_concurrent_calls": concurrent_total,
        "raw_and_scalar_error_no_write_cases": raw_and_scalar_errors,
        "trusted_capacity_error_no_write_cases": trusted_capacity_errors,
        "library_sha256": digest, "request_size": REQUEST_SIZE, "output_size": CAPACITY,
        "input_contract": "operations 0/1 validate arbitrary bytes; operations 4/5 require valid UTF-8 borrowed from Rust &str; all requests are unaligned and read-only",
        "error_contract": "all returned errors preserve source, request and complete output buffers",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = {"schema": "codex.hia.truncate-abi.v2", "passed": False}
    try:
        report.update(verify(args.library_dir.resolve(strict=True)))
    except (AssertionError, OSError, KeyError, ValueError) as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
