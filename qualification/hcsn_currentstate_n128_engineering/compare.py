"""Third coordinate-stream comparator; imports neither candidate nor oracle."""

import json
from pathlib import Path


def read_stream(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    keys = [json.dumps(row["key"], separators=(",", ":")) for row in rows]
    if len(keys) != len(set(keys)) or keys != sorted(keys):
        raise ValueError("coordinate stream must be sorted and unique")
    if any(set(row) != {"key", "fp64_le"} or len(row["fp64_le"]) != 16 for row in rows):
        raise ValueError("coordinate stream schema")
    return rows


def compare(left_path, right_path):
    left, right = read_stream(left_path), read_stream(right_path)
    if [row["key"] for row in left] != [row["key"] for row in right]:
        raise ValueError("coordinate denominator mismatch")
    mismatches = [
        row["key"]
        for row, other in zip(left, right)
        if row["fp64_le"] != other["fp64_le"]
    ]
    return {
        "coordinates": len(left),
        "mismatches": len(mismatches),
        "passed": not mismatches,
    }
