"""Preserve every frozen MEM6 run output and verify its archive member bytes."""

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tarfile
import time


ROOT = Path("/home/qq/mem6-attribution-20261110-484c")
OUTPUT = ROOT / "archive-v1"
EXCLUDED_TOP = {"archive-v1", "source-8cf848ba", "tmp"}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    OUTPUT.mkdir(exist_ok=False)
    before = time.perf_counter()
    files = []
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if relative.parts[0] in EXCLUDED_TOP:
            continue
        if path.is_symlink():
            raise ValueError("unexpected symlink: " + str(relative))
        if path.is_file():
            if path.stat().st_nlink != 1:
                raise ValueError("unexpected hard link: " + str(relative))
            raw = path.read_bytes()
            files.append({"path": str(relative), "bytes": len(raw), "sha256": digest(raw)})
    manifest = {"schema": "hepta.mem6.raw-archive.v1", "files": files,
                "file_count": len(files), "total_bytes": sum(f["bytes"] for f in files),
                "source_commit": "8cf848babdd897e9f38642d5faf3ba0f72a1303c",
                "source_capsule_included": "mem6-source-8cf848ba.zip",
                "excluded_top_level": sorted(EXCLUDED_TOP),
                "external_runtime_inputs_included": False,
                "full_owner_cold_recovery": False,
                "independent_trust_domain": False,
                "created_at": datetime.now(timezone.utc).isoformat()}
    manifest_raw = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    (OUTPUT / "MANIFEST.json").write_bytes(manifest_raw)
    archive = OUTPUT / "mem6-run-001.tar.xz"
    with tarfile.open(archive, "w:xz", preset=6) as bundle:
        for row in files:
            raw = (ROOT / row["path"]).read_bytes()
            if len(raw) != row["bytes"] or digest(raw) != row["sha256"]:
                raise ValueError("file changed during archival: " + row["path"])
            info = tarfile.TarInfo(row["path"])
            info.size, info.mode, info.mtime = len(raw), 0o600, 0
            bundle.addfile(info, io.BytesIO(raw))
        info = tarfile.TarInfo("MEM6_RAW_MANIFEST.json")
        info.size, info.mode, info.mtime = len(manifest_raw), 0o600, 0
        bundle.addfile(info, io.BytesIO(manifest_raw))
    expected = {row["path"]: row for row in files}
    seen = set()
    with tarfile.open(archive, "r:xz") as bundle:
        for member in bundle:
            if not member.isfile() or member.name in seen:
                raise ValueError("unexpected archive member")
            seen.add(member.name)
            raw = bundle.extractfile(member).read()
            if member.name == "MEM6_RAW_MANIFEST.json":
                assert raw == manifest_raw
            else:
                row = expected[member.name]
                assert len(raw) == row["bytes"] and digest(raw) == row["sha256"]
    assert seen == set(expected) | {"MEM6_RAW_MANIFEST.json"}
    archive_raw = archive.read_bytes()
    receipt = {"schema": "hepta.mem6.raw-archive-verification.v1",
               "archive": {"path": str(archive), "bytes": len(archive_raw),
                           "sha256": digest(archive_raw)},
               "manifest": {"bytes": len(manifest_raw), "sha256": digest(manifest_raw)},
               "verified_file_count": len(files), "verified_raw_bytes": manifest["total_bytes"],
               "archive_members_verified": True,
               "wall_seconds": time.perf_counter() - before,
               "full_owner_cold_recovery": False,
               "scientific_acceptance": "HOLD", "production_adoption": False}
    (OUTPUT / "ARCHIVE_RECEIPT.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
