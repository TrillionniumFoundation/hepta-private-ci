"""Deterministic text transport for complete fitted/result evidence bytes."""

import argparse
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

HERE = Path(__file__).resolve().parent
RESTORE = '''"""Restore verified evidence bytes beneath an explicitly chosen directory."""
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
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("preconfirm", "confirm"), required=True)
    phase = parser.parse_args().phase
    prepared = HERE / "run_01"
    if phase == "preconfirm":
        assert not (prepared / "confirmation_01").exists()
        paths = [p for p in prepared.iterdir() if p.is_file()]
        paths += list(HERE.glob("run_01_prepare.*"))
    else:
        paths = [p for p in (prepared / "confirmation_01").iterdir() if p.is_file()]
        paths += list(HERE.glob("run_01_confirm.*"))
    files, archive = [], io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w", format=tarfile.USTAR_FORMAT) as package:
        for path in sorted(paths):
            raw = path.read_bytes()
            relative = path.relative_to(HERE).as_posix()
            files.append(dict(path=relative, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
            info = tarfile.TarInfo(relative)
            info.size, info.mode, info.mtime = len(raw), 0o644, 0
            package.addfile(info, io.BytesIO(raw))
    compressed = gzip.compress(archive.getvalue(), compresslevel=9, mtime=0)
    target = HERE / f"transport_{phase}"
    target.mkdir(exist_ok=False)
    parts = []
    for index, start in enumerate(range(0, len(compressed), 60000)):
        encoded = base64.b64encode(compressed[start:start + 60000])
        name = f"part_{index:04d}.b64"
        (target / name).write_bytes(encoded)
        parts.append(dict(path=name, bytes=len(encoded), sha256=hashlib.sha256(encoded).hexdigest()))
    manifest = dict(phase=phase, archive_sha256=hashlib.sha256(compressed).hexdigest(),
        compressed_bytes=len(compressed), logical_bytes=sum(r["bytes"] for r in files),
        files=files, parts=parts, compression="deterministic gzip/tar; timestamps/owner zero")
    (target / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (target / "RESTORE.py").write_text(RESTORE)
    print(json.dumps(dict(directory=str(target), files=len(files), parts=len(parts),
                         compressed_bytes=len(compressed), archive_sha256=manifest["archive_sha256"])))


if __name__ == "__main__":
    main()
