#!/usr/bin/env python3
"""Verify the local evidence bytes against INDEX.json without running tests."""

import gzip
import hashlib
import json
from pathlib import Path
import sys
import zlib


def digest(data):
    return hashlib.sha256(data).hexdigest()


def verify(root):
    index_path = root / "INDEX.json"
    index = json.loads(index_path.read_text())
    expected = {}
    failures = []
    decoded_count = 0
    stored_bytes = 0
    for entry in index["artifacts"]:
        name = entry["path"]
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or name in expected:
            failures.append({"path": name, "reason": "invalid or duplicate path"})
            continue
        expected[name] = entry
        path = root / relative
        if path.is_symlink() or not path.is_file():
            failures.append({"path": name, "reason": "missing regular file"})
            continue
        if not path.resolve().is_relative_to(root.resolve()):
            failures.append({"path": name, "reason": "path leaves evidence root"})
            continue
        data = path.read_bytes()
        stored_bytes += len(data)
        if len(data) != entry["bytes"] or digest(data) != entry["sha256"]:
            failures.append({"path": name, "reason": "stored bytes differ"})
        if "decompressed_sha256" in entry:
            try:
                decoded = gzip.decompress(data)
            except (OSError, EOFError, zlib.error) as error:
                failures.append({"path": name, "reason": str(error)})
                continue
            decoded_count += 1
            if (
                len(decoded) != entry["decompressed_bytes"]
                or digest(decoded) != entry["decompressed_sha256"]
            ):
                failures.append({"path": name, "reason": "decoded bytes differ"})

    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and path != index_path
        and "__pycache__" not in path.parts
    }
    for name in sorted(actual - expected.keys()):
        failures.append({"path": name, "reason": "unindexed file"})
    result = {
        "status": "FAIL" if failures else "PASS_LOCAL_ARTIFACT_INTEGRITY",
        "indexed_files": len(expected),
        "decoded_gzip_files": decoded_count,
        "stored_bytes": stored_bytes,
        "failures": failures,
        "scope": (
            "Local byte integrity and inventory completeness only. "
            "No test rerun, provenance authentication, model evaluation, "
            "or transfer of intermediate test results to another source tree."
        ),
    }
    return result


if __name__ == "__main__":
    evidence_root = Path(__file__).resolve().parent
    result = verify(evidence_root)
    print(json.dumps(result, indent=2))
    sys.exit(bool(result["failures"]))
