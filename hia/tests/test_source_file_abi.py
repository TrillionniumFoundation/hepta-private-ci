#!/usr/bin/env python3
"""Check the actual SourceFile native frame, plans, UTF-8 and atomic errors.

These are explicit ABI fixtures. The separate public-caller gate compares the
complete original Rust SourceFile implementation, including multi-apply state.
"""

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
ROOT = Path(__file__).resolve().parents[2]
LITERALS = (b"\n", b"\r\n", b"\r")


def words(values):
    return struct.pack(f"<{len(values)}Q", *values)


def request(operation, lengths, lines=(), replacements=(), inserted=(), preferred=1, parse_id=0):
    header = (operation, len(lengths), len(lines), len(replacements), len(inserted), preferred, parse_id, 0)
    return (words(header) + words(lengths) + b"".join(map(words, lines))
            + b"".join(map(words, replacements)) + words(inserted))


def parse_request(operation, source):
    return request(operation, (1, 2, 1, len(source)), preferred=0, parse_id=3)


def state_request(operation, texts, lines=(), replacements=(), inserted=(), preferred=1):
    pool = LITERALS + tuple(texts)
    return b"".join(pool), request(operation, tuple(map(len, pool)), lines, replacements, inserted, preferred)


def changed_word(frame, index, value):
    return frame[:index * 8] + words((value,)) + frame[(index + 1) * 8:]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(library_dir):
    path = library_dir / "libcodex_hia_source_file.so"
    build_path = library_dir / "build.json"
    build = json.loads(build_path.read_text())
    assert build["status"] == "built" and build["compiler_fixed_point"] is True
    component = build["modules"]["source_file"]
    abi = component["codex_link_abi"]
    assert component["source_sha256"] == digest(ROOT / "hia/source_file.hepta")
    assert abi["symbol"] == "codex_hia_source_file"
    assert abi["library_sha256"] == digest(path)
    assert abi["archive_sha256"] == digest(library_dir / "libcodex_hia_source_file.a")
    library = ctypes.CDLL(str(path))
    function = library.codex_hia_source_file
    function.restype = ctypes.c_uint64
    function.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    counts = {"native_calls": 0, "error_no_write_cases": 0, "query_calls": 0, "emit_calls": 0,
              "strict_trusted_plan_comparisons": 0}
    count_lock = Lock()

    def invoke(source, frame, expected_status=0, expected=None, output_size=40):
        # Seventeen-byte guards deliberately make every borrowed pointer unaligned.
        borrowed = (ctypes.c_ubyte * (len(source) + 34)).from_buffer_copy(b"\xcc" * (len(source) + 34))
        workspace = (ctypes.c_ubyte * (len(frame) + 34)).from_buffer_copy(b"\x5a" * (len(frame) + 34))
        full_size = expected[0][0] if expected is not None else 40
        allocation = max(40, output_size, full_size) + 34
        output = (ctypes.c_ubyte * allocation).from_buffer_copy(b"\xa5" * allocation)
        borrowed[17:17 + len(source)] = source
        workspace[17:17 + len(frame)] = frame
        before = bytes(borrowed), bytes(workspace), bytes(output)
        status = function(ctypes.byref(borrowed, 17), len(source), ctypes.byref(output, 17), output_size,
                          ctypes.byref(workspace, 17), len(frame))
        with count_lock:
            counts["native_calls"] += 1
        assert status == expected_status, (source[:24], frame[:64].hex(), status, expected_status)
        assert bytes(borrowed) == before[0], "source or its canaries changed"
        assert bytes(workspace) == before[1], "workspace or its canaries changed"
        if status != 0:
            assert bytes(output) == before[2], "an error changed output or its canaries"
            with count_lock:
                counts["error_no_write_cases"] += 1
            return
        assert expected is not None, "every successful call needs an explicit complete plan"
        operation = struct.unpack_from("<Q", frame)[0]
        header, rows = expected
        published = words(header)
        if operation % 2:
            published += b"".join(map(words, rows))
        after = bytes(output)
        assert after[17:17 + len(published)] == published, (operation, header, rows[:4], after[17:57].hex())
        assert after[:17] == before[2][:17] and after[17 + len(published):] == before[2][17 + len(published):], "success wrote outside its published plan"
        with count_lock:
            counts["emit_calls" if operation % 2 else "query_calls"] += 1

    def pair(source, frame, rows, logical, total, preferred, expanded=False):
        operation = struct.unpack_from("<Q", frame)[0]
        assert operation in (0, 2, 4, 6)
        rows = tuple(rows)
        expected = ((40 + 32 * len(rows), len(rows), logical, total, preferred), rows)
        for profile in (0, 8):
            query = changed_word(frame, 0, operation + profile)
            emit = changed_word(frame, 0, operation + profile + 1)
            invoke(source, query, expected=expected)
            invoke(source, emit, expected=expected, output_size=expected[0][0])
            if expanded:
                invoke(source, query, expected=expected, output_size=expected[0][0] + 19)
                invoke(source, emit, expected=expected, output_size=expected[0][0] + 19)
        with count_lock:
            counts["strict_trusted_plan_comparisons"] += 1

    parse_cases = [
        (b"", (), 1), (b"x", ((3, 0, 1, 0),), 1),
        (b"\n", ((3, 0, 0, 1),), 1), (b"\r", ((3, 0, 0, 3),), 3),
        (b"\r\n", ((3, 0, 0, 2),), 2),
        (b"\r\r\n", ((3, 0, 0, 3), (3, 1, 0, 2)), 3),
        (b"\n\r", ((3, 0, 0, 1), (3, 1, 0, 3)), 1),
        (b"a\n\n", ((3, 0, 1, 1), (3, 2, 0, 1)), 1),
        (b"a\r\nb\rc\nd", ((3, 0, 1, 2), (3, 3, 1, 3), (3, 5, 1, 1), (3, 7, 1, 0)), 2),
        ("é\r\n汉\na😀".encode(), ((3, 0, 2, 2), (3, 4, 3, 1), (3, 8, 5, 0)), 2),
    ]
    for source, rows, preferred in parse_cases:
        pair(source, parse_request(0, source), rows, len(rows), len(source), preferred, expanded=True)
    for prefix in range(33):
        source = b"a" * prefix + b"\r\nx"
        pair(source, parse_request(0, source), ((3, 0, prefix, 2), (3, prefix + 2, 1, 0)), 2, len(source), 2)
    for text in ["\0é汉😀", "\u007f\u0080\u07ff\u0800\ud7ff\ue000\uffff\U00010000\U0010ffff", "\u0085\u2028\u2029"]:
        source = text.encode()
        pair(source, parse_request(0, source), ((3, 0, len(source), 0),), 1, len(source), 1)

    # Explicit multi-operation plans retain logical inserted lines and style.
    texts = (b"a\r\nb\rc\nd", b"inside\r\nstill", b"", b"next")
    lines = ((3, 0, 1, 2), (3, 3, 1, 3), (3, 5, 1, 1), (3, 7, 1, 0))
    source, frame = state_request(4, texts, lines, preferred=2)
    pair(source, frame, ((3, 0, 1, 0), (3, 3, 1, 0), (3, 5, 1, 0), (3, 7, 1, 0)), 4, 4, 2, expanded=True)
    source, frame = state_request(6, texts, lines, preferred=2)
    pair(source, frame, ((3, 0, 1, 0), (1, 0, 2, 0), (3, 3, 1, 0), (2, 0, 1, 0),
                        (3, 5, 1, 0), (0, 0, 1, 0), (3, 7, 1, 0)), 4, 8, 2, expanded=True)
    source, frame = state_request(2, texts, lines, preferred=2)
    pair(source, frame, lines[:3] + ((3, 7, 1, 2),), 4, 10, 2, expanded=True)
    inserted_lines = (lines[0], (4, 0, 13, 2), (5, 0, 0, 2), lines[2], (3, 7, 1, 2))
    source, frame = state_request(2, texts, lines, ((1, 1, 2),), (4, 5), preferred=2)
    pair(source, frame, inserted_lines, 5, 25, 2)
    source, frame = state_request(2, texts, inserted_lines, ((1, 1, 1),), (6,), preferred=2)
    pair(source, frame, (lines[0], (6, 0, 4, 2), (5, 0, 0, 2), lines[2], (3, 7, 1, 2)), 5, 16, 2)
    for preferred in (1, 2, 3):
        source, frame = state_request(2, texts, lines, ((0, U64_MAX, 0),), preferred=preferred)
        pair(source, frame, (), 0, 0, preferred)
        for operation in (2, 4, 6):
            source, frame = state_request(operation, texts, preferred=preferred)
            pair(source, frame, (), 0, 0, preferred)
        source, frame = state_request(2, texts, replacements=((0, 0, 1),), inserted=(6,), preferred=preferred)
        pair(source, frame, ((6, 0, 4, preferred),), 1, 4 + len(LITERALS[preferred - 1]), preferred)
    source, frame = state_request(6, (b"",), ((3, 0, 0, 0), (3, 0, 0, 2)), preferred=2)
    pair(source, frame, ((3, 0, 0, 0), (3, 0, 0, 0), (1, 0, 2, 0)), 2, 2, 2)

    # MAX logical positions still consume only the finite existing line table.
    kept = ((3, 0, 1, 2), (3, 3, 1, 2))
    tail = (4, 0, 4, 2)
    maximum_cases = [
        (((U64_MAX, 0, 1),), (4,), kept + (tail,), 12),
        (((0, U64_MAX, 1),), (4,), (tail,), 6),
        (((U64_MAX - 3, 3, 1),), (4,), kept + (tail,), 12),
        (((0, U64_MAX, 0), (U64_MAX, 0, 1)), (4,), (tail,), 6),
        (((U64_MAX, 0, 1), (U64_MAX, 0, 1)), (4, 4), kept + (tail, tail), 18),
        (((1, U64_MAX - 1, 1),), (4,), (kept[0], tail), 9),
    ]
    for replacements, inserted, expected, total in maximum_cases:
        source, frame = state_request(2, (b"a\r\nb", b"tail"), ((3, 0, 1, 2), (3, 3, 1, 0)), replacements, inserted, 2)
        pair(source, frame, expected, len(expected), total, 2)

    # Overlap and empty end spans are legal. Internal CR/LF never reparses them.
    overlapping = ((3, 1, 2, 0), (3, 1, 11, 3), (3, 13, 0, 0))
    source, frame = state_request(4, ("aé\r\n汉😀z".encode(),), overlapping)
    pair(source, frame, ((3, 1, 2, 0), (3, 1, 11, 0), (3, 13, 0, 0)), 3, 13, 1)
    source, frame = state_request(2, ("aé\r\n汉😀z".encode(),), overlapping)
    pair(source, frame, ((3, 1, 2, 1), (3, 1, 11, 3), (3, 13, 0, 1)), 3, 16, 1)

    for operation in range(16):
        if (operation & 7) < 2:
            source, frame = b"a\nb", parse_request(operation, b"a\nb")
        else:
            source, frame = state_request(operation, (b"a",), ((3, 0, 1, 0),))
        for size in range(40):
            invoke(source, frame, SHORT, output_size=size)
        for size in range(64):
            invoke(source, frame[:size], SHORT)
        for size in range(64, len(frame)):
            invoke(source, frame[:size], INVALID)
        for extra in (b"\0", b"\0" * 8, b"\0" * 64):
            invoke(source, frame + extra, INVALID)
        invoke(source, changed_word(frame, 7, 1), INVALID)
        for index, huge in [(1, U64_MAX), (1, U64_MAX // 8 + 1), (2, U64_MAX // 32 + 1),
                            (3, U64_MAX // 24 + 1), (4, U64_MAX // 8 + 1)]:
            invoke(source, changed_word(frame, index, huge), INVALID)
    for operation in (16, 17, 255, 1 << 32, (1 << 32) + 7, 1 << 63, U64_MAX):
        invoke(b"a", parse_request(operation, b"a"), INVALID)
    for index, value in [(5, 1), (5, U64_MAX), (6, 0), (6, 4), (8, 0), (9, 1), (10, 2), (11, 0), (11, U64_MAX)]:
        for operation in (0, 1, 8, 9):
            invoke(b"a", changed_word(parse_request(operation, b"a"), index, value), INVALID)
    for operation in (0, 1, 8, 9):
        for lengths in [(1, 2, 1), (1, 2, 1, 1, 0)]:
            invoke(b"a", request(operation, lengths, preferred=0, parse_id=3), INVALID)
        for field in ("lines", "replacements", "inserted"):
            values = {"lines": ((3, 0, 1, 0),), "replacements": ((0, 0, 0),), "inserted": (3,)}
            invoke(b"a", request(operation, (1, 2, 1, 1), preferred=0, parse_id=3, **{field: values[field]}), INVALID)

    for operation in (*range(2, 8), *range(10, 16)):
        source, frame = state_request(operation, ("é😀汉".encode(),), ((3, 0, 9, 0),))
        for index, value in [(5, 0), (5, 4), (5, U64_MAX), (5, (1 << 32) + 1), (6, 3),
                             (8, 0), (9, 1), (10, 2), (11, U64_MAX), (11, (1 << 32) + 9)]:
            invoke(source, changed_word(frame, index, value), INVALID)
        for lengths in [(), (1,), (1, 2), (1, 2, 1)]:
            invoke(b"".join(LITERALS[:len(lengths)]), request(operation, lengths), INVALID)
        invoke(source[:-1], frame, INVALID)
        invoke(source + b"x", frame, INVALID)
        for offset in range(4):
            corrupted = source[:offset] + b"x" + source[offset + 1:]
            invoke(corrupted, frame, INVALID)
        for line in [(0, 0, 1, 0), (2, 0, 1, 0), (4, 0, 0, 0), (U64_MAX, 0, 0, 0),
                     ((1 << 32) + 3, 0, 1, 0), (3, 10, 0, 0), (3, U64_MAX, 0, 0),
                     (3, 1 << 32, 0, 0), (3, 0, 10, 0), (3, 1, U64_MAX, 0),
                     (3, 0, (1 << 32) + 1, 0), (3, 0, 0, 4), (3, 0, 0, (1 << 32) + 1)]:
            bad_source, bad_frame = state_request(operation, ("é😀汉".encode(),), (line,))
            invoke(bad_source, bad_frame, INVALID)
        for start in range(10):
            for end in range(start, 10):
                if start not in (0, 2, 6, 9) or end not in (0, 2, 6, 9):
                    bad_source, bad_frame = state_request(operation, ("é😀汉".encode(),), ((3, start, end - start, 0),))
                    invoke(bad_source, bad_frame, INVALID)
        # The whole source is UTF-8, but the declared pool boundary bisects é.
        invoke(b"\n\r\n\r\xc3\xa9", request(operation, (1, 2, 1, 1, 1)), INVALID)
    for operation in (4, 5, 6, 7, 12, 13, 14, 15):
        source, frame = state_request(operation, (b"a",), replacements=((0, 0, 0),))
        invoke(source, frame, INVALID)
        source, frame = state_request(operation, (b"a",), inserted=(3,))
        invoke(source, frame, INVALID)
    for operation in (2, 3, 10, 11):
        for replacements, inserted in [
            (((2, 0, 0), (1, 0, 0)), ()), (((0, 2, 0), (1, 0, 0)), ()),
            (((U64_MAX, 1, 0),), ()), (((1, U64_MAX, 0),), ()),
            (((0, 0, 1),), ()), (((0, 0, 0),), (3,)),
            (((0, 0, U64_MAX), (0, 0, 1)), ()),
            (((0, 0, 1),), (0,)), (((0, 0, 1),), (2,)),
            (((0, 0, 1),), (4,)), (((0, 0, 1),), (U64_MAX,)),
        ]:
            source, frame = state_request(operation, (b"a",), replacements=replacements, inserted=inserted)
            invoke(source, frame, INVALID)

    invalid_sequences = [bytes([byte]) for byte in range(128, 256)] + [
        b"\xc0\x80", b"\xc1\xbf", b"\xe0\x80\x80", b"\xed\xa0\x80", b"\xed\xbf\xbf",
        b"\xf0\x80\x80\x80", b"\xf4\x90\x80\x80", b"\xf5\x80\x80\x80",
        b"\xc2a", b"\xe1\x80a", b"\xf1\x80\x80a", b"\xe0\x80", b"\xed\xa0",
        b"\xf0\x90", b"\xf0\x90\x80", b"\xef\xbf", b"\xc2", b"\xf4\x8f\xbf",
    ]
    for bad in invalid_sequences:
        for prefix in (b"", b"valid\r\nprefix"):
            for operation in range(8):
                if operation < 2:
                    source, frame = prefix + bad, parse_request(operation, prefix + bad)
                else:
                    source, frame = state_request(operation, (prefix + bad,))
                invoke(source, frame, INVALID_UTF8)
    # Minimum sizes precede malformed metadata, which precedes UTF-8 and
    # final emit capacity. In particular no partially computed plan may leak.
    invoke(b"\xff", changed_word(parse_request(1, b"\xff"), 0, 16), SHORT, output_size=39)
    invoke(b"\xff", parse_request(1, b"\xff")[:63], SHORT)
    invoke(b"\xff", changed_word(parse_request(1, b"\xff"), 0, 16), INVALID)
    invoke(b"a\n\xff", parse_request(1, b"a\n\xff"), INVALID_UTF8)
    emit_fixtures = [(b"a\nb", parse_request(1, b"a\nb"), 104)]
    for operation in (3, 5, 7):
        source, frame = state_request(operation, (b"a",), ((3, 0, 1, 2),))
        emit_fixtures.append((source, frame, 104 if operation == 7 else 72))
    for source, frame, needed in emit_fixtures:
        operation = struct.unpack_from("<Q", frame)[0]
        for profile in (0, 8):
            for size in range(40, needed):
                invoke(source, changed_word(frame, 0, operation + profile), SHORT, output_size=size)

    # Both backing bytes and emitted row tables cross the old 1 MiB boundary.
    large_source = "é汉😀a".encode() * 220_000
    pair(large_source, parse_request(0, large_source), ((3, 0, len(large_source), 0),), 1, len(large_source), 1)
    source, frame = state_request(2, (large_source,), ((3, 0, len(large_source), 0),), preferred=2)
    pair(source, frame, ((3, 0, len(large_source), 2),), 1, len(large_source) + 2, 2)
    dense_source = b"x\n" * 35_000
    dense_rows = tuple((3, index * 2, 1, 1) for index in range(35_000))
    pair(dense_source, parse_request(0, dense_source), dense_rows, 35_000, len(dense_source), 1)
    source, frame = state_request(4, (dense_source,), dense_rows)
    pair(source, frame, tuple((3, index * 2, 1, 0) for index in range(35_000)), 35_000, 35_000, 1)

    before_concurrent = counts["native_calls"]

    def concurrent_calls(worker):
        for iteration in range(32):
            original, rows, preferred = parse_cases[(worker + iteration) % len(parse_cases)]
            pair(original, parse_request(0, original), rows, len(rows), len(original), preferred)
            source, frame = state_request(2, (b"inside\r\nline",), replacements=((U64_MAX, 0, 1),), inserted=(3,), preferred=preferred)
            pair(source, frame, ((3, 0, 12, preferred),), 1, 12 + len(LITERALS[preferred - 1]), preferred)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(concurrent_calls, range(8)))
    return {
        "passed": True, **counts, "skipped": 0,
        "concurrent_native_calls": counts["native_calls"] - before_concurrent,
        "large_source_bytes": len(large_source), "large_plan_bytes": 40 + 32 * len(dense_rows),
        "library_sha256": digest(path), "archive_sha256": abi["archive_sha256"],
        "source_sha256": component["source_sha256"], "compiler_sha256": build["compiler_sha256"],
        "build_report_sha256": digest(build_path), "test_source_sha256": digest(Path(__file__)),
        "request_header_bytes": 64, "result_header_bytes": 40, "result_record_bytes": 32,
        "contract": "explicit complete query/emit plans; strict canonical UTF-8 profile and trusted valid-string profile; both retain complete frame/range/pool/subspan checks; live disjoint unaligned buffers; exact workspace extent",
        "error_contract": "every returned error leaves source, request, output and all canaries byte-identical",
        "oracle_scope": "explicit ABI fixtures only; complete original-Rust semantic comparison is test_native_source_file_caller.py",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = {"schema": "codex.hia.source-file-abi.v2", "passed": False}
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
