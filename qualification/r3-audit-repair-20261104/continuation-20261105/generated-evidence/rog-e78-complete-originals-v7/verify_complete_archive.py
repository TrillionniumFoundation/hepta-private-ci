#!/usr/bin/env python3
"""Verify immutable native transport and publish complete originals atomically."""
from pathlib import Path
import base64
import gzip
import hashlib
import io
import json
import os
import struct
import tarfile

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT.parent / "project-nonpass-priority-v1/export-manifest.json"
FINAL = ROOT / "decoded-verified-v1"
STAGING = ROOT / "decoded-verified-v1.staging"


def identity(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def verify(data, expected):
    got = identity(data)
    for key, value in got.items():
        assert expected[key] == value, (key, expected[key], value)
    return got


def main():
    assert not FINAL.exists() and not STAGING.exists()
    manifest_bytes = MANIFEST.read_bytes()
    assert len(manifest_bytes) == 53278
    assert hashlib.sha256(manifest_bytes).hexdigest() == "8a30fd1939e75a997ae3d8cb305673ef2ed6f233952855dd498937839aa84b29"
    manifest = json.loads(manifest_bytes)
    compressed_parts = []
    offset = 0
    part_receipts = []
    for index, part in enumerate(manifest["parts"]):
        assert part["index"] == index and part["compressed_offset"] == offset
        path = ROOT / "transport" / Path(part["path"]).name
        encoded = path.read_bytes()
        verify(encoded, part)
        assert encoded.endswith(b"\n") and encoded.count(b"\n") == 1
        decoded = base64.b64decode(encoded[:-1], validate=True)
        assert base64.b64encode(decoded) + b"\n" == encoded
        verify(decoded, part["decoded"])
        compressed_parts.append(decoded)
        part_receipts.append({"index": index, "local_path": str(path), **identity(encoded)})
        offset += len(decoded)
    assert len(part_receipts) == 70
    compressed = b"".join(compressed_parts)
    verify(compressed, manifest["archive"])
    assert struct.unpack("<I", compressed[4:8])[0] == 0
    archive_bytes = gzip.decompress(compressed)
    verify(archive_bytes, manifest["tar_identity"])
    expected = {entry["member"]: entry for entry in manifest["originals"]}
    assert len(expected) == len(manifest["originals"]) == 29
    STAGING.mkdir()
    original_receipts = []
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as archive:
        members = archive.getmembers()
        assert [m.name for m in members] == [entry["member"] for entry in manifest["originals"]]
        assert len(members) == len(set(m.name for m in members)) == 29
        for member in members:
            assert member.isfile() and Path(member.name).name == member.name
            original = archive.extractfile(member).read()
            measured = verify(original, expected[member.name])
            path = STAGING / member.name
            with path.open("xb") as stream:
                stream.write(original)
                stream.flush()
                os.fsync(stream.fileno())
            verify(path.read_bytes(), expected[member.name])
            original_receipts.append({"member": member.name, "local_path": str(FINAL / member.name), "native_path": expected[member.name]["path"], **measured})
    assert sum(row["bytes"] for row in original_receipts) == manifest["original_bytes"] == 33420419
    with (ROOT / "originals.tar.gz").open("xb") as stream:
        stream.write(compressed)
    verify((ROOT / "originals.tar.gz").read_bytes(), manifest["archive"])
    STAGING.rename(FINAL)
    for row in original_receipts:
        verify(Path(row["local_path"]).read_bytes(), row)
    receipt = {
        "schema": "strict-complete-original-archive-verification-v1",
        "manifest": {"path": str(MANIFEST), **identity(manifest_bytes)},
        "archive_complete": True,
        "strict_base64_roundtrip": True,
        "gzip_final_crc_and_size_verified": True,
        "gzip_mtime": 0,
        "tar_exact_member_sequence_and_set": True,
        "raw_original_bytes": 33420419,
        "raw_original_count": 29,
        "parts": part_receipts,
        "compressed": identity(compressed),
        "tar": identity(archive_bytes),
        "originals": original_receipts,
        "publication": "Each original was fully verified and reopened in a new staging directory; the complete directory was renamed before being announced.",
        "native_tests_rerun": False,
    }
    encoded = (json.dumps(receipt, indent=2) + "\n").encode()
    path = ROOT / "complete-verification.json"
    with path.open("xb") as stream:
        stream.write(encoded)
    print(json.dumps({"verified": True, "path": str(path), "identity": identity(encoded), "original_count": 29, "original_bytes": 33420419, "decoded_directory": str(FINAL)}))


if __name__ == "__main__":
    main()
