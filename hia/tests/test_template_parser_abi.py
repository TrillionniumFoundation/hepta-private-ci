#!/usr/bin/env python3
"""Exercise borrowed parser frames, terminal/error states, and atomic writes."""

import argparse
import ctypes
import hashlib
import json
import struct
from pathlib import Path

INVALID = 0xFFFFFFFF
SHORT = 0xFFFFFFFE
UTF8 = 0xFFFFFFFD
EMPTY = 0xFFFFFFFC
NESTED = 0xFFFFFFFB
UNMATCHED = 0xFFFFFFFA
UNTERMINATED = 0xFFFFFFF9


def state(total, position=0, anchor=0, first=0, last=0, phase=0, final=0):
    return bytearray(struct.pack("<5Q2B", total, position, anchor, first, last, phase, final) + b"\xa5" * 6)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    library = ctypes.CDLL(str(args.library.resolve()))
    invoke = library.codex_hia_template_parser
    invoke.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    invoke.restype = ctypes.c_uint64
    counters = {"calls": 0, "error_no_write": 0, "streams": 0}

    def call(data, workspace, out_capacity=24, state_capacity=48):
        def guarded(value):
            raw = b"\xd3" * 16 + bytes(value) + b"\xe7" * 16
            buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
            return buffer, ctypes.byref(buffer, 16), raw
        source, source_ptr, source_before = guarded(data)
        output, output_ptr, output_before = guarded(b"\x96" * 40)
        working, working_ptr, working_before = guarded(workspace)
        result = invoke(source_ptr, len(data), output_ptr, out_capacity,
                        working_ptr, state_capacity)
        counters["calls"] += 1
        assert bytes(source) == source_before
        for buffer, before in [(output, output_before), (working, working_before)]:
            assert bytes(buffer)[:16] == before[:16]
            assert bytes(buffer)[-16:] == before[-16:]
        if result != 24:
            assert bytes(output) == output_before, (result, data)
            assert bytes(working) == working_before, (result, data)
            counters["error_no_write"] += 1
        else:
            assert bytes(output)[40:] == output_before[40:]
            assert bytes(working)[16:24] == working_before[16:24]  # total length
            assert bytes(working)[57:] == working_before[57:]  # EOF flag, reserved, guard
        return result, bytes(output)[16:40], bytearray(bytes(working)[16:-16])

    def reject(data, workspace, expected, **sizes):
        result, _, _ = call(data, workspace, **sizes)
        assert result == expected, (hex(result), hex(expected), data, list(workspace))

    def stream(text, width):
        data = text.encode()
        workspace = state(len(data))
        position = 0
        window = width
        segments = []
        for _ in range(4 * len(data) + 16):
            frame = data[position:position + window]
            workspace[41] = int(position + len(frame) == len(data))
            old_anchor = struct.unpack_from("<Q", workspace, 16)[0]
            result, output, workspace = call(frame, workspace)
            if result != 24:
                counters["streams"] += 1
                return result, position if result == UNMATCHED else old_anchor
            event, begin, end = struct.unpack("<3Q", output)
            next_position = struct.unpack_from("<Q", workspace, 8)[0]
            assert position <= next_position <= position + len(frame)
            if event == 3:
                assert next_position == len(data) and workspace[40] == 2
                reject(b"", workspace, INVALID)
                counters["streams"] += 1
                return 24, segments
            if event in (1, 2):
                assert begin < end <= next_position
                span = data[begin:end].decode()
                if event == 1 and segments and segments[-1][0] == 1:
                    segments[-1] = (1, segments[-1][1] + span)
                else:
                    segments.append((event, span))
            else:
                assert event == 0 and begin == end == 0
            if next_position == position:
                assert not workspace[41] and event == 0
                window += 1
                assert window <= 4
            else:
                position = next_position
                window = width
        raise AssertionError("parser did not finish")

    report = {"status": "running", "library_sha256": hashlib.sha256(args.library.read_bytes()).hexdigest(),
              "abi": "distinct immutable readbuf and two distinct mutbuf borrows; 4096-byte maximum frame",
              "counters": counters}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    try:
        for size in range(24):
            reject(b"", state(0, final=1), SHORT, out_capacity=size)
        for size in range(48):
            reject(b"", state(0, final=1), SHORT, state_capacity=size)
        reject(b"x" * 4097, state(4097, final=1), INVALID)
        for workspace in [
            state(0, phase=2), state(0, phase=255), state(0, final=2),
            state(0, position=1), state(1, final=1), state(1, anchor=1),
            state(1, first=1), state(1, last=1), state(1, phase=1),
            state(2, position=2, anchor=1, phase=1),
            state(2, position=2, first=2, last=2, phase=1),
            state(3, position=2, first=2, last=3, phase=1),
            state(3, position=3, first=1, last=3, phase=1),
            state(3, position=3, first=(1 << 64) - 1, last=3, phase=1),
        ]:
            reject(b"", workspace, INVALID)
        reject(b"xx", state(1), INVALID)
        maximum = (1 << 64) - 1
        result, output, after = call(b"x", state(maximum, position=maximum - 1, final=1))
        assert result == 24 and struct.unpack("<3Q", output) == (1, maximum - 1, maximum)
        result, output, after = call(b"", after)
        assert result == 24 and struct.unpack("<3Q", output) == (3, 0, 0) and after[40] == 2
        result, output, after = call(b"x}}", state(maximum, position=maximum - 3,
                                                  anchor=maximum - 5, first=maximum,
                                                  phase=1, final=1))
        assert result == 24 and struct.unpack("<3Q", output) == (2, maximum - 3, maximum - 2)
        reject(b"", state(4, position=4, anchor=maximum, phase=1), INVALID)
        for data in [b"{", b"{{", b"{{{", b"}", b"}}", b"}}}"]:
            result, output, after = call(data, state(len(data) + 4))
            assert result == 24 and struct.unpack("<3Q", output) == (0, 0, 0)
            assert struct.unpack_from("<Q", after, 8)[0] == 0 and after[40] == 0
        reject(b"prefix\xff", state(7, final=1), UTF8)
        malformed = [bytes([value]) for value in range(128, 256)]
        malformed += [b"\xc2x", b"\xe0\x80", b"\xed\xa0", b"\xf0\x80", b"\xf4\x90",
                      b"\xe1\x80x", b"\xf1\x80\x80x", b"\xf5\x80\x80\x80"]
        for data in malformed:
            reject(data, state(len(data), final=1), UTF8)
        for data in [b"\xc2", b"\xe0", b"\xe0\xa0", b"\xf0", b"\xf0\x90", b"\xf0\x90\x80"]:
            result, output, after = call(data, state(len(data) + 1))
            assert (result, struct.unpack("<3Q", output), struct.unpack_from("<Q", after, 8)[0]) == (24, (0, 0, 0), 0)
            reject(data, state(len(data), final=1), UTF8)
        for data in [b"x{{y", b" }}", b"   ", b"x\xff"]:
            expected = {b"x{{y": NESTED, b" }}": EMPTY, b"   ": UNTERMINATED, b"x\xff": UTF8}[data]
            reject(data, state(2 + len(data), position=2, first=(1 << 64) - 1, phase=1, final=1), expected)
        result, _, opened = call(b"{{", state(2, final=1))
        assert result == 24 and opened[40] == 1
        reject(b"", opened, UNTERMINATED)
        fixtures = {
            "": (24, []),
            "{{{{}}}}": (24, [(1, "{{}}")]),
            "é{{ \u3000name\u0085 }}😀": (24, [(1, "é"), (2, "name"), (1, "😀")]),
            "{{a}}-{{a}}": (24, [(2, "a"), (1, "-"), (2, "a")]),
            "{{{name}}}": (24, [(2, "{name"), (1, "}")]),
            "{{a{b}c}}": (24, [(2, "a{b}c")]),
            "é{{ }}": (EMPTY, 2),
            "é{{a{{b}}": (NESTED, 2),
            "é}}": (UNMATCHED, 2),
            "é{{x": (UNTERMINATED, 2),
            "{{a}}{{": (UNTERMINATED, 5),
        }
        for text, expected in fixtures.items():
            for width in [1, 2, 3, 4, 5, 7, 8, 4096]:
                assert stream(text, width) == expected, (text, width)
        for offset in range(4090, 4102):
            prefix = "x" * offset
            for text, suffix in [("{{{{", "{{"), ("}}}}", "}}"), ("é😀", "é😀")]:
                assert stream(prefix + text, 4096) == (24, [(1, prefix + suffix)])
            assert stream(prefix + "{{ \u3000name\u0085 }}", 4096) == (24, [(1, prefix), (2, "name")])
        report["status"] = "passed"
    except BaseException as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
