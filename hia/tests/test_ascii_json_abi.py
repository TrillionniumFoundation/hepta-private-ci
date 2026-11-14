#!/usr/bin/env python3
"""Verify the native ASCII-fragment window and error/no-write contracts."""

import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import struct


INVALID, SHORT, INVALID_UTF8 = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD
CAPACITY = 8 + 3 * 4096


def verify(library_dir):
    path = library_dir / "libcodex_hia_ascii_json_fragment.so"
    build = json.loads((library_dir / "build.json").read_text())
    assert build["status"] == "built" and build["compiler_fixed_point"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert build["modules"]["ascii_json_fragment"]["codex_link_abi"]["library_sha256"] == digest
    library = ctypes.CDLL(str(path))
    function = library.codex_hia_ascii_json_fragment
    function.restype = ctypes.c_uint64
    function.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    counts = {"native_calls": 0, "error_no_write_cases": 0, "stream_cases": 0}

    def buffers(phase=0, final=0):
        return ((ctypes.c_ubyte * (CAPACITY + 8))(*([0xA5] * (CAPACITY + 8))),
                (ctypes.c_ubyte * 10)(phase, final, *([0x5A] * 8)))

    def invoke(source, output, workspace, output_size=CAPACITY, workspace_size=2):
        borrowed = ctypes.create_string_buffer(source)
        before = bytes(borrowed)
        status = function(borrowed, len(source), output, output_size, workspace, workspace_size)
        counts["native_calls"] += 1
        assert bytes(borrowed) == before
        assert bytes(output)[CAPACITY:] == bytes([0xA5] * 8)
        assert bytes(workspace)[2:] == bytes([0x5A] * 8)
        return status

    def reject(source, phase, final, expected, output_size=CAPACITY, workspace_size=2):
        output, workspace = buffers(phase, final)
        before = bytes(output), bytes(workspace)
        assert invoke(source, output, workspace, output_size, workspace_size) == expected
        assert (bytes(output), bytes(workspace)) == before
        counts["error_no_write_cases"] += 1

    for phase in range(1, 256):
        reject(b"a", phase, 0, INVALID)
    for final in range(2, 256):
        reject(b"a", 0, final, INVALID)
    reject(b"a" * 4097, 0, 1, INVALID)
    for capacity, workspace_size in [(0, 2), (7, 2), (10, 2), (CAPACITY, 0), (CAPACITY, 1)]:
        reject(b"a", 0, 1, SHORT, capacity, workspace_size)
    bad_sequences = [bytes([byte]) for byte in range(128, 256)] + [
        b"\xc0\x80", b"\xc1\xbf", b"\xe0\x80\x80", b"\xed\xa0\x80",
        b"\xf0\x80\x80\x80", b"\xf4\x90\x80\x80", b"\xf5\x80\x80\x80",
        b"\xc2a", b"\xe1\x80a", b"\xf1\x80\x80a", b"\xe0\x80", b"\xed\xa0",
    ]
    for invalid in bad_sequences:
        reject(b"valid prefix" + invalid, 0, 1, INVALID_UTF8)
    for invalid in [b"\xe0\x80", b"\xed\xa0", b"\xf0\x80", b"\xf4\x90"]:
        reject(b"a" + invalid, 0, 0, INVALID_UTF8)

    def window(source, final, output, workspace):
        output[:CAPACITY] = [0xA5] * CAPACITY
        workspace[1] = int(final)
        count = invoke(source, output, workspace)
        assert 8 <= count <= 8 + 3 * len(source)
        consumed = struct.unpack("<Q", bytes(output)[:8])[0]
        assert consumed <= len(source) and (not final or consumed == len(source))
        assert bytes(output)[count:CAPACITY] == bytes([0xA5] * (CAPACITY - count))
        assert workspace[0] == int(final)
        return consumed, bytes(output)[8:count]

    cases = [
        ("", b""), ("A\0\n\"\\\x7fZ", b"A\0\n\"\\\x7fZ"),
        ("é汉😀", b"\\u00e9\\u6c49\\ud83d\\ude00"),
        ("\u0080\u07ff\u0800", b"\\u0080\\u07ff\\u0800"),
        ("\ud7ff\ue000\uffff", b"\\ud7ff\\ue000\\uffff"),
        ("\U00010000\U0010ffff", b"\\ud800\\udc00\\udbff\\udfff"),
    ]
    for text, expected in cases:
        encoded = text.encode()
        for split in range(len(encoded) + 1):
            output, workspace = buffers()
            consumed, first = window(encoded[:split], False, output, workspace)
            _, second = window(encoded[consumed:], True, output, workspace)
            assert first + second == expected
            before = bytes(output), bytes(workspace)
            assert invoke(b"", output, workspace) == INVALID
            assert (bytes(output), bytes(workspace)) == before
            counts["stream_cases"] += 1
        for size in [1, 2, 3, 4, 7, 4096]:
            output, workspace = buffers()
            position, available = 0, size
            result = bytearray()
            while position < len(encoded):
                frame = encoded[position:position + available]
                consumed, payload = window(frame, False, output, workspace)
                result.extend(payload)
                if consumed:
                    position += consumed
                    available = size
                else:
                    available += 1
            _, payload = window(b"", True, output, workspace)
            result.extend(payload)
            assert bytes(result) == expected
            counts["stream_cases"] += 1
    for padding in range(4091, 4099):
        text = "a" * padding + "é汉😀"
        encoded = text.encode()
        output, workspace = buffers()
        consumed, first = window(encoded[:4096], False, output, workspace)
        _, second = window(encoded[consumed:], True, output, workspace)
        assert first + second == b"a" * padding + b"\\u00e9\\u6c49\\ud83d\\ude00"
        counts["stream_cases"] += 1
    return {"passed": True, **counts, "skipped": 0, "library_sha256": digest,
            "framing": "borrowed UTF-8 windows; unconsumed partial scalar is presented again",
            "error_contract": "all returned errors leave output and workspace unchanged"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = {"schema": "codex.hia.ascii-json-abi.v1", "passed": False}
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
