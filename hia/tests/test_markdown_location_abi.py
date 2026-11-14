#!/usr/bin/env python3
"""Exercise the native markdown stream's framing and error/no-write contract."""

import argparse
import ctypes
import hashlib
import json
from pathlib import Path


INVALID, SHORT, INVALID_FORMAT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD
CAPACITY = 4096


def verify(library_dir):
    path = library_dir / "libcodex_hia_markdown_location.so"
    build = json.loads((library_dir / "build.json").read_text())
    assert build["status"] == "built" and build["compiler_fixed_point"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert build["modules"]["markdown_location"]["codex_link_abi"]["library_sha256"] == digest
    library = ctypes.CDLL(str(path))
    function = library.codex_hia_markdown_location
    function.restype = ctypes.c_uint64
    function.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    counts = {"native_calls": 0, "error_no_write_cases": 0, "stream_cases": 0}

    def buffers(phase=0, final=0):
        output = (ctypes.c_ubyte * (CAPACITY + 8))(*([0xA5] * (CAPACITY + 8)))
        workspace = (ctypes.c_ubyte * 10)(phase, final, *([0x5A] * 8))
        return output, workspace

    def invoke(source, output, workspace, output_size=CAPACITY, workspace_size=2):
        borrowed = ctypes.create_string_buffer(source)
        before = bytes(borrowed)
        status = function(borrowed, len(source), output, output_size, workspace, workspace_size)
        counts["native_calls"] += 1
        assert bytes(borrowed) == before, "the borrowed input changed"
        assert bytes(output)[CAPACITY:] == bytes([0xA5] * 8)
        assert bytes(workspace)[2:] == bytes([0x5A] * 8)
        return status

    def reject(source, phase, final, expected, output_size=CAPACITY, workspace_size=2):
        output, workspace = buffers(phase, final)
        before = bytes(output), bytes(workspace)
        assert invoke(source, output, workspace, output_size, workspace_size) == expected
        assert (bytes(output), bytes(workspace)) == before
        counts["error_no_write_cases"] += 1

    for phase in range(7, 256):
        reject(b"abc", phase, 0, INVALID)
    for flag in range(2, 256):
        reject(b"abc", 2, flag, INVALID)
    reject(b"a" * (CAPACITY + 1), 2, 0, INVALID)
    for output_size, workspace_size in [(0, 2), (2, 2), (CAPACITY, 0), (CAPACITY, 1)]:
        reject(b"#L1", 0, 1, SHORT, output_size, workspace_size)
    for source, phase, final in [
        (b"", 0, 1), (b"#", 0, 1), (b"#L1-", 0, 1), (b"L1", 0, 1),
        (b"#Labc-X", 0, 1), (b"abc-X", 2, 0), (b"abc-X", 3, 0),
        (b"", 1, 1), (b"", 4, 1), (b"X", 1, 0), (b"X", 4, 0),
    ]:
        reject(source, phase, final, INVALID_FORMAT)

    # Empty nonfinal frames never imply EOF; the same states remain usable.
    for phase in range(7):
        output, workspace = buffers(phase)
        before = bytes(output), bytes(workspace)
        assert invoke(b"", output, workspace) == 0
        assert (bytes(output), bytes(workspace)) == before

    def stream(chunks, expected):
        output, workspace = buffers()
        accumulated = bytearray()
        for index, chunk in enumerate(chunks):
            output[:CAPACITY] = [0xA5] * CAPACITY
            workspace[1] = int(index == len(chunks) - 1)
            count = invoke(chunk, output, workspace)
            assert count <= len(chunk), (chunks, index, count)
            assert bytes(output)[count:CAPACITY] == bytes([0xA5] * (CAPACITY - count))
            accumulated.extend(bytes(output)[:count])
        assert workspace[0] == 7 and workspace[1] == 1
        assert bytes(accumulated) == expected.encode()
        before = bytes(output), bytes(workspace)
        assert invoke(b"again", output, workspace) == INVALID
        assert (bytes(output), bytes(workspace)) == before
        counts["stream_cases"] += 1

    cases = [
        ("#L", ":"), ("#LC", "::"), ("#L-L", ":-"), ("#L-LC", ":-:"),
        ("#L1C2-L3C4", ":1:2-3:4"), ("#L1C2C3-L4C5C6-L7", ":1:2C3-4:5C6-L7"),
        ("#LéC汉-L😀C\0", ":é:汉-😀:\0"), ("#L1-L-2", ":1--2"),
        ("#L-L-L", ":--L"), ("#LC-LC", "::-:"),
    ]
    for text, expected in cases:
        encoded = text.encode()
        # Every two-way cut includes #|L, -|L, both sides of C, and UTF-8 splits.
        for split in range(len(encoded) + 1):
            stream([encoded[:split], b"", encoded[split:], b""], expected)
        for size in [1, 2, 3, 4, 7, CAPACITY]:
            stream([encoded[i:i + size] for i in range(0, len(encoded), size)], expected)
    for padding in range(4091, 4099):
        prefix = "0" * padding
        for tail, result in [("C2-L3C4", ":2-3:4"), ("-L3C4", "-3:4"), ("😀Cé-L汉C😀", "😀:é-汉:😀")]:
            encoded = ("#L" + prefix + tail).encode()
            stream([encoded[i:i + CAPACITY] for i in range(0, len(encoded), CAPACITY)], ":" + prefix + result)

    # Rejecting an incomplete final frame preserves the committed prefix state.
    for prefix, phase, count, completion, expected in [
        (b"#", 1, 1, b"L0", b"0"), (b"#L1-", 4, 3, b"L2", b"2"),
    ]:
        output, workspace = buffers()
        assert invoke(prefix, output, workspace) == count and workspace[0] == phase
        workspace[1] = 1
        before = bytes(output), bytes(workspace)
        for invalid in [b"", b"X"]:
            assert invoke(invalid, output, workspace) == INVALID_FORMAT
            assert (bytes(output), bytes(workspace)) == before
            counts["error_no_write_cases"] += 1
        assert invoke(completion, output, workspace) == 1 and workspace[0] == 7
        assert bytes(output)[:1] == expected
    return {
        "passed": True, **counts, "skipped": 0, "library_sha256": digest,
        "input_contract": "byte frames of a complete valid UTF-8 string; per-frame result length",
        "error_contract": "no writes to output or workspace on any returned error",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = {"schema": "codex.hia.markdown-abi.v1", "passed": False}
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
