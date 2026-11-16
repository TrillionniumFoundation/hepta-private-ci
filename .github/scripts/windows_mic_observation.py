#!/usr/bin/env python3
"""Keep a failed MIC isolation hypothesis separate from admission regression PASS."""

import argparse
import hashlib
import json
from pathlib import Path
import re


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key: " + key)
        result[key] = value
    return result


def canonical(value):
    # JSON distinguishes true from 1, unlike Python's dictionary equality.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def validate_transcript(text):
    prefix = "MIC_CASE_JSON "
    rows = [
        json.loads(line.strip()[len(prefix) :], object_pairs_hook=unique_object)
        for line in text.splitlines()
        if line.strip().startswith(prefix)
    ]
    require(len(rows) == 5, "Five complete MIC cases must be recorded exactly once")
    require(
        all(isinstance(row, dict) and type(row.get("case")) is int for row in rows),
        "Each MIC case requires an integer identity",
    )
    require(
        sorted(row["case"] for row in rows) == list(range(5)),
        "Missing, duplicate, or unreviewed MIC case",
    )
    success = {"success": True, "denied": False, "os": None}
    denied = {"success": False, "denied": True, "os": 5}
    for row in rows:
        case = row["case"]
        expected = {
            "schema": "hepta.windows-mic-counterexample.v1",
            "case": case,
            "observation": {
                "outside_read": True,
                "outside": [denied, denied, success, success]
                if case in (0, 3)
                else [denied] * 4,
                "inside": [[denied if case == 1 else success] * 3] * 2,
                "protected_git": denied if case == 1 else success,
                "outside_postconditions": case not in (0, 3),
                "inside_postconditions": case != 1,
                "protected_git_retained": case == 1,
            },
            "original_oracle": False,
            "original_isolation_hypothesis": "FAIL",
            "production_admission": {
                "legacy_error": "LegacyWindowsSandboxIsolationUnavailable",
                "elevated_error": "ElevatedWindowsSandboxIsolationUnavailable",
                "fixture_unchanged": True,
                "child_marker_absent": True,
                "provisioning_absent": True,
            },
            "permission_qualification": False,
        }
        require(
            canonical(row) == canonical(expected),
            f"MIC case {case} differs from the complete counterexample and public refusal",
        )
    return {
        "schema": "hepta.windows-mic-regression.v1",
        "regression_status": "PASS",
        "original_isolation_hypothesis": "FAIL",
        "original_oracle_failed_cases": list(range(5)),
        "public_capture_refusals": 10,
        "permission_qualification": False,
        "cases": sorted(rows, key=lambda row: row["case"]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdout", type=Path, required=True)
    parser.add_argument("--stderr", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    args = parser.parse_args()
    require(
        re.fullmatch(r"[0-9a-f]{40}", args.expected_head) is not None,
        "Exact candidate commit required",
    )
    inputs = {}
    texts = []
    for path in (args.stdout, args.stderr):
        with path.open("rb") as stream:
            raw = stream.read(4 * 1024 * 1024 + 1)
        require(len(raw) <= 4 * 1024 * 1024, "Unexpected native transcript size")
        inputs[path.name] = hashlib.sha256(raw).hexdigest()
        texts.append(raw.decode("utf-8"))
    report = validate_transcript("\n".join(texts))
    report.update({"head": args.expected_head, "input_sha256": inputs})
    args.output.write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
