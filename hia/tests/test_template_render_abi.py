#!/usr/bin/env python3
"""Check native render-policy transitions, priorities and error atomicity."""
import argparse
import ctypes
import hashlib
import json
import struct
from pathlib import Path

MAX = (1 << 64) - 1
INVALID, SHORT = 0xFFFFFFFF, 0xFFFFFFFE
DUPLICATE, MISSING, EXTRA, MISSING_SEGMENT = 0xFFFFFFFC, 0xFFFFFFFB, 0xFFFFFFFA, 0xFFFFFFF9
CANARY = bytes([0xA7]) * 32


def put(buffer, at, value):
    struct.pack_into("<Q", buffer, at, value)


class Native:
    def __init__(self, path):
        self.library = ctypes.CDLL(str(path))
        self.entry = self.library.codex_hia_template_render
        self.entry.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        self.entry.restype = ctypes.c_uint64
        self.calls = self.errors = self.streams = 0

    def call(self, workspace, words, *, expected=None, error=None, source_length=40, output_length=32):
        source = struct.pack("<5Q", *(list(words) + [0] * (5 - len(words))))
        source = (source + bytes(64))[:source_length]
        raw_source = bytearray(CANARY) + source + CANARY
        raw_workspace = bytearray(CANARY) + workspace + CANARY
        raw_output = bytearray(CANARY) + bytes([0xB9]) * output_length + CANARY
        before_source, before_workspace, before_output = map(bytes, (raw_source, raw_workspace, raw_output))
        arrays = [(ctypes.c_ubyte * len(data)).from_buffer(data)
                  for data in (raw_source, raw_output, raw_workspace)]
        status = self.entry(ctypes.addressof(arrays[0]) + 32, source_length,
                            ctypes.addressof(arrays[1]) + 32, output_length,
                            ctypes.addressof(arrays[2]) + 32, len(workspace))
        self.calls += 1
        assert raw_source == before_source
        for buffer in (raw_workspace, raw_output):
            assert buffer[:32] == buffer[-32:] == CANARY
        if error is not None:
            assert status == error, (words, status, error)
            assert raw_workspace == before_workspace and raw_output == before_output
            self.errors += 1
        else:
            assert status == 32
            result = struct.unpack_from("<4Q", raw_output, 32)
            assert result == expected, (words, result, expected)
        workspace[:] = raw_workspace[32:-32]


def flows(native):
    states = [bytearray(64)]
    for variable_count in (0, 1, 2, 17):
        workspace = bytearray(64)
        for index in range(variable_count):
            native.call(workspace, [0, 0, index], expected=(0, index, 0, 0))
        if variable_count:
            native.call(workspace, [0, 1, variable_count - 1], error=DUPLICATE)
        native.call(workspace, [1, variable_count, 3],
                    expected=(1, 0, 0, 0) if variable_count else (2, 0, 0, 0))
        if variable_count:
            states.append(bytearray(workspace))
        for index in range(variable_count):
            native.call(workspace, [2, 0, 0], error=MISSING)
            native.call(workspace, [3, 0, 0], error=INVALID)
            native.call(workspace, [2, 1, variable_count - index - 1],
                        expected=(1, index + 1, 0, 0) if index + 1 < variable_count else (2, 0, 0, 0))
        states.append(bytearray(workspace))
        if variable_count:
            native.call(workspace, [3, 1, 0], error=EXTRA)
        native.call(workspace, [3, 0, 0], expected=(3, 0, 0, 0))
        states.append(bytearray(workspace))
        native.call(workspace, [5, 0, 0], error=MISSING_SEGMENT)
        native.call(workspace, [4, 0, 0], expected=(4, 0, 1, 0))
        if variable_count:
            native.call(workspace, [5, 1, variable_count - 1], expected=(5, 1, variable_count - 1, 2))
            native.call(workspace, [5, 1, 0], expected=(8, 2, 0, 0))
        else:
            native.call(workspace, [4], expected=(4, 1, 2, 0))
            native.call(workspace, [4], expected=(7, 2, 0, 0))
        states.append(bytearray(workspace))
        native.streams += 1
    empty = bytearray(64)
    native.call(empty, [1, 0, 0], expected=(2, 0, 0, 0))
    native.call(empty, [3, 0, 0], expected=(6, 0, 0, 0))
    native.streams += 1
    return states


def invalid_frames(native, states):
    for size in range(64):
        native.call(bytearray(size), [0], error=INVALID)
    for size in [*range(40), 41, 42, 63, 64]:
        native.call(bytearray(64), [0], source_length=size, error=INVALID)
    for size in range(32):
        native.call(bytearray(64), [0], output_length=size, error=SHORT)
    allowed = {0: {0, 1}, 1: {2}, 2: {3}, 3: {4, 5}, 4: set()}
    for state in states:
        phase = struct.unpack_from("<Q", state, 40)[0]
        for command in (*range(7), MAX):
            if command not in allowed[phase]:
                native.call(bytearray(state), [command], error=INVALID)
        for offset in (40, 48, 56):
            changed = bytearray(state)
            put(changed, offset, MAX)
            native.call(changed, [0], error=INVALID)
        for field in (3, 4):
            frame = [0] * 5
            frame[field] = MAX
            native.call(bytearray(state), frame, error=INVALID)
    for words in ([0, 2, 0], [0, MAX, 0], [0, 1, 0], [0, 0, 1]):
        native.call(bytearray(64), words, error=INVALID)


def numeric_edges(native):
    workspace = bytearray(64)
    put(workspace, 0, MAX - 1)
    native.call(workspace, [0, 0, MAX - 1], expected=(0, MAX - 1, 0, 0))
    native.call(workspace, [0, 0, MAX], error=INVALID)
    native.call(workspace, [0, 1, MAX - 1], error=DUPLICATE)
    native.call(workspace, [1, MAX, MAX], expected=(1, 0, 0, 0))
    put(workspace, 16, MAX - 1)
    native.call(workspace, [2, 0, 0], error=MISSING)
    native.call(workspace, [2, 1, 0], expected=(2, 0, 0, 0))
    native.call(workspace, [3, 1, MAX - 1], error=EXTRA)
    native.call(workspace, [3, 0, 0], expected=(3, 0, 0, 0))
    put(workspace, 32, MAX - 1)
    native.call(workspace, [4], expected=(7, MAX - 1, 0, 0))
    native.call(workspace, [4], error=INVALID)
    native.streams += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    native = Native(args.library.resolve())
    report = {"status": "running", "library_sha256": hashlib.sha256(args.library.read_bytes()).hexdigest(),
              "source_sha256": hashlib.sha256(Path(__file__).parents[1].joinpath("template_render.hepta").read_bytes()).hexdigest()}
    try:
        invalid_frames(native, flows(native))
        numeric_edges(native)
        report["status"] = "passed"
    except BaseException as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report.update(calls=native.calls, error_no_write=native.errors, streams=native.streams)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("status", "calls", "error_no_write", "streams")}))


if __name__ == "__main__":
    main()
