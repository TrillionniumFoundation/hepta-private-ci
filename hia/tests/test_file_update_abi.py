#!/usr/bin/env python3
"""Verify file-update raw framing, continuations, stable sorting and rendering.

These are independent ABI fixtures, including malformed metadata and overlapping
edits. The complete original public-crate oracle is a separate required gate.
Callback answers here are explicit fixtures, not evidence of string matching.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import ctypes
import hashlib
import json
from pathlib import Path
import random
import struct
from threading import Lock

INVALID, SHORT, INVALID_UTF8 = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD
MAX = (1 << 64) - 1
ROOT = Path(__file__).resolve().parents[2]


def words(values):
    values = tuple(values)
    return struct.pack(f"<{len(values)}Q", *values)


def unpack(data):
    assert len(data) % 8 == 0
    return struct.unpack(f"<{len(data) // 8}Q", data)


def changed(data, index, value):
    return data[:index * 8] + words((value,)) + data[(index + 1) * 8:]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def step(*, mode=0, lines=4, last=1, chunks=1, chunk=0, cursor=0,
         phase=0, answer=None, context=False, eof=False, old=(), new=(), pairs=()):
    return (words((2, mode, lines, last, chunks, chunk, cursor, phase,
                   int(answer is not None), 0 if answer is None else answer,
                   int(context), int(eof), len(old), len(new), len(pairs), 0))
            + words(old) + words(new) + b"".join(words(pair) for pair in pairs))


def render(lengths, originals, replacements):
    return (words((6, len(originals), len(replacements), len(lengths), 0, 0, 0, 0))
            + words(lengths) + words(originals)
            + b"".join(words(row) for row in replacements))


def verify(library_dir):
    build_path = library_dir / "build.json"
    build = json.loads(build_path.read_text())
    assert build["status"] == "built" and build["compiler_fixed_point"] is True
    component = build["modules"]["file_update"]
    abi = component["codex_link_abi"]
    path = library_dir / "libcodex_hia_file_update.so"
    assert component["source_sha256"] == digest(ROOT / "hia/file_update.hepta")
    assert abi["symbol"] == "codex_hia_file_update"
    assert abi["library_sha256"] == digest(path)
    assert abi["archive_sha256"] == digest(library_dir / "libcodex_hia_file_update.a")
    library = ctypes.CDLL(str(path))
    function = library.codex_hia_file_update
    function.restype = ctypes.c_uint64
    function.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    counts = {"native_calls": 0, "error_no_write_cases": 0,
              "query_calls": 0, "emit_calls": 0, "planner_pairs": 0,
              "stable_sort_pairs": 0, "reverse_render_pairs": 0}
    lock = Lock()

    def call(source, request, capacity, expected_status=0):
        # Disjoint live allocations, deliberately unaligned at all three pointers.
        arrays = []
        for data, fill in ((source, 0xCC), (request, 0x5A), (bytes(capacity), 0xA5)):
            buf = (ctypes.c_ubyte * (len(data) + 34))()
            buf[:] = bytes((fill,)) * len(buf)
            if fill != 0xA5:
                buf[17:17 + len(data)] = data
            arrays.append(buf)
        borrowed, workspace, output = arrays
        before = tuple(map(bytes, arrays))
        status = function(ctypes.byref(borrowed, 17), len(source),
                          ctypes.byref(output, 17), capacity,
                          ctypes.byref(workspace, 17), len(request))
        with lock:
            counts["native_calls"] += 1
        assert status == expected_status, (
            "status", status, expected_status, source[:24], request[:128].hex(), capacity)
        assert bytes(borrowed) == before[0], "source/canary mutation"
        assert bytes(workspace) == before[1], "workspace/canary mutation"
        if status:
            assert bytes(output) == before[2], "error published partial output"
            with lock:
                counts["error_no_write_cases"] += 1
            return b""
        operation = unpack(request[:8])[0]
        header = 96 if operation in (2, 3) else 32
        after = bytes(output)
        needed = unpack(after[17:25])[0]
        written = needed if operation & 1 else header
        assert header <= written <= capacity
        assert after[:17] == before[2][:17]
        assert after[17 + written:] == before[2][17 + written:], "out-of-plan write"
        with lock:
            counts["emit_calls" if operation & 1 else "query_calls"] += 1
        return after[17:17 + written]

    def pair(source, request, header, rows=(), *, spare=False):
        header = tuple(header)
        expected = words(header) + b"".join(words(row) for row in rows)
        assert len(expected) == header[0]
        hsize = len(header) * 8
        assert call(source, request, hsize) == words(header)
        assert call(source, changed(request, 0, unpack(request[:8])[0] + 1),
                    len(expected)) == expected
        if spare:
            assert call(source, request, len(expected) + 19) == words(header)
            assert call(source, changed(request, 0, unpack(request[:8])[0] + 1),
                        len(expected) + 19) == expected

    def parse_pair(source, *, spare=False):
        source.decode("utf-8", errors="strict")
        pieces = source.split(b"\n")
        if pieces[-1] == b"":
            pieces.pop()
        rows, start = [], 0
        for value in pieces:
            rows.append((start, len(value)))
            start += len(value) + 1
        pair(source, words((0,)),
             (32 + 16 * len(rows), len(rows), len(source),
              len(pieces[-1]) if pieces else 0), rows, spare=spare)

    # LF splitting retains CR/NUL, removes one trailing empty item, and handles
    # all canonical UTF-8 sequence boundaries independently of Rust Strings.
    parse_cases = [b"", b"a", b"\n", b"\n\n", b"\r", b"\r\n", b"a\n\n",
                   b"a\r\nb\rc\nz", b"\0\n\0", "é\n汉\r\n😀".encode()]
    for value in parse_cases:
        parse_pair(value, spare=True)
    for point in (0, 0x7F, 0x80, 0x7FF, 0x800, 0xD7FF, 0xE000, 0xFFFF,
                  0x10000, 0x10FFFF):
        parse_pair(chr(point).encode() + b"\n" + chr(point).encode())
    invalid_utf8 = [b"\x80", b"\xc0\x80", b"\xc1\xbf", b"\xc2",
                    b"\xe0\x80\x80", b"\xe0\xa0", b"\xed\xa0\x80",
                    b"\xf0\x80\x80\x80", b"\xf0\x90\x80",
                    b"\xf4\x90\x80\x80", b"\xf5\x80\x80\x80", b"\xff"]
    for value in invalid_utf8:
        for operation in (0, 1):
            call(value, words((operation,)), 96, INVALID_UTF8)

    # Explicit continuation states cover context-before-old-empty, EOF cursor
    # differences, one empty-tail retry, and Preserve context segmentation.
    def planner(request, *, action, cursor, phase=0, pattern=0, eof=0,
                records=(), semantic=0, chunk=None, spare=True):
        state = unpack(request[:128])
        index = state[5] if chunk is None else chunk
        header = (96 + 32 * len(records), action, index, cursor, phase, pattern,
                  eof, len(records), state[1], semantic, 0, 0)
        pair(b"", request, header, records, spare=spare)
        with lock:
            counts["planner_pairs"] += 1

    for mode in (0, 1):
        planner(step(mode=mode, lines=0, last=0, chunks=0),
                action=0, cursor=0)
        planner(step(mode=mode, lines=4, last=0, new=(3, 0)),
                action=3, cursor=0, chunk=1,
                records=((3 if mode == 0 else 4, 0, 0, 2),))
        planner(step(mode=mode, context=True, new=(2,), eof=True),
                action=1, cursor=0, phase=1, pattern=1)
        planner(step(mode=mode, context=True, phase=1, answer=2, new=(2,)),
                action=3, cursor=3, chunk=1, records=((4, 0, 0, 1),))
        planner(step(mode=mode, old=(2, 0), new=(3, 0), eof=True),
                action=2, cursor=0, phase=2, pattern=2, eof=1)
        planner(step(mode=mode, phase=2, old=(2, 0), new=(3, 0), eof=True),
                action=2, cursor=0, phase=3, pattern=1, eof=1)
        planner(step(mode=mode, phase=3, answer=3,
                     old=(2, 0), new=(3, 0), eof=True),
                action=3, cursor=4, chunk=1, records=((3, 1, 0, 1),))
        planner(step(mode=mode, cursor=2, phase=3, answer=2,
                     old=(0,), new=(4, 0), eof=True),
                action=3, cursor=2, chunk=1, records=((2, 0, 0, 1),))
        planner(step(mode=mode, context=True, phase=1),
                action=4, cursor=0, semantic=1)
        planner(step(mode=mode, phase=2, old=(1,)),
                action=4, cursor=0, semantic=2)
        planner(step(mode=mode, phase=3, old=(1, 0)),
                action=4, cursor=0, semantic=2)
        planner(step(mode=mode, phase=2, answer=1, old=(1, 1),
                     new=(2, 2), pairs=((MAX, MAX), (0, 0))),
                action=3, cursor=3, chunk=1, records=((1, 2, 0, 2),))
    planner(step(mode=1, lines=6, phase=2, answer=1, old=(1, 1, 1, 1),
                 new=(1, 2, 1, 3), pairs=((0, 0), (2, 2))),
            action=3, cursor=5, chunk=1, records=((2, 1, 1, 1), (4, 1, 3, 1)))
    planner(step(mode=1, phase=2, answer=0, old=(1, 1),
                 new=(1, 1), pairs=((0, 0), (1, 1))),
            action=3, cursor=2, chunk=1)
    planner(step(mode=0, cursor=3, phase=2, answer=2, old=(1, 1),
                 new=(3,), eof=True),
            action=3, cursor=4, chunk=1, records=((2, 2, 0, 1),))
    planner(step(mode=1, phase=2, answer=0, old=(1, 1), new=(1, 1),
                 pairs=((0, 0), (0, 0))),
            action=4, cursor=0, semantic=3)

    # Metadata admission errors never publish a prefix, even with a valid earlier
    # pair or record and an output buffer large enough to tempt partial writes.
    canonical_step = step(phase=2, answer=1, old=(1, 1), new=(1, 1))
    bad_steps = [changed(canonical_step, k, v) for k, v in
                 ((1, 2), (5, 2), (6, 5), (7, 4), (8, 2), (9, 4),
                  (10, 2), (11, 2), (12, MAX), (13, MAX), (14, MAX), (15, 1))]
    bad_steps += [step(phase=0, answer=0), step(phase=1),
                  step(lines=0, last=1), step(phase=3, old=(1,)),
                  step(phase=2), step(chunks=0, old=(1,)),
                  step(phase=2, cursor=2, answer=1, old=(1,)),
                  step(phase=2, answer=0, old=(1,), eof=True),
                  step(mode=1, cursor=3, phase=2, answer=2, old=(1, 1), eof=True),
                  step(cursor=2, phase=3, answer=0, old=(0,)),
                  changed(step(phase=2, old=(1,)), 9, 1)]
    for request in bad_steps:
        for operation in (2, 3):
            call(b"", changed(request, 0, operation), 512, INVALID)

    def sort_pair(keys, *, spare=False):
        request = words((4, len(keys), 0, 0)) + words(keys)
        ordered = sorted(range(len(keys)), key=lambda index: (keys[index], index))
        pair(b"", request, (32 + 8 * len(keys), len(keys), 0, 0),
             tuple((index,) for index in ordered), spare=spare)
        with lock:
            counts["stable_sort_pairs"] += 1

    rng = random.Random(0xF11E2026)
    for keys in ((), (MAX,), (4, 1, 4, 0, MAX, 1), tuple(range(127)),
                 tuple(reversed(range(127))), (7,) * 129):
        sort_pair(keys, spare=True)
    for count in range(65):
        sort_pair(tuple(rng.randrange(12) for _ in range(count)))
    sort_pair(tuple(rng.randrange(128) for _ in range(4096)))
    for field, value in ((1, MAX), (2, 1), (3, 1)):
        for op in (4, 5):
            call(b"", changed(words((op, 1, 0, 0, 3)), field, value), 128, INVALID)

    def render_pair(lengths, originals, replacements, *, spare=False):
        # Independent sequence model includes repeated pool IDs, reverse overlap,
        # delete clipping and peak scratch demand before a later shrink.
        ids = list(originals)
        peak = len(ids)
        byte_bound = sum(lengths[index] for index in originals)
        for start, old, first, count in reversed(replacements):
            del ids[start:start + old]
            ids[start:start] = range(first, first + count)
            peak = max(peak, len(ids))
            byte_bound += sum(lengths[first:first + count])
        before_empty = len(ids)
        scratch = max(peak, 2 * before_empty + 1)
        if not ids or lengths[ids[-1]] != 0:
            ids.append(1)
        rendered = []
        for index, pool_id in enumerate(ids):
            if index:
                rendered.append(0)
            rendered.append(pool_id)
        exact_bytes = sum(lengths[index] for index in rendered)
        request = render(lengths, originals, replacements)
        query = call(b"", request, 32)
        q = unpack(query)
        assert q[:3] == (32 + 8 * scratch, scratch, before_empty)
        assert exact_bytes <= q[3] <= byte_bound + before_empty
        capacities = (q[0], q[0] + 19) if spare else (q[0],)
        for capacity in capacities:
            emitted = call(b"", changed(request, 0, 7), capacity)
            assert unpack(emitted[:32]) == (q[0], len(rendered), len(ids), exact_bytes)
            assert unpack(emitted[32:32 + 8 * len(rendered)]) == tuple(rendered)
        with lock:
            counts["reverse_render_pairs"] += 1

    render_pair((1, 0), (), (), spare=True)
    render_pair((1, 0, 1, 1, 1, 1, 1, 1), (2, 3, 4),
                ((1, 2, 5, 1), (2, 1, 6, 2)), spare=True)  # a,b,c -> a,X,Z
    render_pair((1, 0, 1, 1, 1, 0), (2, 3, 4), ((1, MAX, 5, 1),), spare=True)
    render_pair((1, 0, 1, 0), (2, 3), (), spare=True)
    render_pair((1, 0, 2, 3), (2, 2, 2), ((0, 0, 3, 1), (0, 0, 3, 1)))
    for _ in range(200):
        lengths = (1, 0) + tuple(rng.randrange(0, 20) for _ in range(14))
        originals = tuple(rng.randrange(2, len(lengths)) for _ in range(rng.randrange(16)))
        replacements = []
        for _ in range(rng.randrange(8)):
            start = rng.randrange(len(originals) + 1)
            first = rng.randrange(2, len(lengths) + 1)
            replacements.append((start, rng.randrange(20), first,
                                 rng.randrange(len(lengths) - first + 1)))
        replacements.sort(key=lambda row: row[0])  # independent fixture ordering
        render_pair(lengths, originals, tuple(replacements))
    render_pair((1, 0, 2, 3), (2,) * 2048, ((0, 1, 3, 1), (1024, MAX, 4, 0)))

    base_render = render((1, 0, 1, 1), (2, 3), ((0, 1, 3, 1),))
    bad_render = [changed(base_render, index, value)
                  for index, value in ((1, MAX), (2, MAX), (3, 1), (3, MAX),
                                       (4, 1), (5, 1), (6, 1), (7, 1),
                                       (8, 0), (9, 1), (12, 1), (13, 4),
                                       (14, 3), (16, 1), (17, MAX))]
    bad_render += [
        render((1, 0, MAX), (2, 2), ()),  # repeated-ID byte sum overflow
        render((1, 0, MAX), (2,), ()),  # final LF byte bound overflow
        render((1, 0, MAX), (), ((0, 0, 2, 1), (0, 0, 2, 1))),
        render((1, 0, 2), (2,), ((1, 0, 2, 0), (0, 0, 2, 0))),
    ]
    for request in bad_render:
        for op in (6, 7):
            call(b"", changed(request, 0, op), 512, INVALID)

    # Every operation's fixed header, exact table extent and capacity boundaries.
    frames = [(b"a\nb", words((0,)), 32, 64),
              (b"", canonical_step, 96, 128),
              (b"", words((4, 3, 0, 0, 2, 1, 0)), 32, 56),
              (b"", base_render, 32, 72)]
    for source, request, header_size, needed in frames:
        op = unpack(request[:8])[0]
        for emit in (0, 1):
            frame = changed(request, 0, op + emit)
            for size in range(header_size):
                call(source, frame, size, SHORT)
            for cut in range(len(frame)):
                # Operation-specific descriptor-short is SHORT only below the
                # fixed header; truncated tables are INVALID after admission.
                fixed = {0: 8, 2: 128, 4: 32, 6: 64}[op]
                expected = SHORT if cut < fixed else INVALID
                call(source, frame[:cut], max(needed, header_size), expected)
            call(source, frame + b"\0", max(needed, header_size), INVALID)
            if op:
                call(b"x", frame, max(needed, header_size), INVALID)
        for size in range(header_size, needed):
            call(source, changed(request, 0, op + 1), size, SHORT)
    for op in (8, 15, MAX):
        call(b"", words((op,)), 32, INVALID)
    call(b"\xff", words((MAX,)), 31, SHORT)
    call(b"\xff", words((MAX,)), 32, INVALID)

    large = "é汉😀a".encode() * 220000
    parse_pair(large)
    parse_pair(b"x\n" * 70000)  # emitted table, not only input, exceeds one MiB
    before_concurrent = counts["native_calls"]

    def concurrent(worker):
        for index in range(16):
            parse_pair(parse_cases[(worker + index) % len(parse_cases)])
            sort_pair((worker, MAX, index % 3, worker, 0))
            render_pair((1, 0, 1, 2), (2, 3), ((1, 1, 2, 1),))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(concurrent, range(8)))
    return {
        "passed": True, **counts, "skipped": 0,
        "concurrent_native_calls": counts["native_calls"] - before_concurrent,
        "large_source_bytes": len(large), "large_line_plan_bytes": 32 + 16 * 70000,
        "library_sha256": digest(path), "archive_sha256": abi["archive_sha256"],
        "source_sha256": component["source_sha256"],
        "contract_sha256": digest(ROOT / "hia/file_update_buffer_contract.json"),
        "compiler_sha256": build["compiler_sha256"],
        "build_report_sha256": digest(build_path),
        "test_source_sha256": digest(Path(__file__)),
        "error_contract": "Every nonzero return preserves all buffers and canaries; query writes only its header; emit writes only within needed bytes.",
        "callback_scope": "Explicit raw continuation answers only. Existing actual HIA seek and complete-original public behavior are qualified separately.",
        "oracle_scope": "Independent raw ABI/sequence fixtures, not an extracted or substituted original Rust owner.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = {"schema": "codex.hia.file-update-abi.v1", "passed": False}
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
