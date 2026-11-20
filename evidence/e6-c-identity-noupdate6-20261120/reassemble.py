#!/usr/bin/env python3
"""Verify and reassemble the immutable original evidence; never run its contents."""
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parent
spec = json.loads((ROOT / "archive-parts.json").read_text())
chunks = []
for row in spec["parts"]:
    name = row["name"]
    if Path(name).name != name:
        raise ValueError("Part path must be a local filename")
    data = (ROOT / name).read_bytes()
    if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
        raise ValueError("Part length or digest differs: " + name)
    chunks.append(data)
archive = b"".join(chunks)
if len(archive) != spec["archive_bytes"] or hashlib.sha256(archive).hexdigest() != spec["archive_sha256"]:
    raise ValueError("Reassembled archive differs")
manifest_bytes = (ROOT / "MANIFEST.json").read_bytes()
manifest = json.loads(manifest_bytes)
with tarfile.open(fileobj=io.BytesIO(archive), mode="r:xz") as stream:
    names = stream.getnames()
    expected = {row["path"] for row in manifest["files"]} | {"MANIFEST.json"}
    if len(names) != len(expected) or set(names) != expected:
        raise ValueError("Archive membership differs")
    if stream.extractfile("MANIFEST.json").read() != manifest_bytes:
        raise ValueError("Embedded manifest differs")
    for row in manifest["files"]:
        entry = stream.getmember(row["path"])
        if not entry.isfile():
            raise ValueError("Unexpected non-regular entry")
        data = stream.extractfile(entry).read()
        if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError("Original length or digest differs: " + row["path"])
name = spec["archive_name"]
if Path(name).name != name:
    raise ValueError("Archive name must be a local filename")
out = ROOT / name
if out.exists():
    if out.read_bytes() != archive:
        raise ValueError("Refusing to replace a different archive")
else:
    with out.open("xb") as handle:
        handle.write(archive)
print(json.dumps({"verified_original_files": len(manifest["files"]), "archive_bytes": len(archive), "archive_sha256": spec["archive_sha256"], "executed_or_extracted": False}))
