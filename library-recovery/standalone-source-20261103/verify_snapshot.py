#!/usr/bin/env python3
"""Verify original Library bytes; no runtime experiments are claimed."""

from pathlib import Path
import hashlib, json, sys

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root.parents[1] / "scripts"))
from verify_source_custody_volumes import verify_collection

collection = "library-recovery/standalone-source-20261103"
verified_source = verify_collection(root.parents[1], collection)
manifest = json.loads(verified_source[collection + "/MANIFEST.json"])
errors = []
for row in manifest["files"]:
    p = root / "files" / row["name"]
    try:
        buf = verified_source[collection + "/files/" + row["name"]]
    except OSError as exc:
        errors.append(f"{row['name']}: {exc}")
        continue
    sha = hashlib.sha256(buf).hexdigest()
    git_sha = hashlib.sha1(
        b"blob " + str(len(buf)).encode("ascii") + b"\x00" + buf
    ).hexdigest()
    if (len(buf), sha, git_sha) != (row["bytes"], row["sha256"], row["git_blob_sha"]):
        errors.append(row["name"] + ": hash or size mismatch")
if errors:
    print("\n".join("FAIL: " + e for e in errors))
    sys.exit(1)
print(
    "PASS: %d source files retained with SHA-256 and Git blob identity"
    % len(manifest["files"])
)
