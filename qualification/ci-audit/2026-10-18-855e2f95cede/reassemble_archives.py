#!/usr/bin/env python3
"""Verify archive pieces and optionally reconstruct exact tar.gz files; never extract them."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

CHUNK = 1024 * 1024


def member_path(root, name):
    if not isinstance(name, str):
        raise ValueError("file path must be a string")
    part = Path(name)
    if part.is_absolute() or not part.parts or any(p in ("..", ".") for p in part.parts):
        raise ValueError(f"unsafe relative path: {name!r}")
    candidate = root / part
    if any((root / Path(*part.parts[:i])).is_symlink() for i in range(1, len(part.parts) + 1)):
        raise ValueError(f"symlink member: {name}")
    if not candidate.is_file():
        raise ValueError(f"missing archive member: {name}")
    return candidate


def verify_member(root, entry):
    path = member_path(root, entry["path"])
    size = path.stat().st_size
    if type(entry["bytes"]) is not int or size != entry["bytes"]:
        raise ValueError(f"size mismatch: {entry['path']}")
    digest = hashlib.sha256()
    git_digest = hashlib.sha1(f"blob {size}\0".encode())
    with path.open("rb") as source:
        while data := source.read(CHUNK):
            digest.update(data)
            git_digest.update(data)
    if digest.hexdigest() != entry["sha256"]:
        raise ValueError(f"SHA-256 mismatch: {entry['path']}")
    if git_digest.hexdigest() != entry["git_blob_sha"]:
        raise ValueError(f"Git blob mismatch: {entry['path']}")
    return path


def reconstruct(root, archive, output_dir, verify_only):
    name = archive["name"]
    if not isinstance(name, str) or Path(name).name != name or name in ("", ".", ".."):
        raise ValueError("archive name must be a simple filename")
    storage = archive["storage"]
    if storage["kind"] == "blob":
        entries = [storage["file"]]
    elif storage["kind"] == "parts":
        entries = storage["parts"]
        if not entries or [x["index"] for x in entries] != list(range(len(entries))):
            raise ValueError(f"missing or unordered pieces: {name}")
    else:
        raise ValueError(f"unknown archive storage: {name}")
    if type(archive["bytes"]) is not int or archive["bytes"] < 0:
        raise ValueError(f"invalid archive size: {name}")
    paths = [verify_member(root, entry) for entry in entries]
    if sum(entry["bytes"] for entry in entries) != archive["bytes"]:
        raise ValueError(f"piece size sum mismatch: {name}")
    digest = hashlib.sha256()
    git_digest = hashlib.sha1(f"blob {archive['bytes']}\0".encode())
    destination = output_dir / name
    temporary = None
    writer = None
    try:
        if not verify_only and storage["kind"] == "parts":
            if destination.is_symlink():
                raise ValueError(f"refusing symlink destination: {name}")
            if destination.exists():
                verify_member(output_dir, {
                    "path": name,
                    "bytes": archive["bytes"],
                    "sha256": archive["sha256"],
                    "git_blob_sha": archive["git_blob_sha"],
                })
            else:
                output_dir.mkdir(parents=True, exist_ok=True)
                writer = tempfile.NamedTemporaryFile(
                    prefix=f".{name}.", suffix=".tmp", dir=output_dir, delete=False
                )
                temporary = Path(writer.name)
        for path in paths:
            with path.open("rb") as source:
                while data := source.read(CHUNK):
                    digest.update(data)
                    git_digest.update(data)
                    if writer is not None:
                        writer.write(data)
        if digest.hexdigest() != archive["sha256"]:
            raise ValueError(f"whole archive SHA-256 mismatch: {name}")
        if git_digest.hexdigest() != archive["git_blob_sha"]:
            raise ValueError(f"whole archive Git blob mismatch: {name}")
        if writer is not None:
            writer.flush()
            os.fsync(writer.fileno())
            writer.close()
            writer = None
            # An existing path created during verification must not be overwritten.
            os.link(temporary, destination)
            temporary.unlink()
            temporary = None
        return {
            "archive": name,
            "status": "VERIFIED",
            "bytes": archive["bytes"],
            "parts": len(paths),
            "sha256": digest.hexdigest(),
            "git_blob_sha": git_digest.hexdigest(),
            "reconstructed": storage["kind"] == "parts" and not verify_only,
        }
    finally:
        if writer is not None:
            writer.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("ARCHIVES.json"))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    manifest = args.manifest.resolve(strict=True)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if payload.get("schema") != "hepta.audit-archives.v1":
        raise ValueError("unsupported archive manifest schema")
    root = manifest.parent
    output_dir = args.output_dir.resolve() if args.output_dir else root
    for archive in payload["archives"]:
        print(json.dumps(reconstruct(root, archive, output_dir, args.verify_only), sort_keys=True))


if __name__ == "__main__":
    main()
