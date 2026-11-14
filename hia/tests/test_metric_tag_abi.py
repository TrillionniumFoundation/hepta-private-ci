#!/usr/bin/env python3
"""Exercise the native metric stream ABI and its error/no-write contract."""

import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import struct


INVALID = 0xFFFFFFFF
SHORT = 0xFFFFFFFE


def invoke(function, source, output, workspace, output_size=256, workspace_size=32):
    source_buffer = ctypes.create_string_buffer(source)
    before = bytes(source_buffer)
    status = function(
        source_buffer, len(source), output, output_size, workspace, workspace_size,
    )
    assert bytes(source_buffer) == before, "HIA modified the borrowed source"
    return status


def verify(library_dir):
    path = library_dir / "libcodex_hia_metric_tag.so"
    build = json.loads((library_dir / "build.json").read_text())
    assert build["status"] == "built" and build["compiler_fixed_point"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert build["modules"]["metric_tag"]["codex_link_abi"]["library_sha256"] == digest
    library = ctypes.CDLL(str(path))
    function = library.codex_hia_metric_tag
    function.restype = ctypes.c_uint64
    function.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    calls = 0
    bad_states = [
        (258, 1, 1, 1, 0), (1, 2, 1, 1, 0), (1, 0, 0, 1, 0),
        (0, 0, 1, 1, 0), (1, 1, 2, 1, 0), (0, 0, 0, 2, 0),
        (0, 0, 0, 1, 1), (0, 0, 0, 1, 255),
        (0xFFFFFFFFFFFFFFFF, 1, 1, 1, 0),
    ]
    for state in bad_states:
        workspace = (ctypes.c_ubyte * 40)()
        encoded = struct.pack("<QQQBB", *state)
        workspace[:len(encoded)] = encoded
        output = (ctypes.c_ubyte * 264)(*([0xA5] * 264))
        before = (bytes(output), bytes(workspace))
        assert invoke(function, b"a", output, workspace) == INVALID
        assert (bytes(output), bytes(workspace)) == before
        calls += 1
    for output_size, workspace_size in [(0, 32), (255, 32), (256, 0), (256, 31)]:
        output = (ctypes.c_ubyte * 264)(*([0xA5] * 264))
        workspace = (ctypes.c_ubyte * 40)()
        workspace[24] = 1
        before = (bytes(output), bytes(workspace))
        assert invoke(function, b"a", output, workspace, output_size, workspace_size) == SHORT
        assert (bytes(output), bytes(workspace)) == before
        calls += 1
    cases = [
        ("", "unspecified"), ("__é汉😀__", "unspecified"),
        ("__Aé汉😀Z___", "A___Z"), (". / -", "unspecified"),
        ("." * 256 + "a", "." * 256),
        ("a" + "_" * 255 + "b", "a" + "_" * 255),
        ("a" + "_" * 4096, "a"), ("a\0\u007fz", "a__z"),
    ]
    for text, expected in cases:
        encoded = text.encode()
        for chunk_size in [1, 2, 3, 4, 7, 255, 256, 257, 1_048_576]:
            output = (ctypes.c_ubyte * 264)(*([0xA5] * 264))
            workspace = (ctypes.c_ubyte * 40)()
            workspace[26:] = [0x5A] * 14
            chunks = [encoded[i:i + chunk_size] for i in range(0, len(encoded), chunk_size)] or [b""]
            for i, chunk in enumerate(chunks):
                final = i == len(chunks) - 1
                workspace[24] = int(final)
                status = invoke(function, chunk, output, workspace)
                assert status == (len(expected) if final else 0)
                assert bytes(output)[256:] == bytes([0xA5] * 8)
                assert bytes(workspace)[26:] == bytes([0x5A] * 14)
                assert workspace[25] == int(final)
                calls += 1
            assert bytes(output)[:len(expected)] == expected.encode()
            before = (bytes(output), bytes(workspace))
            assert invoke(function, b"again", output, workspace) == INVALID
            assert (bytes(output), bytes(workspace)) == before
            calls += 1
    return {
        "passed": True, "native_calls": calls, "invalid_states": len(bad_states),
        "capacity_failures": 4, "stream_cases": len(cases) * 9,
        "skipped": 0, "library_sha256": digest,
        "input_contract": "chunks of a complete valid UTF-8 string",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = {"schema": "codex.hia.metric-abi.v1", "passed": False}
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
