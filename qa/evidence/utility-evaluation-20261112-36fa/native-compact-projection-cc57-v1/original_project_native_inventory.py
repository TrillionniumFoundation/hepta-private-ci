#!/usr/bin/env python3
"""Pure projection of a pinned expected full inventory into original native rows.

This reads JSON evidence only. It never reads a source checkout, runs Git, calls
H, imports gate code, or executes a native/qualification driver. All output is a
projection; actual alignment and original native snapshot remain mandatory.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path, PurePosixPath

FULL_PIN = {
    "bytes": 5611184,
    "sha256": "df891018254756c61007f91dd7cd9f794a550dc6ad33f389849eb44eaffc9b3e",
    "git_blob": "663373f936c2ff130aec96ad34654cc9811773c2",
}
SOURCE = {
    "head": "246d8cb614770252ee42029a5c014f2a4904176a",
    "tree": "d5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087",
    "status": "",
}
COUNT = 15188
ORIGINAL_DRIVERS = {
    "b92": {
        "bytes": 14986,
        "sha256": "3c318e8d028afd0039325a531215c4add411dc5a1a0ec5016fd3448dfbf2d231",
        "git_blob": "b92ddded4fce78aeb076d022471c62bf81ce2e4f",
    },
    "reviewed_native_wrapper": {
        "bytes": 13360,
        "sha256": "fc5b2c43fdf01288396b03369647a5c886108ec3e8eec3da2e2fe5afadb21d5f",
        "git_blob": "de3e9dc5e7eb30f47929f9e1ba9f460035a94fae",
    },
}

def pin(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }

def require(value, explanation):
    if not value:
        raise ValueError(explanation)

def project(raw):
    require(pin(raw) == FULL_PIN, "exact expected full-inventory bytes differ")
    full = json.loads(raw)
    require(full["schema"] == "hepta.utility.desktop-source-gates.v1.inventory",
            "original full inventory schema differs")
    require(full["source"] == SOURCE, "exact expected source differs")
    require(full["tracked_entries"] == full["filesystem_entries"] == COUNT,
            "expected complete source membership differs")
    entries = full["files"]
    require(len(entries) == COUNT, "complete expected rows required")
    paths = [row["path"] for row in entries]
    require(len(set(paths)) == COUNT, "unique source paths required")
    # This fixed source contains only ASCII paths. Raw Git byte sorting and
    # os.fsdecode therefore have the same result independently of locale.
    for path in paths:
        require(isinstance(path, str) and path.isascii() and "\0" not in path,
                "this pinned projection admits only the observed ASCII paths")
        p = PurePosixPath(path)
        require(not p.is_absolute() and ".." not in p.parts
                and str(p) == path and ".git" not in p.parts,
                "canonical source-relative path required")
    rows = []
    for entry in sorted(entries, key=lambda row: row["path"].encode("ascii")):
        require(entry["matches_index"] is True and entry["stable"] is True,
                "missing, unstable, extra, or index-mismatched row")
        require(entry["working_blob"] == entry["index_blob"],
                "working/index object differs")
        require(type(entry["bytes"]) is int and entry["bytes"] >= 0,
                "invalid original content length")
        require(len(entry["sha256"]) == 64 and len(entry["working_blob"]) == 40,
                "content identities required")
        permissions = entry["permissions"]
        require(type(permissions) is int and 0 <= permissions <= 0o7777,
                "original physical permission bits required")
        if entry["kind"] == "symlink":
            mode = "120000"
        elif entry["kind"] == "file":
            mode = "100755" if permissions & 0o111 else "100644"
        else:
            raise ValueError("unsupported/missing physical kind")
        require(mode == entry["index_mode"], "physical Git mode differs")
        rows.append({
            "path": entry["path"],
            "mode": mode,
            "bytes": entry["bytes"],
            "sha256": entry["sha256"],
            "blob": entry["working_blob"],
        })
    # Exact uncompressed native serializer: array only, sorted keys, compact
    # separators, default ensure_ascii=True, UTF-8, and no final LF.
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    summary = {
        "commit": SOURCE["head"], "tree": SOURCE["tree"], "status": "",
        "files": len(rows), "inventory_sha256": hashlib.sha256(encoded).hexdigest(),
    }
    report = {
        "format": "hepta-final-native-compact-inventory-projection-v1",
        "status": "PROJECTION_ONLY_NOT_ACTUAL_NATIVE_OBSERVATION",
        "full_expected_input": FULL_PIN,
        "source_expected": SOURCE,
        "native_compact_expected": pin(encoded),
        "native_snapshot_expected_value": summary,
        "source_membership": {
            "rows": len(rows), "all_indexed": True, "all_stable": True,
            "all_working_blobs_equal_index": True, "untracked_or_ignored_file_rows": 0,
            "ascii_paths": len(paths),
            "kinds": dict(sorted(collections.Counter(e["kind"] for e in entries).items())),
            "git_modes": dict(sorted(collections.Counter(r["mode"] for r in rows).items())),
        },
        "original_snapshot_algorithm_pins": ORIGINAL_DRIVERS,
        "algorithm": {
            "membership": "Original git ls-files plus nonignored untracked paths; in this pinned expected clean full inventory every physical file is indexed, so the union is exactly its 15188 paths.",
            "sort": "Sort unique raw Git path bytes. All current paths are ASCII; source-relative path strings retain those bytes.",
            "mode": "Symlink => 120000; regular file => 100755 if any physical execute bit is set, otherwise 100644.",
            "content": "Use the pinned expected full row's bytes, SHA256 and working_blob. No source file was read or newly hashed by this projection.",
            "row_fields": ["path", "mode", "bytes", "sha256", "blob"],
            "serializer": "json.dumps(rows, sort_keys=True, separators=(',', ':')).encode(); default ensure_ascii=True; no terminal LF.",
            "gzip": "No gzip identity is predicted. Original b92 gzip headers can vary; the required inventory hash covers the uncompressed JSON array.",
        },
        "scope_difference": {
            "full_5118": "Object with source HEAD/tree/status, counts, and every physical source file plus every index entry. Rows retain permissions, kind, index mode/blob, working blob, stability and index-match flags; ignored physical outputs are visible. Serializer ends with LF.",
            "native_b92_and_wrapper": "Array of tracked and nonignored-untracked rows only. It omits ignored outputs and full permission/stability/index fields. Source HEAD/tree/status/count live in a separate summary. Array serializer has no LF.",
            "not_substitutable": "Full SHA256 df891018... and projected native SHA256 describe different byte formats and scope. Neither may be relabeled as the other.",
        },
        "requirements_before_use": [
            "Root must receive the actual normal canonical-alignment terminal and complete audits.",
            "Its actual full inventory identity must match this exact 5611184-byte input pin; a predicted tree alone is insufficient.",
            "The reviewed native wrapper must still run its original source-before snapshot from the actual checkout and compare its own exact HEAD/tree/status/count/hash against the bound expected values.",
            "The unchanged b92 focused/all drivers must still take and retain their own actual original snapshots and require before/after equality.",
            "Source gates must first create and freeze their original shared/no-hardlinks independent clone. That clone's permissions/full-inventory hash can differ from the writable origin; do not substitute the clone hash.",
            "Generated ignored JUnit/output files after native execution must remain explicit in the separate final full-physical observation.",
        ],
        "actual_native_snapshot_observed": False,
        "actual_alignment_observed_by_this_script": False,
        "native_or_H_or_git_commands": 0,
        "gate_or_test_driver_main_calls": 0,
        "source_files_read_or_written": 0,
    }
    return encoded, summary, report

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-inventory", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    compact, summary, report = project(args.full_inventory.read_bytes())
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "NATIVE_COMPACT_INVENTORY.projected.json").write_bytes(compact)
    for name, value in [
        ("NATIVE_SNAPSHOT.projected.json", summary),
        ("PROJECTION_REPORT.json", report),
    ]:
        with (args.output_dir / name).open("x") as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")
    print(json.dumps({
        "status": report["status"],
        "projected_compact": pin(compact),
        "files": summary["files"],
        "report": pin((args.output_dir / "PROJECTION_REPORT.json").read_bytes()),
    }, sort_keys=True))

