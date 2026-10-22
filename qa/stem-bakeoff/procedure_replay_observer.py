"""Independent result-file observation for the bounded procedure experiment.

The observer receives the task's goal only for scoring. It reopens both files,
uses its own reference algorithms and canonicalization, and ignores an
executor's claimed success. It is independent code, not an independent human
organization, production signer, or adversarial-process trust boundary.
"""

import hashlib
import json
from pathlib import Path


def _bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode() + b"\n"


def observe(goal, source, output, expected_input_sha256):
    raw = Path(source).read_bytes()
    input_digest = hashlib.sha256(raw).hexdigest()
    result = {"input_sha256": input_digest, "input_unchanged":
              input_digest == expected_input_sha256, "output_exists": False,
              "success": False, "observer_error": None}
    try:
        document = json.loads(raw)
        rows = document["records"]
        if goal == "latest_by_id":
            # Reverse scan + first occurrence, independent of executor's map replacement.
            ids, kept = set(), []
            for index in range(len(rows) - 1, -1, -1):
                if rows[index]["id"] not in ids:
                    ids.add(rows[index]["id"])
                    kept.append(rows[index])
            expected = sorted(kept, key=lambda row: row["id"])
        elif goal == "group_totals":
            expected = [{"group": group, "total": sum(row["score"] for row in rows
                        if row["group"] == group)} for group in sorted({r["group"] for r in rows})]
        elif goal == "threshold_filter":
            expected = []
            for row in rows:
                if not row["score"] < document["threshold"]:
                    expected.append(row)
        elif goal == "stable_score_sort":
            expected = [rows[index] for index in sorted(range(len(rows)),
                        key=lambda index: (rows[index]["score"], index))]
        else:
            raise ValueError("observer received an unknown goal")
        expected_bytes = _bytes(expected)
        result["expected_output_sha256"] = hashlib.sha256(expected_bytes).hexdigest()
        output = Path(output)
        if output.is_symlink() or not output.is_file() or output.stat().st_size > 65536:
            raise ValueError("missing, linked or oversized result file")
        actual = output.read_bytes()
        result.update(output_exists=True, output_sha256=hashlib.sha256(actual).hexdigest(),
                      output_utf8=actual.decode("utf-8"), output_bytes=len(actual))
        result["success"] = (result["input_unchanged"] and actual == expected_bytes
                             and json.loads(actual) == expected)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        result["observer_error"] = type(exc).__name__ + ": " + str(exc)
    return result
