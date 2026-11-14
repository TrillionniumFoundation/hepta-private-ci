#!/usr/bin/env python3
"""Verify original Library snapshot bytes; no training or runtime inference."""

import hashlib, json, sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root.parents[1] / "scripts"))
from verify_source_custody_volumes import verify_collection

collection = "library-recovery/additional-source-20261103"
verified_source = verify_collection(root.parents[1], collection)
manifest = json.loads(verified_source[collection + "/MANIFEST.json"])
errors = []
for entry in manifest["files"]:
    try:
        b = verified_source[collection + "/files/" + entry["name"]]
    except OSError as exc:
        errors.append(str(exc))
        continue
    if (
        len(b),
        hashlib.sha256(b).hexdigest(),
        hashlib.sha1(b"blob " + str(len(b)).encode() + b"\x00" + b).hexdigest(),
    ) != (entry["bytes"], entry["sha256"], entry["git_blob_sha"]):
        errors.append(entry["name"])
if errors:
    print("FAIL:", *errors)
    sys.exit(1)
print("PASS: %d preserved source-file identities" % len(manifest["files"]))
