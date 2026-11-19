#!/usr/bin/env python3
"""Verify archived bytes only; never import or execute the recovered sources."""

import hashlib
import json
import sys
from pathlib import Path, PurePosixPath

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root.parents[1] / "scripts"))
from verify_source_custody_volumes import verify_collection

collection = "library-recovery/priority-source-20261103"
verified_source = verify_collection(root.parents[1], collection)
manifest = json.loads(verified_source[collection + "/SOURCE_MANIFEST.json"])
for item in manifest["sources"] + manifest["licenses"]:
    relative = PurePosixPath(item["stored_path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise SystemExit("unsafe stored path")
    path = root.joinpath(*relative.parts)
    if path.is_symlink():
        raise SystemExit("unexpected symlink")
    data = verified_source[collection + "/" + item["stored_path"]]
    actual_blob = hashlib.sha1(
        b"blob " + str(len(data)).encode() + b"\0" + data
    ).hexdigest()
    if (
        len(data) != item["bytes"]
        or hashlib.sha256(data).hexdigest() != item["sha256"]
        or actual_blob != item["git_blob_sha"]
    ):
        raise SystemExit("byte mismatch: " + item["stored_path"])
print(
    "Verified",
    len(manifest["sources"]),
    "source objects and",
    len(manifest["licenses"]),
    "license objects; archived source execution: false",
)
