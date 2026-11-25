"""Verify transport archives against every listed member and retained original."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tarfile

from audit_hcsn_artifacts import PROTOCOL_SHA, check, digest, read, require

INDEX_SHA = "37736a1b054eb4dc5e6160dbdc5b02a01de8bd44a5ba57635eb1c97c3ecc74c4"


def run(root, output):
    require(not output.exists(), "receipt already exists")
    index_path = root / "evidence_archives/ARCHIVE_INDEX.json"
    check(index_path, INDEX_SHA)
    index = read(index_path)
    require(index["protocol_sha256"] == PROTOCOL_SHA, "archive protocol identity")
    require(len(index["bundles"]) == index["archive_count"] == 190, "archive count")
    members, total, expanded, largest = {}, 0, 0, 0
    for bundle in index["bundles"]:
        path = root / bundle["path"]
        require(path.stat().st_size == bundle["bytes"] <= 512000, "archive blob-size policy")
        check(path, bundle["sha256"])
        total += bundle["bytes"]; largest = max(largest, bundle["bytes"])
        expected = {row["path"]: row for row in bundle["members"]}
        require(len(expected) == len(bundle["members"]), "duplicate index member")
        with tarfile.open(path, "r:xz") as archive:
            rows = archive.getmembers()
            require(len(rows) == len(expected) and {r.name for r in rows} == set(expected),
                    "archive/member inventory mismatch")
            for row in rows:
                want = expected[row.name]
                require(row.isfile() and row.size == want["bytes"] < 128 * 1024**2,
                        "only bounded original file members are allowed")
                relative = Path(row.name)
                require(not relative.is_absolute() and ".." not in relative.parts, "member path")
                with archive.extractfile(row) as stream:
                    actual = hashlib.file_digest(stream, "sha256").hexdigest()
                require(actual == want["sha256"], "expanded member SHA")
                check(root / relative, actual)
                require(row.name not in members, "duplicate member across transport archives")
                members[row.name] = actual; expanded += row.size
    require(total == index["bytes"], "total archived bytes")
    receipt = {"schema": "hepta.adoption-closure.independent-hcsn-v2-archive-audit.v1",
               "observed_utc": datetime.now(timezone.utc).isoformat(), "status": "ALL_ARCHIVES_AND_MEMBERS_MATCH",
               "index_sha256": INDEX_SHA, "protocol_sha256": PROTOCOL_SHA, "archive_count": 190,
               "member_count": len(members), "archive_bytes": total, "expanded_bytes": expanded,
               "maximum_archive_bytes": largest, "blob_limit_bytes": 512000,
               "member_map_sha256": hashlib.sha256(json.dumps(members, sort_keys=True,
                   separators=(",", ":")).encode()).hexdigest(),
               "audit_source_sha256": digest(__file__),
               "audit_common_source_sha256": digest(Path(__file__).with_name("audit_hcsn_artifacts.py")),
               "all_retained_originals_matched": True, "archive_extracted_to_filesystem": False,
               "model_calls": 0, "training_updates": 0, "test_regenerated": False}
    with output.open("x") as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.source_root, args.output)
