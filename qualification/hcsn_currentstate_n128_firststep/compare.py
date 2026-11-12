"""Third-source complete coordinate comparison."""

import json
import math
import struct


TOLERANCE = 2e-12


def compare(candidate_rows, oracle_rows):
    if [row["key"] for row in candidate_rows] != [row["key"] for row in oracle_rows]:
        raise ValueError("coordinate denominator differs")
    mismatches = 0
    max_abs = 0.0
    exact = 0
    for left, right in zip(candidate_rows, oracle_rows):
        lv = struct.unpack("<d", bytes.fromhex(left["fp64_le"]))[0]
        rv = struct.unpack("<d", bytes.fromhex(right["fp64_le"]))[0]
        if not math.isfinite(lv) or not math.isfinite(rv):
            raise ValueError("nonfinite comparison")
        if left["fp64_le"] == right["fp64_le"]:
            exact += 1
        error = abs(lv - rv)
        max_abs = max(max_abs, error)
        if error > TOLERANCE:
            mismatches += 1
    return {
        "coordinates": len(candidate_rows),
        "bitwise_equal": exact,
        "tolerance": TOLERANCE,
        "max_abs": max_abs,
        "failures": mismatches,
        "passed": mismatches == 0,
    }


def jsonl(rows):
    return "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)
