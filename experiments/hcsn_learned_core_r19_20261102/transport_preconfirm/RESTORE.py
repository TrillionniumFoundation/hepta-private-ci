"""Restore verified evidence bytes beneath an explicitly chosen directory."""
import base64, gzip, hashlib, io, json, pathlib, sys, tarfile
source = pathlib.Path(__file__).resolve().parent
destination = pathlib.Path(sys.argv[1]).resolve()
manifest = json.loads((source / "MANIFEST.json").read_text())
pieces = []
for part in manifest["parts"]:
    raw = (source / part["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == part["sha256"]
    pieces.append(base64.b64decode(raw, validate=True))
archive = b"".join(pieces)
assert hashlib.sha256(archive).hexdigest() == manifest["archive_sha256"]
with tarfile.open(fileobj=io.BytesIO(gzip.decompress(archive)), mode="r:") as package:
    for entry in manifest["files"]:
        relative = pathlib.PurePosixPath(entry["path"])
        assert not relative.is_absolute() and ".." not in relative.parts
        raw = package.extractfile(entry["path"]).read()
        assert len(raw) == entry["bytes"] and hashlib.sha256(raw).hexdigest() == entry["sha256"]
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            assert target.read_bytes() == raw, str(target)
        else:
            with target.open("xb") as stream: stream.write(raw)
print(json.dumps({"verified_files": len(manifest["files"]), "destination": str(destination)}))
