"""Deterministic, hash-verified multipart evidence archives; no pickle required."""

import argparse
import hashlib
import json
import lzma
from pathlib import Path, PurePosixPath
import tarfile
import tempfile


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def safe_name(name):
    value = PurePosixPath(name)
    if value.is_absolute() or ".." in value.parts or not value.parts or "\\" in name:
        raise ValueError(f"Unsafe archive member: {name}")
    return value


def pack(root, destination, name, part_bytes=1048576):
    root, destination = Path(root).resolve(), Path(destination)
    if part_bytes < 4096 or not root.is_dir() or not name.replace("_", "").isalnum():
        raise ValueError("Require existing root, simple bundle name, and part size >=4096")
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / f"{name}.json"
    if manifest_path.exists() or list(destination.glob(f"{name}.tar.xz.part*")):
        raise FileExistsError("Archive bundle already exists; preserve previous evidence")
    files = sorted(path for path in root.rglob("*")
                   if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
    if any(path.is_symlink() for path in files):
        raise ValueError("Symlinks are not accepted as evidence members")
    members = [{"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
                "sha256": sha256(path)} for path in files]
    parts, whole = [], hashlib.sha256()
    with tempfile.TemporaryFile() as temporary:
        with lzma.LZMAFile(temporary, "w", preset=6) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as archive:
                for path, record in zip(files, members, strict=True):
                    info = tarfile.TarInfo(record["path"])
                    info.size, info.mode, info.mtime = record["bytes"], 0o644, 0
                    with path.open("rb") as source:
                        archive.addfile(info, source)
        temporary.seek(0)
        index = 0
        while block := temporary.read(part_bytes):
            part_path = destination / f"{name}.tar.xz.part{index:04d}"
            part_path.write_bytes(block)
            whole.update(block)
            parts.append({"path": part_path.name, "bytes": len(block),
                          "sha256": hashlib.sha256(block).hexdigest(),
                          "git_blob_sha1": hashlib.sha1(
                              b"blob " + str(len(block)).encode() + b"\0" + block).hexdigest()})
            index += 1
    if any(sha256(path) != record["sha256"] for path, record in zip(files, members, strict=True)):
        raise ValueError("An input changed while packing; do not publish this incomplete bundle")
    manifest = {"schema": "hcsn-evidence-bundle.v1", "name": name,
                "format": "deterministic POSIX tar, xz, concatenated parts in declared order",
                "archive_sha256": whole.hexdigest(), "parts": parts, "members": members,
                "uncompressed_file_bytes": sum(row["bytes"] for row in members),
                "compressed_bytes": sum(row["bytes"] for row in parts)}
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def restore(manifest_path, destination):
    manifest_path, destination = Path(manifest_path), Path(destination).resolve()
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != "hcsn-evidence-bundle.v1":
        raise ValueError("Unknown archive contract")
    expected = {record["path"]: record for record in manifest["members"]}
    if len(expected) != len(manifest["members"]):
        raise ValueError("Duplicate declared members")
    for name in expected:
        safe_name(name)
    with tempfile.TemporaryFile() as temporary:
        whole = hashlib.sha256()
        for part in manifest["parts"]:
            name = safe_name(part["path"])
            if len(name.parts) != 1:
                raise ValueError("Archive parts must be adjacent to their manifest")
            path = manifest_path.parent / part["path"]
            if path.stat().st_size != part["bytes"] or sha256(path) != part["sha256"]:
                raise ValueError(f"Corrupt archive part: {path.name}")
            with path.open("rb") as source:
                for block in iter(lambda: source.read(1 << 20), b""):
                    whole.update(block)
                    temporary.write(block)
        if whole.hexdigest() != manifest["archive_sha256"]:
            raise ValueError("Whole archive hash mismatch")
        temporary.seek(0)
        seen = set()
        with tarfile.open(fileobj=temporary, mode="r:xz") as archive:
            for member in archive:
                name = safe_name(member.name)
                if not member.isfile() or member.name not in expected or member.name in seen:
                    raise ValueError("Unexpected, duplicate, or non-regular archive member")
                record = expected[member.name]
                if member.size != record["bytes"]:
                    raise ValueError("Member size mismatch")
                target = destination.joinpath(*name.parts)
                if not target.resolve().is_relative_to(destination):
                    raise ValueError("Destination path escapes through an existing symlink")
                if target.exists() and (not target.is_file() or sha256(target) != record["sha256"]):
                    raise FileExistsError(f"Refuse to overwrite different content: {target}")
                source = archive.extractfile(member)
                value = hashlib.sha256()
                with tempfile.TemporaryFile() as checked:
                    for block in iter(lambda: source.read(1 << 20), b""):
                        value.update(block)
                        checked.write(block)
                    if value.hexdigest() != record["sha256"]:
                        raise ValueError(f"Member checksum mismatch: {member.name}")
                    if not target.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        checked.seek(0)
                        with target.open("xb") as output:
                            for block in iter(lambda: checked.read(1 << 20), b""):
                                output.write(block)
                seen.add(member.name)
        if seen != set(expected):
            raise ValueError("Archive is missing declared members")
    return {"restored_or_already_identical": len(seen), "archive_sha256": manifest["archive_sha256"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("pack")
    create.add_argument("--root", type=Path, required=True)
    create.add_argument("--destination", type=Path, required=True)
    create.add_argument("--name", required=True)
    unpack = commands.add_parser("restore")
    unpack.add_argument("--manifest", type=Path, required=True)
    unpack.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "pack":
        result = pack(args.root, args.destination, args.name)
        print(json.dumps({key: result[key] for key in ("name", "compressed_bytes", "uncompressed_file_bytes")}, indent=2))
    else:
        print(json.dumps(restore(args.manifest, args.destination), indent=2))


if __name__ == "__main__":
    main()
