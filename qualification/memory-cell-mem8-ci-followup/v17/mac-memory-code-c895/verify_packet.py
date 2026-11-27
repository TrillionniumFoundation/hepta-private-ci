#!/usr/bin/env python3
"""Offline byte verification only: no subprocess, network, native or model execution."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--full-raw", type=Path)
    parser.add_argument("--full-tree", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = json.loads((root / "FILE_MANIFEST.json").read_text())
    expected = {row["path"]: row for row in manifest["members"]}
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    assert actual == set(expected) | {"FILE_MANIFEST.json"}, "unexpected/missing member"
    for name, row in expected.items():
        relative = PurePosixPath(name)
        assert not relative.is_absolute() and ".." not in relative.parts
        path = root / name
        assert not path.is_symlink() and path.resolve().is_relative_to(root)
        assert identity(path.read_bytes()) == {key: row[key] for key in identity(b"")}
    index = json.loads((root / "SOURCE_INDEX.json").read_text())
    assert index["source_head"] == "c89540598693697577cda8cba31cb07f6ce65317"
    assert index["source_tree"] == "5a7c897a33e4eef48ea8f4bf52eaf48ea7c866ae"
    assert len(index["files"]) == 14
    for row in index["files"]:
        assert identity((root / "source" / row["path"]).read_bytes()) == {
            key: row[key] for key in identity(b"")}
        assert row["mode"] == "100644"
    report = json.loads((root / "READ_ONLY_REVIEW.json").read_text())
    assert report["status"] == "CAUSE_NOT_UNIQUELY_DETERMINED_NO_SOURCE_PATCH_NO_NATIVE_RUN"
    assert report["original"]["run_id"] == 43048568477 and report["original"]["job_id"] == 130619380498
    assert report["execution_scope"]["new_native_commands"] == report["execution_scope"]["new_model_requests"] == 0
    refs = json.loads((root / "FULL_ORIGINAL_REFERENCES.json").read_text())
    slices = json.loads((root / "RAW_SLICE_INDEX.json").read_text())
    assert slices["original"] == refs["raw"]
    for row in slices["slices"]:
        raw = (root / row["path"]).read_bytes()
        assert identity(raw) == {key: row[key] for key in identity(b"")}
        assert row["byte_end_exclusive"] - row["byte_start"] == len(raw)
        assert len(raw.splitlines()) == row["line_end_inclusive"] - row["line_start_one_based"] + 1
    memory = (root / "raw-excerpts/memory-target-incomplete.raw.log").read_text()
    assert "product_v2_reports_peer_truncation_before_aggregation ... FAILED" in memory
    assert "Test timed out" in memory and "test result:" not in memory and "panicked at" not in memory
    rows = re.findall(r"\btest ([^\r\n]+?) \.\.\. (ok|FAILED|ignored)(?:[ ,\r\n]|$)", memory)
    counts = {status: sum(value == status for _, value in rows) for status in ("ok", "FAILED", "ignored")}
    assert counts == {"ok": 364, "FAILED": 1, "ignored": 9}, counts
    code = (root / "raw-excerpts/code-mode-target.raw.log").read_text()
    assert "driver_tests.rs:762:6" in code
    assert "concurrent large results should queue behind the blocked bulk writer: Elapsed(())" in code
    assert "69 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 25.41s" in code
    full_raw_verified = False
    if args.full_raw:
        raw = args.full_raw.read_bytes()
        assert identity(raw) == {key: refs["raw"][key] for key in identity(b"")}
        for row in slices["slices"]:
            assert raw[row["byte_start"]:row["byte_end_exclusive"]] == (root / row["path"]).read_bytes()
        full_raw_verified = True
    full_tree_verified = False
    if args.full_tree:
        raw = args.full_tree.read_bytes()
        assert identity(raw) == {key: refs["full_source_tree_inventory"][key] for key in identity(b"")}
        entries = {}
        for value in raw.split(b"\0"):
            if value:
                header, path = value.split(b"\t", 1)
                mode, kind, sha = header.decode().split()
                entries[path.decode()] = (mode, kind, sha)
        assert len(entries) == 14053
        for row in index["files"]:
            assert entries[row["path"]] == (row["mode"], "blob", row["git_blob"])
        full_tree_verified = True
    print(json.dumps({"status": "PASS_READONLY_EVIDENCE_BYTES", "regular_members": len(actual),
                      "source_files": 14, "raw_slices": len(slices["slices"]),
                      "memory_visible_display_rows": counts, "code_mode_actual_summary": {"passed": 69, "failed": 1},
                      "full_original_raw_rechecked": full_raw_verified,
                      "full_tree_inventory_rechecked": full_tree_verified,
                      "root_cause_status": report["status"], "new_native_or_model_execution": 0}, sort_keys=True))

if __name__ == "__main__":
    main()
