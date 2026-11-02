"""Lossless bounded Git blobs with complete byte hashes and safe cold restore."""
import argparse
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pack(source, destination):
    source, destination = Path(source), Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    inventory = []
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for path in sorted(source.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            raw = path.read_bytes()
            rel = path.relative_to(source).as_posix()
            info = tarfile.TarInfo(rel)
            info.size, info.mode, info.mtime = len(raw), 0o644, 0
            archive.addfile(info, io.BytesIO(raw))
            inventory.append(dict(path=rel, bytes=len(raw), sha256=sha(raw)))
    raw = gzip.compress(stream.getvalue(), compresslevel=6, mtime=0)
    parts = []
    for i, offset in enumerate(range(0, len(raw), 300000)):
        chunk = raw[offset:offset + 300000]
        name = f"part{i:04d}.b64"
        encoded = base64.b64encode(chunk) + b"\n"
        (destination / name).write_bytes(encoded)
        parts.append(dict(path=name, decoded_bytes=len(chunk), decoded_sha256=sha(chunk),
                          stored_sha256=sha(encoded)))
    manifest = dict(schema="digital-feedback-archive-v1", files=inventory, parts=parts,
                    archive_bytes=len(raw), archive_sha256=sha(raw))
    (destination / "MANIFEST.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return manifest


def restore(archive, destination):
    archive, destination = Path(archive), Path(destination)
    manifest = json.loads((archive / "MANIFEST.json").read_text())
    chunks = []
    for part in manifest["parts"]:
        encoded = (archive / part["path"]).read_bytes()
        if sha(encoded) != part["stored_sha256"]:
            raise ValueError("stored archive part changed")
        raw = base64.b64decode(encoded.strip(), validate=True)
        if sha(raw) != part["decoded_sha256"] or len(raw) != part["decoded_bytes"]:
            raise ValueError("decoded archive part changed")
        chunks.append(raw)
    raw = b"".join(chunks)
    if sha(raw) != manifest["archive_sha256"] or len(raw) != manifest["archive_bytes"]:
        raise ValueError("archive changed")
    expected = {f["path"]: f for f in manifest["files"]}
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(raw)), mode="r:") as stream:
        members = stream.getmembers()
        if len(members) != len(expected) or {m.name for m in members} != set(expected):
            raise ValueError("archive inventory changed or contains duplicates")
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not member.isfile():
                raise ValueError("unsafe archive member")
            target = destination.joinpath(*path.parts)
            if target.exists():
                raise FileExistsError(target)
        destination.mkdir(parents=True, exist_ok=True)
        for member in members:
            data = stream.extractfile(member).read()
            record = expected[member.name]
            if sha(data) != record["sha256"] or len(data) != record["bytes"]:
                raise ValueError("file content mismatch")
            target = destination / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                output.write(data)
    return dict(files_verified=len(expected), archive_sha256=manifest["archive_sha256"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("pack", "restore"))
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = pack(args.source, args.destination) if args.stage == "pack" else restore(args.source, args.destination)
    print(json.dumps({k: v for k, v in result.items() if k not in ("files", "parts")}, sort_keys=True))
