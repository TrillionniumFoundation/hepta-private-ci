"""Raw framing and arbitrary-byte contract gate; not an original-crate oracle."""
from pathlib import Path
import json
import re
import struct
import time

from .transport import INVALID
from .transport import Native
from .transport import SHORT
from .transport import identity

PATTERN = re.compile(rb"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")
UUID = b"00112233-4455-6677-8899-aabbccddeeff"


def run_cases(native, report):
    correct = struct.pack("<4Q", 1, 0, 0, 0)
    for size in range(32):
        native.call(UUID, correct[:size], 64, SHORT, category="short_workspace")
    for size in range(64):
        native.call(UUID, correct, size, SHORT, category="short_output")
        native.call(UUID, b"\xff" * 40, size, SHORT, category="minimum_precedes_invalid_frame")
    for size in range(33, 65):
        native.call(UUID, correct + b"\x72" * (size - 32), 80, INVALID, category="workspace_exact_length")
    for index in range(4):
        values = [0, 1, 2, 3, 0xFF, 1 << 31, 1 << 32, 1 << 63, (1 << 64) - 1]
        values += [1 << bit for bit in range(64)] if index >= 2 else []
        for value in sorted(set(values)):
            words = [1, 0, 0, 0]
            words[index] = value
            valid = words[0] == 1 and words[1] in (0, 1) and words[2:] == [0, 0]
            if not valid:
                native.call(UUID, struct.pack("<4Q", *words), 256, INVALID, category="invalid_frame_word")
    for count in (1, 2, 3, 16, 65):
        data = UUID * count
        needed = 64 + 16 * count
        for capacity in sorted(set([64, 65, 71, 72, 79, needed - 1])):
            native.call(data, struct.pack("<4Q", 1, 1, 0, 0), capacity, SHORT, category="final_emit_capacity_no_write")
        rows = [(36 * i, 36 * (i + 1)) for i in range(count)]
        native.valid(data, rows, 0, extra=needed + 9, category="query_preserves_large_tail")
        native.valid(data, rows, 1, extra=0, category="emit_exact_capacity")
    # All 256 byte values at each of the 36 pattern positions, including
    # non-UTF8 inputs. This does not claim invalid bytes are Rust &str values.
    mutations = 0
    for index in range(36):
        for value in range(256):
            data = UUID[:index] + bytes([value]) + UUID[index + 1:]
            rows = [m.span() for m in PATTERN.finditer(data)]
            native.valid(data, rows, 0, category="all_byte_position_mutations")
            native.valid(data, rows, 1, category="all_byte_position_mutations")
            mutations += 1
    report["byte_position_mutations"] = mutations
    for malformed in (b"\xff", b"\xc0\xaf", b"\xed\xa0\x80", b"\xf4\x90\x80\x80", b"\x80\0\r\n"):
        for data in (malformed + UUID, UUID + malformed, malformed + UUID + malformed + UUID):
            rows = [m.span() for m in PATTERN.finditer(data)]
            for op in (0, 1):
                native.valid(data, rows, op, category="arbitrary_bytes_around_matches")
    for data in (b"", b"x" * (2 * 1024 * 1024 + 7), UUID * 65537):
        rows = [m.span() for m in PATTERN.finditer(data)]
        for op in (0, 1):
            native.valid(data, rows, op, category="empty_and_unbounded_actual_buffers")
        report["largest_source_bytes"] = max(report.get("largest_source_bytes", 0), len(data))
        report["largest_written_table_bytes"] = max(report.get("largest_written_table_bytes", 0), 64 + 16 * len(rows))
    # Interleave independent sources and operations in one worker. A truly
    # simultaneous-thread qualification remains separate and is not claimed.
    for sequence in range(128):
        data = bytes([sequence]) + UUID + b"\xff" + UUID
        rows = [m.span() for m in PATTERN.finditer(data)]
        native.valid(data, rows, 0, category="independent_call_interleaving")
        native.valid(b"no match", [], 1, category="independent_call_interleaving")
        native.valid(data, rows, 1, category="independent_call_interleaving")
    report["independent_interleavings"] = 128
    assert native.counts == {'calls': 19232, 'query': 9367, 'emit': 9495, 'errors_no_write': 370}
