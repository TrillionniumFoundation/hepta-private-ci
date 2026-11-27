#!/usr/bin/env python3
"""Verify native UUID window progress, exact matches, and no-write failures."""

import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import re


INVALID, SHORT = 0xFFFFFFFF, 0xFFFFFFFE
PATTERN = re.compile(rb"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")
UUID = b"00112233-4455-6677-8899-aAbBcCdDeEfF"


def verify(directory):
    path = directory / "libcodex_hia_uuid_matches.so"
    build = json.loads((directory / "build.json").read_text())
    assert build["status"] == "built" and build["compiler_fixed_point"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert build["modules"]["uuid_matches"]["codex_link_abi"]["library_sha256"] == digest
    library = ctypes.CDLL(str(path))
    function = library.codex_hia_uuid_matches
    function.restype = ctypes.c_uint64
    function.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    counts = {"native_calls": 0, "error_no_write_cases": 0, "stream_cases": 0}

    def call(source, final, output_size=36, workspace_size=1):
        borrowed = ctypes.create_string_buffer(source)
        before = bytes(borrowed)
        output = (ctypes.c_ubyte * 44)(*([0xA5] * 44))
        workspace = (ctypes.c_ubyte * 9)(final, *([0x5A] * 8))
        initial = bytes(output), bytes(workspace)
        status = function(borrowed, len(source), output, output_size, workspace, workspace_size)
        counts["native_calls"] += 1
        assert bytes(borrowed) == before
        assert bytes(output)[36:] == bytes([0xA5] * 8)
        assert bytes(workspace) == initial[1]
        if status in (INVALID, SHORT):
            assert (bytes(output), bytes(workspace)) == initial
            counts["error_no_write_cases"] += 1
        return status, bytes(output)[:36]

    for final in range(2, 256):
        assert call(UUID, final)[0] == INVALID
    for size in [4097, 8192]:
        assert call(b"a" * size, 1)[0] == INVALID
    for output, workspace in [(0, 1), (35, 1), (36, 0)]:
        assert call(UUID, 1, output, workspace)[0] == SHORT

    def frame(source, final):
        status, output = call(source, int(final))
        tag, consumed = status >> 16, status & 0xFFFF
        match = PATTERN.search(source)
        if match is not None:
            assert (tag, consumed, output) == (1, match.end(), match.group())
        else:
            expected = (2, len(source)) if final else (3, max(0, len(source) - 35))
            assert (tag, consumed) == expected
            assert output == bytes([0xA5] * 36)
        return tag, consumed, output

    for source in [b"", b"a", UUID, b"a" + UUID + UUID, UUID[:35], b"A" * 4096]:
        frame(source, False)
        frame(source, True)
    for at in range(36):
        for byte in range(256):
            source = UUID[:at] + bytes([byte]) + UUID[at + 1:]
            frame(source, False)
            frame(source, True)

    def stream(source, size):
        result, position, available = [], 0, size
        while True:
            chunk = source[position:position + available]
            final = position + len(chunk) == len(source)
            tag, consumed, output = frame(chunk, final)
            if tag == 1:
                result.append(output)
            if tag == 2:
                break
            position += consumed
            available = size if consumed else available + 1
            assert available <= 4096
        assert result == PATTERN.findall(source)
        counts["stream_cases"] += 1

    for source in [b"", UUID, b"a" + UUID * 3 + b"f", "é汉😀".encode() + UUID, b"A" * 99 + UUID]:
        for size in [1, 2, 3, 7, 35, 36, 37, 4095, 4096]:
            stream(source, size)
    for padding in range(4058, 4101):
        stream(b"A" * padding + "é汉😀".encode() + UUID * 2, 4096)
    return {"passed": True, **counts, "skipped": 0, "library_sha256": digest,
            "framing": "HIA reports consumed bytes; incomplete candidates are presented again",
            "error_contract": "all errors and non-matches leave output and workspace unchanged"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = {"schema": "codex.hia.uuid-abi.v1", "passed": False}
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
