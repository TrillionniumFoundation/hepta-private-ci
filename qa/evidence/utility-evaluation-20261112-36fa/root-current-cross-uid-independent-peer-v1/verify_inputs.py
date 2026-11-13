#!/usr/bin/env python3
"""Verify immutable review inputs only; no candidate imports or execution."""
import argparse
import hashlib
import json
from pathlib import Path


def identity(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--materialized-inputs", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.root / "SOURCE_INPUTS.json").read_text())
    review = json.loads((args.root / "REVIEW.json").read_text())
    assert len(manifest["rows"]) == 30
    checked = []
    for row in manifest["rows"]:
        path = (args.materialized_inputs / row["git_blob"]) if args.materialized_inputs else Path(row["local_path"])
        actual = identity(path.read_bytes())
        assert all(actual[key] == row[key] for key in actual), (row["path"], actual)
        checked.append({"path": row["path"], **actual})
    sdk = json.loads((args.root / "ADDITIONAL_SOURCE_GETS.original.json").read_text())
    assert len(sdk["rows"]) == 11
    sdk_checked = []
    for row in sdk["rows"]:
        data = row["original"]["structuredContent"]["content"].encode("utf-8")
        actual = identity(data)
        assert all(actual[key] == row[key] for key in actual), (row["name"], actual)
        sdk_checked.append({"name": row["name"], **actual})
    by_sha = {row["git_blob"]: row for row in checked}
    for stage in review["original_chain"]:
        for cited in stage["sources"]:
            assert by_sha[cited["git_blob"]]["path"] == cited["path"]
    print(json.dumps({
        "format": "hepta-root-current-peer-input-byte-check-v1",
        "status": "INPUT_BYTES_MATCH",
        "source_objects": len(checked),
        "complete_GET_results": len(sdk_checked),
        "checked_sources": checked,
        "checked_GETs": sdk_checked,
        "semantic_review_is_separate": True,
        "H_Rust_QA_gate_candidate_execution": False,
    }, indent=2) + "\n", end="")


if __name__ == "__main__":
    main()
