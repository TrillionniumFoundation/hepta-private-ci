"""Verify each independent gzip piece and every original TAR member."""

from pathlib import Path
import gzip
import hashlib
import io
import json
import tarfile

root = Path(__file__).resolve().parent
manifest = json.loads((root / "manifest.json").read_bytes())
sha = lambda data: hashlib.sha256(data).hexdigest()
pieces = []
offset = 0
for row in manifest["parts"]:
    assert Path(row["path"]).name == row["path"]
    packed = (root / row["path"]).read_bytes()
    assert len(packed) == row["gzip_bytes"] <= 400000
    assert sha(packed) == row["gzip_sha256"]
    assert row["raw_bytes"] <= 384000 and row["offset"] == offset
    with gzip.GzipFile(fileobj=io.BytesIO(packed)) as stream:
        raw = stream.read(row["raw_bytes"] + 1)
        assert len(raw) == row["raw_bytes"] and stream.read(1) == b""
    assert sha(raw) == row["raw_sha256"]
    pieces.append(raw)
    offset += len(raw)
raw_tar = b"".join(pieces)
assert len(raw_tar) == manifest["raw_tar_bytes"]
assert sha(raw_tar) == manifest["raw_tar_sha256"]
with tarfile.open(fileobj=io.BytesIO(raw_tar), mode="r:") as archive:
    members = archive.getmembers()
    assert len(members) == len(manifest["members"])
    names = set()
    for member, expected in zip(members, manifest["members"]):
        assert member.isfile() and member.name == expected["path"]
        assert not member.name.startswith("/") and ".." not in Path(member.name).parts
        assert member.name not in names
        names.add(member.name)
        data = archive.extractfile(member).read()
        assert len(data) == expected["bytes"] and sha(data) == expected["sha256"]
print(
    json.dumps(
        {
            "status": "PASS",
            "members": len(members),
            "parts": len(pieces),
            "raw_tar_sha256": sha(raw_tar),
        },
        sort_keys=True,
    )
)
