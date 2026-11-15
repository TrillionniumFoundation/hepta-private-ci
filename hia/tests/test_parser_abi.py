#!/usr/bin/env python3
"""Actual native parser plans and atomic errors; no mirrored patch grammar."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import ctypes
import hashlib
import json
from pathlib import Path
import random
import struct
import sys
from threading import Lock

ROOT = Path(__file__).resolve().parents[2]
INVALID, SHORT, INVALID_UTF8 = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD
MAX, ZERO = (1 << 64) - 1, (0,) * 8
BEGIN, END = b"*** Begin Patch", b"*** End Patch"
ADD, DELETE, UPDATE = b"*** Add File: ", b"*** Delete File: ", b"*** Update File: "


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def words(values):
    return struct.pack(f"<{len(values)}Q", *values)


def request(operation, state=ZERO, argument_0=0, argument_1=0):
    return words((1, operation, argument_0, argument_1, *state, 0, 0, 0, 0))


def changed(frame, index, value):
    return frame[:index * 8] + words((value,)) + frame[(index + 1) * 8:]


def event(kind, hunk=0, chunk=0, start=0, length=0, old=0, new=0):
    return (kind, hunk, chunk, start, length, old, new, 0)


def expected(rows=(), state=ZERO, error=0, error_line=0, argument_kind=0,
             argument_0=0, argument_1=0, processed=0, keep_start=0,
             keep_length=0, result_kind=0, auxiliary=0):
    rows = tuple(rows)
    assert state[2] == keep_length
    return ((160 + 64 * len(rows), len(rows), error, error_line, argument_kind,
             argument_0, argument_1, processed, keep_start, keep_length,
             state[0], state[1], state[3], state[4], state[5], state[6], state[7],
             result_kind, auxiliary, 1), rows)


def next_state(h):
    return (h[10], h[11], h[9], h[12], h[13], h[14], h[15], h[16])


def span(source, start, length):
    assert start <= len(source) and length <= len(source) - start
    for offset in (start, start + length):
        assert offset == len(source) or source[offset] & 0xC0 != 0x80
    payload = source[start:start + length]
    payload.decode()
    return payload


def verify(library_dir):
    build_path = library_dir / "build.json"
    build = json.loads(build_path.read_text())
    assert build["status"] == "built" and build["compiler_fixed_point"] is True
    module = build["modules"]["parser"]
    link = module["codex_link_abi"]
    path = library_dir / "libcodex_hia_parser.so"
    assert module["source_sha256"] == digest(ROOT / "hia/parser.hepta")
    assert link["symbol"] == "codex_hia_parser" and link["library_sha256"] == digest(path)
    assert link["archive_sha256"] == digest(library_dir / "libcodex_hia_parser.a")
    library = ctypes.CDLL(str(path))
    function = library.codex_hia_parser
    function.restype = ctypes.c_uint64
    function.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    counts = {"native_calls": 0, "transport_error_no_write_cases": 0, "query_calls": 0,
              "emit_calls": 0, "semantic_error_calls": 0, "strict_trusted_plan_pairs": 0,
              "largest_source_bytes": 0, "largest_required_plan_bytes": 0}
    lock = Lock()
    observed_events, observed_errors = set(), set()

    def invoke(source, frame, status=0, plan=None, capacity=160):
        borrowed = (ctypes.c_ubyte * (len(source) + 34)).from_buffer_copy(b"\xcc" * (len(source) + 34))
        control = (ctypes.c_ubyte * (len(frame) + 34)).from_buffer_copy(b"\x5a" * (len(frame) + 34))
        output = (ctypes.c_ubyte * (max(160, capacity) + 34)).from_buffer_copy(b"\xa5" * (max(160, capacity) + 34))
        borrowed[17:17 + len(source)] = source
        control[17:17 + len(frame)] = frame
        before = bytes(borrowed), bytes(control), bytes(output)
        actual = function(ctypes.byref(borrowed, 17), len(source), ctypes.byref(output, 17), capacity,
                          ctypes.byref(control, 17), len(frame))
        with lock:
            counts["native_calls"] += 1
            counts["largest_source_bytes"] = max(counts["largest_source_bytes"], len(source))
        assert actual == status, (source[:80], frame.hex(), actual, status)
        assert bytes(borrowed) == before[0], "source/guards changed"
        assert bytes(control) == before[1], "request/guards changed"
        if status:
            assert bytes(output) == before[2], "transport error wrote output/guards"
            with lock:
                counts["transport_error_no_write_cases"] += 1
            return None
        op = struct.unpack_from("<Q", frame, 8)[0]
        data = bytes(output)
        h = struct.unpack_from("<20Q", data, 17)
        assert h[0] == 160 + 64 * h[1] and h[19] == 1
        assert h[2] <= 9 and h[4] <= 2 and h[17] <= 2
        assert h[1] <= 2 * (source.count(b"\n") + 1)
        emitted = op < 16 and op % 2 == 1
        size = h[0] if emitted else 160
        assert size <= capacity
        rows = tuple(struct.unpack_from("<8Q", data, 177 + 64 * i) for i in range(h[1])) if emitted else ()
        assert data[:17] == before[2][:17] and data[17 + size:] == before[2][17 + size:], "success wrote outside its plan"
        if plan is not None:
            assert h == plan[0], (op, h, plan[0])
            if emitted:
                assert rows == tuple(plan[1]), (op, rows, plan[1])
        for row in rows:
            assert 1 <= row[0] <= 14 and row[7] == 0
        if h[4] == 1:
            span(source, h[5], h[6])
        with lock:
            counts["emit_calls" if emitted else "query_calls"] += 1
            counts["largest_required_plan_bytes"] = max(counts["largest_required_plan_bytes"], h[0])
            if h[2]:
                counts["semantic_error_calls"] += 1
                observed_errors.add(h[2])
            observed_events.update(row[0] for row in rows)
        return h, rows

    def pair(source, state=ZERO, finish=False, plan=None, expanded=False):
        op = 2 if finish else 0
        h = invoke(source, request(op, state), plan=plan)[0]
        result = invoke(source, request(op + 1, state), plan=plan, capacity=h[0])
        assert result[0] == h
        assert invoke(source, request(op + 4, state), plan=plan)[0] == h
        assert invoke(source, request(op + 5, state), plan=plan, capacity=h[0]) == result
        if expanded:
            assert invoke(source, request(op, state), plan=plan, capacity=h[0] + 23)[0] == h
            assert invoke(source, request(op + 1, state), plan=plan, capacity=h[0] + 23) == result
            invoke(source, request(op + 1, state), SHORT, capacity=h[0] - 1)
        with lock:
            counts["strict_trusted_plan_pairs"] += 1
        return result

    # Explicit fixtures pin the complete header and event bytes.
    pair(b"", plan=expected(), expanded=True)
    pair(b"", finish=True, plan=expected(error=2))
    text = b"*** Beg"
    h, _ = pair(text, plan=expected(state=(0, 0, len(text), 0, 0, 0, 0, 0), processed=len(text), keep_length=len(text)))
    text += b"in Patch\n"
    pair(text, next_state(h), plan=expected(state=(1, 1, 0, 0, 0, 0, 0, 0), processed=len(text), keep_start=len(text)))
    pair(b"bad\nignored\n", plan=expected(state=(0, 1, 0, 0, 0, 0, 0, 0), error=1, processed=4, keep_start=4), expanded=True)
    end_state = (0, 0, len(END), 0, 0, 0, 0, 0)
    pair(END, plan=expected(state=end_state, processed=len(END), keep_length=len(END)))
    pair(END, end_state, finish=True, plan=expected(state=(5, 1, 0, 0, 0, 0, 0, 0), processed=len(END), keep_start=len(END)))
    started = (1, 1, 0, 0, 0, 0, 0, 0)
    line = ADD + b"x\n"
    add_state = (10, 2, 0, 1, 0, 0, 0, 0)
    pair(line, started, plan=expected((event(2, start=len(ADD), length=1),), add_state, processed=len(line), keep_start=len(line)), expanded=True)
    line = b"+payload \t\r\r\n"
    pair(line, add_state, plan=expected((event(5, start=1, length=len(line) - 3),), (10, 3, 0, 1, 0, 0, 0, 0), processed=len(line), keep_start=len(line)))
    line = " \tbad\u2003 \n".encode()
    pair(line, started, plan=expected(state=(1, 2, 0, 0, 0, 0, 0, 0), error=5, error_line=2, argument_kind=1, argument_0=2, argument_1=3, processed=len(line), keep_start=len(line)))
    line = b"*** Environment ID:first\n"
    env_state = (33, 2, 0, 0, 0, 0, 0, 0)
    pair(line, started, plan=expected((event(1, start=19, length=5),), env_state, processed=len(line), keep_start=len(line)))
    line = b"*** Environment ID: \n"
    pair(line, env_state, plan=expected(state=(33, 3, 0, 0, 0, 0, 0, 0), error=3, processed=len(line), keep_start=len(line)))
    pair(line, started, plan=expected(state=(1, 2, 0, 0, 0, 0, 0, 0), error=4, processed=len(line), keep_start=len(line)))
    update = (28, 2, 0, 1, 2, 0, 0, 0)
    line = UPDATE + b"x\n"
    pair(line, started, plan=expected((event(4, start=len(UPDATE), length=1),), update, processed=len(line), keep_start=len(line)))
    line = END + b"\n"
    pair(line, update, plan=expected(state=(28, 3, 0, 1, 2, 0, 0, 0), error=6, error_line=2, argument_kind=2, processed=len(line), keep_start=len(line)))
    empty_chunk = (28, 3, 0, 1, 2, 1, 0, 0)
    pair(b"@@\n", update, plan=expected((event(7),), empty_chunk, processed=3, keep_start=3))
    pair(line, empty_chunk, plan=expected(state=(28, 4, 0, 1, 2, 1, 0, 0), error=7, error_line=4, processed=len(line), keep_start=len(line)))
    for line, length in [(b"@@ \t\n", 4), (ADD + b"y \t\n", len(ADD) + 1)]:
        pair(line, empty_chunk, plan=expected(state=(28, 4, 0, 1, 2, 1, 0, 0), error=8, error_line=4, argument_kind=1, argument_1=length, processed=len(line), keep_start=len(line)))
    one_line = (28, 4, 0, 1, 2, 1, 0, 1)
    pair(b"+ok\n", empty_chunk, plan=expected((event(10, start=1, length=2),), one_line, processed=4, keep_start=4))
    line = b"bad \t\n"
    pair(line, one_line, plan=expected(state=(28, 5, 0, 1, 2, 1, 0, 1), error=9, error_line=5, argument_kind=1, argument_1=len(line) - 1, processed=len(line), keep_start=len(line)))

    def trajectory(deltas):
        # Decode HIA-selected effects only. No marker classification occurs here.
        state, pending, hunks, environment = ZERO, b"", [], None
        for command, delta in deltas:
            source, old_line = pending + delta, state[1]
            finishing = command == "finish"
            h, rows = pair(source, state, finish=finishing)
            for kind, target, chunk, start, length, old, new, reserved in rows:
                assert reserved == 0 and kind <= 12
                payload = span(source, start, length)
                assert b"\n" not in payload
                if kind == 1:
                    assert (target, chunk, old, new) == (0, 0, 0, 0) and environment is None
                    environment = payload
                elif kind in (2, 3, 4):
                    assert target == len(hunks) and (chunk, old, new) == (0, 0, 0)
                    hunks.append({"kind": kind - 1, "path": payload, "contents": b"", "move": None, "chunks": [],
                                  "anchor": old_line + source[:start].count(b"\n") + 1})
                else:
                    assert target < len(hunks)
                    item = hunks[target]
                    if kind == 5:
                        assert item["kind"] == 1 and (chunk, old, new) == (0, 0, 0)
                        item["contents"] += payload + b"\n"
                    elif kind == 6:
                        assert item["kind"] == 3 and item["move"] is None and not item["chunks"]
                        assert (chunk, old, new) == (0, 0, 0)
                        item["move"] = payload
                    elif kind in (7, 8):
                        assert item["kind"] == 3 and chunk == len(item["chunks"]) and (old, new) == (0, 0)
                        if kind == 7:
                            assert (start, length) == (0, 0)
                        item["chunks"].append({"context": payload if kind == 8 else None, "old": [], "new": [], "indices": [], "eof": False})
                    else:
                        assert item["kind"] == 3 and chunk < len(item["chunks"])
                        part = item["chunks"][chunk]
                        if kind in (9, 11):
                            assert old == len(part["old"])
                            part["old"].append(payload)
                        if kind in (10, 11):
                            assert new == len(part["new"])
                            part["new"].append(payload)
                        if kind == 9:
                            assert new == 0
                        elif kind == 10:
                            assert old == 0
                        elif kind == 11:
                            part["indices"].append((old, new))
                        elif kind == 12:
                            assert (start, length, old, new) == (0, 0, 0, 0) and (part["old"] or part["new"])
                            part["eof"] = True
            assert h[17:20] == (0, 0, 1) and h[7] <= len(source)
            if h[2]:
                assert h[8] == h[7] and h[9] == 0
            else:
                assert h[7] == len(source)
            assert h[11] == old_line + (int(bool(source)) if finishing else source[:h[7]].count(b"\n"))
            pending = span(source, h[8], h[9])
            assert b"\n" not in pending
            state = next_state(h)
            assert state[3] == len(hunks) and bool(state[0] & 32) == (environment is not None)
            last = hunks[-1] if hunks else None
            assert ((state[0] >> 3) & 3) == (last["kind"] if last else 0)
            if last and last["kind"] == 3:
                parts = last["chunks"]
                assert state[4] == last["anchor"] and state[5] == len(parts)
                assert bool(state[0] & 64) == (last["move"] is not None)
                assert state[6:8] == ((len(parts[-1]["old"]), len(parts[-1]["new"])) if parts else (0, 0))
                assert bool(state[0] & 128) == (parts[-1]["eof"] if parts else False)
            else:
                assert state[4:] == (0, 0, 0, 0) and state[0] & 192 == 0

    trajectory([("push", BEGIN + b"\n"), ("push", b"*** Environment ID:remote\n"), ("push", ADD + b"a\n+x\n"),
                ("push", DELETE + b"b\n"), ("push", UPDATE + b"c\n*** Move to: d\n@@ context\n-old\n+new\n same\n*** End of File\n"),
                ("push", b" \t\n@@\n next\n"), ("push", END), ("finish", b""), ("finish", b"")])
    for line in [b"bad\nignored\n", b"@@ \t\n+discarded\n", ADD + b"other \t\n+discarded\n", END + b"\n"]:
        trajectory([("push", BEGIN + b"\n" + UPDATE + b"x\n@@\n"), ("push", line), ("push", b"+recover\n" + END + b"\n"), ("finish", b"")])
    trajectory([("push", BEGIN + b"\n" + ADD + b"x\n+pending\r"), ("finish", b""), ("push", END), ("finish", b"")])
    for width in [1, 2, 3, 7, 31]:
        text = (BEGIN + b"\r\n" + ADD + "é.txt".encode() + b"\r\n+" + "é中🙂".encode() + b"\r\r\n" + END).decode()
        trajectory([*(('push', text[i:i + width].encode()) for i in range(0, len(text), width)), ("finish", b"")])
    rng = random.Random(0x0DE5657)
    tokens = [BEGIN, END, ADD + b"x", DELETE + b"y", UPDATE + b"z", b"@@", b"@@ ctx", b"+x", b"-x", b" x", b"", b"bad", b"*** End of File", b"*** Environment ID:env"]
    for _ in range(96):
        trajectory([*(('push', rng.choice(tokens) + b"\n") for _ in range(12)), ("finish", b""), ("push", END), ("finish", b"")])

    def normalize(source, normalized=None, error=0, rows=None, lenient=True):
        operation = 10 if lenient else 8
        plan = expected(rows or (), error=error, result_kind=1, auxiliary=0 if error else len(normalized)) if rows is not None or error else None
        h = invoke(source, request(operation), plan=plan)[0]
        emitted = invoke(source, request(operation + 1), plan=plan, capacity=h[0])
        assert emitted[0] == h and h[2] == error and h[17] == 1 and h[3:17] == (0,) * 14
        assert invoke(source, request(operation + 4), plan=plan)[0] == h
        assert invoke(source, request(operation + 5), plan=plan, capacity=h[0]) == emitted
        result = bytearray()
        for row in emitted[1]:
            assert row[1:3] == (0, 0) and row[5:] == (0, 0, 0)
            if row[0] == 13:
                result.extend(span(source, row[3], row[4]))
            else:
                assert row[0] == 14 and row[3:5] == (0, 1)
                result.extend(b"\n")
        assert bytes(result) == (normalized if error == 0 else b"") and h[18] == len(result)
        invoke(source, request(operation + 1), SHORT, capacity=h[0] - 1)

    normalized = BEGIN + b"\n" + END
    rows = (event(13, start=0, length=len(BEGIN)), event(14, length=1), event(13, start=len(BEGIN) + 1, length=len(END)))
    normalize(normalized, normalized, rows=rows)
    normalize(normalized, normalized, rows=rows, lenient=False)
    for source, error in [(b"", 2), (b"wrong\nwrong", 1), (BEGIN + b"\nbad", 2)]:
        normalize(source, error=error)
    for opening in [b"<<EOF", b"<<'EOF'", b'<<"EOF"']:
        source = opening + b"\n" + BEGIN + b" \t\r\n" + END + b" \t\r\nprefixEOF"
        normalize(source, BEGIN + b" \t\n" + END + b" \t")
        normalize(source, error=1, lenient=False)
    normalize(BEGIN + b"\n+a\r\r\n" + END, BEGIN + b"\n+a\r\n" + END)
    white_space = [*range(9, 14), 0x20, 0x85, 0xA0, 0x1680, *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000]
    for code in white_space:
        pad = chr(code).encode()
        normalize(pad + normalized + pad, normalized)
    for code in [8, 14, 0x1C, 0x1F, 0x180E, 0x200B, 0xFEFF]:
        pad = chr(code).encode()
        normalize(pad + normalized + pad, error=1)
    for operation in (16, 17):
        for kind, moved in [(1, 0), (2, 0), (3, 0), (3, 1)]:
            selected = int(operation == 16 and kind == 3 and moved == 1)
            invoke(b"", request(operation, argument_0=kind, argument_1=moved), plan=expected(result_kind=2, auxiliary=selected), capacity=183)

    frame = request(0)
    for length in range(128):
        invoke(b"", frame[:length], SHORT)
    for capacity in range(160):
        invoke(b"", frame, SHORT, capacity=capacity)
    for extra in range(1, 18):
        invoke(b"", frame + b"\0" * extra, INVALID)
    for index, values in [(0, [0, 2, MAX]), (1, [18, 19, 255, MAX]), (2, [1, MAX]), (3, [1, MAX]), *[(i, [1, MAX]) for i in range(12, 16)]]:
        for value in values:
            malformed = changed(frame, index, value)
            invoke(b"", malformed, INVALID)
            invoke(b"\xff", malformed, INVALID)
            invoke(b"\xff", malformed, SHORT, capacity=159)
    invalid_states = [(6, 0, 0, 0, 0, 0, 0, 0), (7, 0, 0, 0, 0, 0, 0, 0),
                      (32, 1, 0, 0, 0, 0, 0, 0), (0, 1, 0, 1, 0, 0, 0, 0),
                      (8, 1, 0, 0, 0, 0, 0, 0), (11, 1, 0, 1, 0, 0, 0, 0),
                      (28, 1, 0, 1, 0, 0, 0, 0), (28, 1, 0, 1, 2, 0, 0, 0),
                      (28, 2, 0, 1, 2, 0, 1, 0), (156, 2, 0, 1, 2, 0, 0, 0),
                      (29, 2, 0, 1, 2, 0, 0, 0), (29, 2, 0, 1, 2, 1, 0, 0),
                      (10, 1, 0, 2, 0, 0, 0, 0), (10, 2, 0, 1, 1, 0, 0, 0)]
    invalid_states += [(1 << bit, 0, 0, 0, 0, 0, 0, 0) for bit in range(8, 64)]
    for state in invalid_states:
        for op in (0, 1, 4, 5):
            invoke(b"", request(op, state), INVALID)
    for op in range(8):
        invoke(b"x", request(op, (0, 0, 2, 0, 0, 0, 0, 0)), INVALID)
    for op in (2, 3, 6, 7):
        invoke(b"x", request(op), INVALID)
    for op in range(8, 18):
        invoke(b"", request(op, started, argument_0=3 if op >= 16 else 0), INVALID)
    for op in (16, 17):
        for kind, move in [(0, 0), (4, 0), (MAX, 0), (1, 1), (2, 1), (3, 2), (3, MAX)]:
            invoke(b"", request(op, argument_0=kind, argument_1=move), INVALID)
        invoke(b"\xff", request(op, argument_0=3), INVALID)
    bad_utf8 = [bytes([c]) for c in range(0x80, 256)]
    bad_utf8 += [b"\xc0\x80", b"\xc1\xbf", b"\xe0\x9f\xbf", b"\xed\xa0\x80", b"\xf0\x8f\xbf\xbf", b"\xf4\x90\x80\x80", b"\xf5\x80\x80\x80", b"\xe2\x82", b"\xf0\x90\x80"]
    for invalid in bad_utf8:
        for source in (invalid, BEGIN + b"\n" + invalid, b"x" * 33 + invalid + b"tail"):
            for op in (0, 1, 8, 9, 10, 11):
                invoke(source, request(op), INVALID_UTF8)
            for op in (2, 3):
                invoke(source, request(op, (0, 0, len(source), 0, 0, 0, 0, 0)), INVALID_UTF8)
    for op in range(4):
        if op < 2:
            invoke("é".encode(), request(op, (0, 0, 1, 0, 0, 0, 0, 0)), INVALID)
        invoke(b"x\ny", request(op, (0, 0, 3, 0, 0, 0, 0, 0)), INVALID)
    maximum_state = (0, MAX, 0, 0, 0, 0, 0, 0)
    pair(b"", maximum_state, plan=expected(state=maximum_state))
    for op in (0, 1, 4, 5):
        invoke(b"\n", request(op, maximum_state), INVALID)
    for op in (2, 3, 6, 7):
        invoke(b"x", request(op, (0, MAX, 1, 0, 0, 0, 0, 0)), INVALID)

    huge = BEGIN + b"\n" + ADD + b"large\n+" + b"x" * 2_200_000 + b"\n" + END + b"\n"
    trajectory([("push", huge), ("finish", b"")])
    dense = BEGIN + b"\n" + UPDATE + b"x\n" + b"+x\n" * 20_000 + END + b"\n"
    trajectory([("push", dense), ("finish", b"")])

    def concurrent(index):
        name = f"t{index}".encode()
        source = BEGIN + b"\n" + ADD + name + b"\n+x\n" + END + b"\n"
        rows = (event(2, start=len(BEGIN) + 1 + len(ADD), length=len(name)), event(5, start=source.index(b"+x") + 1, length=1))
        return pair(source, plan=expected(rows, (13, 4, 0, 1, 0, 0, 0, 0), processed=len(source), keep_start=len(source)))
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert len(list(executor.map(concurrent, range(256)))) == 256
    assert observed_events == set(range(1, 15)), observed_events
    assert observed_errors == set(range(1, 10)), observed_errors
    assert module["source_sha256"] == digest(ROOT / "hia/parser.hepta")
    return {
        "passed": True, **counts, "concurrent_native_calls": 1024, "skipped": 0,
        "all_event_kinds_observed": sorted(observed_events), "all_semantic_errors_observed": sorted(observed_errors),
        "source_sha256": module["source_sha256"], "library_sha256": link["library_sha256"],
        "archive_sha256": link["archive_sha256"], "build_report_sha256": digest(build_path),
        "contract_sha256": digest(ROOT / "hia/parser_buffer_contract.json"), "test_sha256": digest(Path(__file__)),
        "error_contract": "all returned transport errors preserve every borrowed byte and guard; semantic errors publish committed-prefix plans",
        "trusted_scope": "valid UTF-8 and unchanged native-selected pending; malformed UTF-8/prefix bytes are tested only on strict entries",
        "oracle_scope": "exact fixed ABI plans and legal trajectory event/state consistency; complete original Rust semantics are a separate mandatory public-caller gate",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = {"schema": "codex.hia.parser-abi.v1", "passed": False}
    try:
        report.update(verify(args.library_dir.resolve(strict=True)))
    except (OSError, AssertionError, AttributeError, KeyError, ValueError, struct.error) as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(report["error"], file=sys.stderr)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
