"""Deduplicate the immutable MEM6 raw archive without dropping file identities."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import time

ROOT = Path("/home/qq/mem6-attribution-20261110-484c/archive-v1")
def sha(raw):
    return hashlib.sha256(raw).hexdigest()

before = time.perf_counter()
original = ROOT / "mem6-run-001.tar.xz"
expected_archive = "6fe31c6685012e0e0b6ae92f35782482691d1dfcec7e4c24e9b2376fe4d8453c"
assert sha(original.read_bytes()) == expected_archive
manifest_raw = (ROOT / "MANIFEST.json").read_bytes()
manifest = json.loads(manifest_raw)
expected = {r["path"]: r for r in manifest["files"]}
archive = ROOT / "mem6-cas-001.tar.xz"
assert not archive.exists()
seen, unique, count = set(), set(), 0
with tarfile.open(original, "r:xz") as source, tarfile.open(archive, "w:xz", preset=6) as target:
    info = tarfile.TarInfo("MANIFEST.json")
    info.size, info.mode = len(manifest_raw), 0o600
    target.addfile(info, io.BytesIO(manifest_raw))
    for member in source:
        raw = source.extractfile(member).read()
        if member.name == "MEM6_RAW_MANIFEST.json":
            assert raw == manifest_raw
            continue
        pin = expected[member.name]
        digest = sha(raw)
        assert digest == pin["sha256"] and len(raw) == pin["bytes"]
        assert member.name not in seen
        seen.add(member.name)
        if digest not in unique:
            unique.add(digest)
            count += len(raw)
            info = tarfile.TarInfo("objects/" + digest)
            info.size, info.mode = len(raw), 0o600
            target.addfile(info, io.BytesIO(raw))
assert seen == set(expected)
with tarfile.open(archive, "r:xz") as source:
    restored = {}
    for member in source:
        raw = source.extractfile(member).read()
        if member.name == "MANIFEST.json":
            assert raw == manifest_raw
        else:
            digest = member.name.removeprefix("objects/")
            assert digest == sha(raw) and digest not in restored
            restored[digest] = len(raw)
    assert all(restored[p["sha256"]] == p["bytes"] for p in expected.values())
raw = archive.read_bytes()
receipt = {"schema": "hepta.mem6.content-addressed-archive.v1",
           "archive": {"path": str(archive), "bytes": len(raw), "sha256": sha(raw)},
           "raw_archive_sha256": expected_archive, "manifest_sha256": sha(manifest_raw),
           "original_file_count": len(expected), "original_bytes": manifest["total_bytes"],
           "unique_objects": len(unique), "unique_bytes": count,
           "all_file_bytes_reconstructible": True, "full_owner_cold_recovery": False,
           "wall_seconds": time.perf_counter() - before}
(ROOT / "CAS_RECEIPT.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
print(json.dumps(receipt), flush=True)
