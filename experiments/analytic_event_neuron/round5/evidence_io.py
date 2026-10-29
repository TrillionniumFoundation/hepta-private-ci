"""Versioned UTF-8 envelopes for new binary evidence on text-only Git transport.

This utility never recovers or recreates missing historical execution evidence.
Each envelope identifies its decoded archive and every original member byte.
"""

import argparse
import base64
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import lzma
from pathlib import Path, PurePosixPath
import tarfile


SCHEMA = "hepta.analytic-event.evidence-envelope.v1"
XZ_SCHEMA = "hepta.analytic-event.evidence-envelope.v2"
CHUNK_BYTES = 196608


def digest(value):
    return hashlib.sha256(value).hexdigest()


def relative_name(value):
    name = PurePosixPath(value)
    if (name.is_absolute() or not name.parts or any(p in ("", ".", "..") for p in name.parts)
            or str(name) != value or "\\" in value):
        raise ValueError("A normalized relative member path is required")
    return name


def pack(source, destination, source_label, compression="gzip"):
    """Capture an immutable directory; reject links and refuse overwrites."""
    source, destination = Path(source), Path(destination)
    if compression not in ("gzip", "xz"):
        raise ValueError("Declared gzip or xz compression required")
    if not source.is_dir() or source.is_symlink():
        raise ValueError("Source must be a real directory")
    source, destination = source.resolve(), destination.resolve()
    if destination == source or source in destination.parents:
        raise ValueError("Envelope output must not be inside its input")
    files = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError("Evidence symlinks are not archived")
        if path.is_file():
            name = path.relative_to(source).as_posix()
            relative_name(name)
            files.append((name, path.read_bytes()))
        elif not path.is_dir():
            raise ValueError("Only ordinary files and directories can be archived")
    if not files:
        raise ValueError("Empty evidence is not an archive")
    encoded = io.BytesIO()
    compressor = (gzip.GzipFile(fileobj=encoded, mode="wb", mtime=0) if compression == "gzip"
                  else lzma.LZMAFile(encoded, mode="wb", preset=6))
    with compressor as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for name, payload in files:
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime = len(payload), 0o644, 0
                archive.addfile(info, io.BytesIO(payload))
    blob = encoded.getvalue()
    destination.mkdir(parents=True, exist_ok=False)
    chunks = []
    for offset in range(0, len(blob), CHUNK_BYTES):
        raw = blob[offset:offset + CHUNK_BYTES]
        content = base64.b64encode(raw)
        suffix = "gz" if compression == "gzip" else "xz"
        name = f"archive.tar.{suffix}.b64.part{len(chunks):04d}"
        (destination / name).write_bytes(content)
        chunks.append({"path": name, "encoded_bytes": len(content), "encoded_sha256": digest(content),
                       "decoded_bytes": len(raw), "decoded_sha256": digest(raw)})
    manifest = {"schema": SCHEMA if compression == "gzip" else XZ_SCHEMA,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "source_label": source_label, "encoding": "independent standard base64 chunks without whitespace",
                "archive_format": compression + "+POSIX-tar; regular relative files only", "archive_bytes": len(blob),
                "archive_sha256": digest(blob), "chunks": chunks,
                "members": [{"path": name, "bytes": len(data), "sha256": digest(data)} for name, data in files],
                "historical_missing_evidence_reconstructed": False}
    (destination / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def restore(envelope, destination):
    """Verify all encoded, archive and member bytes before writing new files."""
    envelope, destination = Path(envelope), Path(destination)
    manifest = json.loads((envelope / "MANIFEST.json").read_text())
    if manifest["schema"] not in (SCHEMA, XZ_SCHEMA):
        raise ValueError("Unsupported evidence envelope version")
    compression = "gzip" if manifest["schema"] == SCHEMA else "xz"
    if manifest["archive_format"] != compression + "+POSIX-tar; regular relative files only":
        raise ValueError("Envelope schema and compression declaration disagree")
    expected = {"MANIFEST.json"} | {item["path"] for item in manifest["chunks"]}
    if {p.name for p in envelope.iterdir()} != expected or len(expected) != len(manifest["chunks"]) + 1:
        raise ValueError("Envelope file inventory differs from the manifest")
    chunks = []
    for item in manifest["chunks"]:
        name = relative_name(item["path"])
        if len(name.parts) != 1:
            raise ValueError("Chunks must be direct envelope children")
        content = (envelope / str(name)).read_bytes()
        if len(content) != item["encoded_bytes"] or digest(content) != item["encoded_sha256"]:
            raise ValueError("Encoded chunk differs from manifest")
        raw = base64.b64decode(content, validate=True)
        if len(raw) != item["decoded_bytes"] or digest(raw) != item["decoded_sha256"]:
            raise ValueError("Decoded chunk differs from manifest")
        chunks.append(raw)
    blob = b"".join(chunks)
    if len(blob) != manifest["archive_bytes"] or digest(blob) != manifest["archive_sha256"]:
        raise ValueError("Reassembled archive differs from manifest")
    expected_members = {item["path"]: item for item in manifest["members"]}
    if len(expected_members) != len(manifest["members"]):
        raise ValueError("Duplicate member in manifest")
    payloads = {}
    mode = "r:gz" if compression == "gzip" else "r:xz"
    with tarfile.open(fileobj=io.BytesIO(blob), mode=mode) as archive:
        for member in archive:
            relative_name(member.name)
            if not member.isfile() or member.name not in expected_members or member.name in payloads:
                raise ValueError("Unexpected, duplicate or non-regular archive member")
            item = expected_members[member.name]
            if member.size != item["bytes"]:
                raise ValueError("Archive member size mismatch")
            data = archive.extractfile(member).read(member.size + 1)
            if len(data) != member.size or digest(data) != item["sha256"]:
                raise ValueError("Archive member bytes differ from manifest")
            payloads[member.name] = data
    if set(payloads) != set(expected_members):
        raise ValueError("Incomplete archive member inventory")
    destination.mkdir(parents=True, exist_ok=False)
    for name, payload in payloads.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(payload)
    return {"schema": "hepta.analytic-event.evidence-restoration.v1",
            "manifest_sha256": digest((envelope / "MANIFEST.json").read_bytes()),
            "archive_sha256": digest(blob), "member_count": len(payloads),
            "original_bytes_verified": sum(map(len, payloads.values())), "all_bytes_match": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("pack", "restore"))
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--source-label")
    parser.add_argument("--compression", choices=("gzip", "xz"), default="gzip")
    args = parser.parse_args()
    if args.phase == "pack":
        if not args.source_label:
            parser.error("pack requires an explicit source label")
        result = pack(args.source, args.destination, args.source_label, args.compression)
        print(json.dumps({"archive_sha256": result["archive_sha256"], "archive_bytes": result["archive_bytes"],
                          "chunks": len(result["chunks"]), "members": len(result["members"])}))
    else:
        print(json.dumps(restore(args.source, args.destination)))


if __name__ == "__main__":
    main()
