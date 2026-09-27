#!/usr/bin/env python3
"""Recompute receipt completion claims from independently bound source metadata.

This is a consistency guard, not a workflow attestation verifier. Its caller
must authenticate the expected workflow/run/attempt and source independently.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import hepta_artifact_qualification as qualification

COMPLETION_KEYS = {
    "nativeCandidateQualified", "requirementTraceabilityComplete", "moduleComplete"
}


def git_blob(data: bytes) -> str:
    """Git object identity, not the digest of the JSON after reserialization."""
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def verify_bound_bundle(out: Path, expected: dict, mapping_bytes: bytes) -> dict:
    """Validate original bytes and recompute all traceability/completion fields.

    `mapping_bytes` must be the exact independently expected Git blob; never
    reconstruct it from the receipt's own claims. Unmapped obligations remain
    visible and cannot be upgraded by rehashing the qualification receipt.
    """
    if len(mapping_bytes) > qualification.MAX_REPORT:
        raise ValueError("implementation map exceeds the bounded input profile")
    if git_blob(mapping_bytes) != expected.get("sourceObjects", {}).get(qualification.MAP):
        raise ValueError("implementation map is not the independently bound Git object")
    mapping = qualification.strict_json(mapping_bytes)
    if not isinstance(mapping, dict) or mapping.get("module") != "learning.artifacts":
        raise ValueError("invalid artifact implementation map")
    operations = mapping.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ValueError("missing mapped obligations")
    names = set()
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("malformed operation")
        name = operation.get("operation")
        tests = operation.get("tests")
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("missing or duplicate mapped obligation")
        names.add(name)
        if not isinstance(tests, list) or any(not isinstance(test, str) or not test for test in tests):
            raise ValueError("invalid declared test identities")
        if len(tests) != len(set(tests)):
            raise ValueError("duplicate declared test identity")
        path, blob = operation.get("sourcePath"), operation.get("sourceBlob")
        if not isinstance(path, str) or not isinstance(blob, str):
            raise ValueError("missing operation source binding")
        if expected["sourceObjects"].get(path) != blob:
            raise ValueError("operation does not match independently bound source")
    # Retained artifact directories are host-controlled. Reject symlinks,
    # special files and oversize streams before the legacy digest pass.
    for name in qualification.GATES:
        total = 0
        for suffix in ("stdout", "stderr"):
            metadata = (out / f"{name}.{suffix}").lstat()
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("retained gate output is not a regular file")
            total += metadata.st_size
        if total > qualification.MAX_OUTPUT:
            raise ValueError("retained gate output exceeds the combined stream budget")
    for name in ("qualification.json", "qualification.sha256", "junit.xml"):
        metadata = (out / name).lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > qualification.MAX_REPORT:
            raise ValueError("invalid bounded receipt/report file")
    receipt = qualification.verify_bundle(out, expected)
    actual_trace = qualification.traceability(mapping, receipt["execution"])
    if receipt.get("traceability") != actual_trace:
        raise ValueError("receipt traceability differs from independently bound obligations")
    complete = bool(actual_trace) and all(
        row["mappingStatus"] == "declared_tests_executed" for row in actual_trace
    )
    completion = receipt.get("completion")
    if not isinstance(completion, dict) or set(completion) != COMPLETION_KEYS:
        raise ValueError("unknown or incomplete completion projection")
    wanted = {
        "nativeCandidateQualified": True,
        "requirementTraceabilityComplete": complete,
        "moduleComplete": False,
    }
    if any(completion[key] is not value for key, value in wanted.items()):
        raise ValueError("completion projection does not match recomputed evidence")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--lane", choices=("exact-head", "synthetic-merge"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        # Resolve identity from the checkout and CI context, never from the bundle.
        expected = qualification.source_binding(root, args.source, args.base, args.lane)
        expected["runner"] = {key: os.environ.get(key) for key in qualification.RUNNER_KEYS}
        mapping = subprocess.check_output(
            ["git", "show", f"HEAD:{qualification.MAP}"], cwd=root
        )
        receipt = verify_bound_bundle(args.out.resolve(), expected, mapping)
        print(json.dumps({"receiptConsistent": True, "completion": receipt["completion"]}))
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(json.dumps({"receiptConsistent": False, "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
