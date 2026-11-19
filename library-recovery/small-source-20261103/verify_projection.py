#!/usr/bin/env python3
"""Verify archived bytes only; never import or execute the preserved sources."""

import hashlib
import json
from pathlib import Path
import sys

if sys.flags.optimize:
    raise SystemExit("optimized verification refused")

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root.parents[1] / "scripts"))
from verify_source_custody_volumes import verify_collection

collection = "library-recovery/small-source-20261103"
verified_source = verify_collection(root.parents[1], collection)
manifest = json.loads(verified_source[collection + "/SOURCE_MANIFEST.json"])
seen = set()
for row in manifest["sources"] + manifest["notices"]:
    path = root / row["relative_path"]
    assert path.resolve().is_relative_to(root.resolve())
    data = verified_source[collection + "/" + row["relative_path"]]
    assert len(data) == row["bytes"], row["relative_path"]
    assert hashlib.sha256(data).hexdigest() == row["sha256"], row["relative_path"]
    assert (
        hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        == row["git_blob_sha"]
    ), row["relative_path"]
    assert row["git_blob_sha"] not in seen, row["relative_path"]
    seen.add(row["git_blob_sha"])
assert len(manifest["sources"]) == manifest["source_count"]
print(
    json.dumps(
        {
            "source_count": len(manifest["sources"]),
            "notice_count": len(manifest["notices"]),
            "all_bytes_match_manifest": True,
            "archived_source_executed": False,
            "research_or_runtime_qualification": False,
        }
    )
)
