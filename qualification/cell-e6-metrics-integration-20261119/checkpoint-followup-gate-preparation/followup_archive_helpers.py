"""Create and fully reopen immutable, bounded evidence archives."""

import hashlib
import io
import json
import lzma
from pathlib import Path
import tarfile


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pack(output, entries):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    entries = sorted(entries, key=lambda pair: pair[0])
    assert len({name for name, _ in entries}) == len(entries)
    rows = []
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, path in entries:
            assert not name.startswith("/") and ".." not in Path(name).parts
            raw = Path(path).read_bytes()
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            member.mode = 0o644
            member.mtime = 0
            archive.addfile(member, io.BytesIO(raw))
            rows.append({"path": name, "bytes": len(raw), "sha256": sha(raw), "mode": "100644"})
    compressed = lzma.compress(buffer.getvalue(), preset=6)
    parts = []
    for index, start in enumerate(range(0, len(compressed), 393216)):
        raw = compressed[start:start + 393216]
        name = f"originals.tar.xz.part-{index:03d}"
        (output / name).write_bytes(raw)
        parts.append({"path": name, "bytes": len(raw), "sha256": sha(raw)})
    with tarfile.open(fileobj=io.BytesIO(lzma.decompress(compressed)), mode="r:") as archive:
        members = archive.getmembers()
        assert [m.name for m in members] == [r["path"] for r in rows]
        for member, row in zip(members, rows):
            raw = archive.extractfile(member).read()
            assert member.isfile() and member.mode == 0o644
            assert len(raw) == row["bytes"] and sha(raw) == row["sha256"]
    manifest = {"schema": "hepta.exact-raw-evidence-archive.v1", "archive_sha256": sha(compressed), "archive_bytes": len(compressed), "members": rows, "member_count": len(rows), "original_bytes": sum(r["bytes"] for r in rows), "parts": parts, "all_members_reopened_and_verified": True, "new_model_training_native_calls": 0}
    (output / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
