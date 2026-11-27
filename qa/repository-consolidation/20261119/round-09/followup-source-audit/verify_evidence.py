#!/usr/bin/env python3
"""Verify every evidence part and original member without extracting files."""

import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def verify(root):
    index = json.loads((root / "evidence-index.json").read_text())
    if index["schema"] != "hepta.consolidation.evidence-parts.v1":
        raise ValueError("Unsupported evidence schema")
    if not 0 < index["tar_bytes"] <= 64 * 1024 * 1024:
        raise ValueError("Archive exceeds the verification bound")
    raw = bytearray()
    for number, part in enumerate(index["parts"]):
        expected_name = f"evidence-{number:04d}.tar.part.gz"
        if part["path"] != expected_name or part["offset"] != len(raw):
            raise ValueError("Part order or offset changed")
        if not 0 < part["raw_bytes"] <= 400_000:
            raise ValueError("Part expansion exceeds its bound")
        path = root / expected_name
        if path.is_symlink():
            raise ValueError("Evidence part is a symbolic link")
        compressed = path.read_bytes()
        if len(compressed) != part["bytes"] or len(compressed) > 512_000:
            raise ValueError("Part size changed")
        if sha256(compressed) != part["sha256"]:
            raise ValueError("Part compressed digest changed")
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
            chunk = stream.read(part["raw_bytes"] + 1)
            if len(chunk) != part["raw_bytes"] or stream.read(1):
                raise ValueError("Part expansion size changed")
        if sha256(chunk) != part["raw_sha256"]:
            raise ValueError("Part raw digest changed")
        raw.extend(chunk)
        if len(raw) > index["tar_bytes"]:
            raise ValueError("Archive exceeds the declared size")
    if len(raw) != index["tar_bytes"] or sha256(raw) != index["tar_sha256"]:
        raise ValueError("Reconstructed archive identity changed")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        entries = archive.getmembers()
        names = [entry.name for entry in entries]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate archive member")
        if len(entries) != index["evidence_files"] + 1 or not all(
            entry.isfile() for entry in entries
        ):
            raise ValueError("Unexpected archive member type or count")
        manifest_bytes = archive.extractfile("EVIDENCE_MANIFEST.json").read()
        if sha256(manifest_bytes) != index["member_manifest_sha256"]:
            raise ValueError("Member manifest identity changed")
        manifest = json.loads(manifest_bytes)
        expected = {row["path"]: row for row in manifest["files"]}
        if len(expected) != index["evidence_files"] or set(names) != {
            *expected, "EVIDENCE_MANIFEST.json"
        }:
            raise ValueError("Member manifest coverage changed")
        for name, row in expected.items():
            if name.startswith("/") or ".." in name.split("/"):
                raise ValueError("Unsafe member path")
            if not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
                raise ValueError("Invalid member digest")
            entry = archive.getmember(name)
            if entry.size != row["bytes"]:
                raise ValueError(f"Member size changed: {name}")
            if sha256(archive.extractfile(entry).read()) != row["sha256"]:
                raise ValueError(f"Member digest changed: {name}")
    return {
        "status": "PASS_EVIDENCE_BYTE_CUSTODY",
        "source_commit": index["source_commit"],
        "evidence_files": len(expected),
        "parts": len(index["parts"]),
        "tar_bytes": len(raw),
        "tar_sha256": index["tar_sha256"],
        "execution_qualification": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(Path(__file__).resolve().parent), indent=2, sort_keys=True))
