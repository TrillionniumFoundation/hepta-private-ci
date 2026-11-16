"""Four fixed local-file procedures. No model chooses arbitrary code or paths.

This is a controlled research catalog, not execution authority. All functions
read the same JSON format and write a fresh JSON result in a caller-owned temp
directory. The observer is a separate module and never calls these transforms.
"""

import hashlib
import json
from pathlib import Path
import time


CONTRACTS = (
    {"id": "latest_by_id", "version": 1,
     "goal": "Keep the last input occurrence of each id; emit records sorted by id.",
     "steps": ["read_utf8_json", "validate_records", "replace_by_id_in_input_order",
               "sort_ids", "write_new_canonical_json"],
     "output": "JSON list of complete records, one per id"},
    {"id": "group_totals", "version": 1,
     "goal": "Sum every score for each group; emit group and total rows sorted by group.",
     "steps": ["read_utf8_json", "validate_records", "sum_scores_by_group",
               "sort_groups", "write_new_canonical_json"],
     "output": "JSON list of {group, total} objects"},
    {"id": "threshold_filter", "version": 1,
     "goal": "Keep records with score >= threshold, preserving input order and duplicates.",
     "steps": ["read_utf8_json", "validate_records", "compare_inclusive_threshold",
               "preserve_input_order", "write_new_canonical_json"],
     "output": "JSON list of complete qualifying records"},
    {"id": "stable_score_sort", "version": 1,
     "goal": "Keep all records and sort by ascending score, preserving input order on ties.",
     "steps": ["read_utf8_json", "validate_records", "stable_ascending_score_sort",
               "retain_duplicates", "write_new_canonical_json"],
     "output": "JSON list of all complete input records"},
)
MAX_INPUT_BYTES = 32768
MAX_RECORDS = 64


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_input(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("input must be a bounded regular file")
    raw = path.read_bytes()
    data = json.loads(raw)
    if (set(data) != {"records", "threshold"} or type(data["threshold"]) is not int
            or not -10000 <= data["threshold"] <= 10000
            or not isinstance(data["records"], list)
            or not 1 <= len(data["records"]) <= MAX_RECORDS):
        raise ValueError("invalid input shape")
    for row in data["records"]:
        if (not isinstance(row, dict) or set(row) != {"id", "group", "score", "note"}
                or any(not isinstance(row[k], str) or not 1 <= len(row[k]) <= 64
                       for k in ("id", "group", "note"))
                or type(row["score"]) is not int or not -10000 <= row["score"] <= 10000):
            raise ValueError("invalid record")
    return raw, data


def latest_by_id(rows, threshold):
    latest = {}
    for row in rows:
        latest[row["id"]] = row
    return [latest[key] for key in sorted(latest)]


def group_totals(rows, threshold):
    totals = {}
    for row in rows:
        totals[row["group"]] = totals.get(row["group"], 0) + row["score"]
    return [{"group": key, "total": totals[key]} for key in sorted(totals)]


def threshold_filter(rows, threshold):
    return [row for row in rows if row["score"] >= threshold]


def stable_score_sort(rows, threshold):
    return sorted(rows, key=lambda row: row["score"])


_EXECUTORS = (latest_by_id, group_totals, threshold_filter, stable_score_sort)


def execute(choice, source, output):
    """Exactly one selected execution; failures remain charged attempts."""
    if type(choice) is not int or not 0 <= choice < len(CONTRACTS):
        raise ValueError("unknown fixed procedure")
    source, output = Path(source), Path(output)
    if output.parent != source.parent or output.name != "output.json":
        raise ValueError("output must be the fixed sibling output.json")
    start = time.perf_counter_ns()
    trace = []
    error = None
    try:
        raw, data = read_input(source)
        trace.append({"step": "read_and_validate", "input_sha256": sha(raw),
                      "rows": len(data["records"])})
        result = _EXECUTORS[choice](data["records"], data["threshold"])
        trace.append({"step": "transform", "contract": CONTRACTS[choice]["id"]})
        encoded = canonical(result) + b"\n"
        with output.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
        trace.append({"step": "write_new_output", "bytes": len(encoded),
                      "output_sha256": sha(encoded)})
    except (ValueError, OSError, TypeError, KeyError) as exc:
        error = type(exc).__name__ + ": " + str(exc)
    return {"contract": CONTRACTS[choice]["id"], "trace": trace,
            "execution_error": error, "execution_calls": 1,
            "elapsed_ns": time.perf_counter_ns() - start}
