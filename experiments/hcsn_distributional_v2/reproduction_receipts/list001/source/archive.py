"""Deterministic, hash-verified multipart evidence archives; no pickle required."""

import argparse
from contextlib import nullcontext
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


class _PartWriter:
    """A write-only compressed sink with at most one unfinished part in RAM."""

    def __init__(self, destination, name, part_bytes):
        self.destination = destination
        self.name = name
        self.part_bytes = part_bytes
        self.buffer = bytearray()
        self.parts = []
        self.whole = hashlib.sha256()

    def _emit(self):
        block = bytes(self.buffer)
        path = self.destination / f"{self.name}.tar.xz.part{len(self.parts):04d}"
        with path.open("xb") as output:
            output.write(block)
        self.whole.update(block)
        self.parts.append({"path": path.name, "bytes": len(block),
                           "sha256": hashlib.sha256(block).hexdigest(),
                           "git_blob_sha1": hashlib.sha1(
                               b"blob " + str(len(block)).encode() + b"\0" + block).hexdigest()})
        self.buffer.clear()

    def write(self, data):
        view = memoryview(data)
        count = len(view)
        while view:
            take = min(len(view), self.part_bytes - len(self.buffer))
            self.buffer.extend(view[:take])
            view = view[take:]
            if len(self.buffer) == self.part_bytes:
                self._emit()
        return count

    def finish(self):
        # Closing LZMA, not a part boundary, ends the one continuous XZ stream.
        if self.buffer:
            self._emit()


class _PartReader:
    """Sequential bounded reads across parts, with a second content check."""

    def __init__(self, directory, parts, expected_whole):
        self.directory = directory
        self.parts = iter(parts)
        self.expected_whole = expected_whole
        self.source = None
        self.record = None
        self.part_hash = None
        self.part_read = 0
        self.whole = hashlib.sha256()

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        if self.source is not None:
            self.source.close()

    def read(self, size):
        if size < 0:
            raise ValueError("The internal archive reader requires bounded reads")
        result = bytearray()
        while len(result) < size:
            if self.source is None:
                self.record = next(self.parts, None)
                if self.record is None:
                    break
                self.source = (self.directory / self.record["path"]).open("rb")
                self.part_hash = hashlib.sha256()
                self.part_read = 0
            block = self.source.read(size - len(result))
            if block:
                self.part_hash.update(block)
                self.whole.update(block)
                self.part_read += len(block)
                result.extend(block)
            else:
                self.source.close()
                self.source = None
                if self.part_read != self.record["bytes"] or self.part_hash.hexdigest() != self.record["sha256"]:
                    raise ValueError(f"Archive part changed while reading: {self.record['path']}")
        return bytes(result)

    def verify_end(self):
        # Tar can stop at its zero blocks before the compressed stream ends.
        # Drain the remaining compressed bytes to recheck every complete part.
        while self.read(1 << 20):
            pass
        if self.whole.hexdigest() != self.expected_whole:
            raise ValueError("Whole archive changed while reading")


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
    sink = _PartWriter(destination, name, part_bytes)
    with lzma.LZMAFile(sink, "w", preset=6) as compressed:
        with tarfile.open(fileobj=compressed, mode="w|") as archive:
            for path, record in zip(files, members, strict=True):
                info = tarfile.TarInfo(record["path"])
                info.size, info.mode, info.mtime = record["bytes"], 0o644, 0
                with path.open("rb") as source:
                    archive.addfile(info, source)
    sink.finish()
    parts, whole = sink.parts, sink.whole
    if any(sha256(path) != record["sha256"] for path, record in zip(files, members, strict=True)):
        raise ValueError("An input changed while packing; do not publish this incomplete bundle")
    manifest = {"schema": "hcsn-evidence-bundle.v1", "name": name,
                "format": "deterministic POSIX tar, xz, concatenated parts in declared order",
                "archive_sha256": whole.hexdigest(), "parts": parts, "members": members,
                "uncompressed_file_bytes": sum(row["bytes"] for row in members),
                "compressed_bytes": sum(row["bytes"] for row in parts)}
    with manifest_path.open("x") as output:
        output.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
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
    whole = hashlib.sha256()
    for part in manifest["parts"]:
        name = safe_name(part["path"])
        if len(name.parts) != 1:
            raise ValueError("Archive parts must be adjacent to their manifest")
        path = manifest_path.parent / part["path"]
        if path.stat().st_size != part["bytes"]:
            raise ValueError(f"Corrupt archive part: {path.name}")
        part_hash = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1 << 20), b""):
                part_hash.update(block)
                whole.update(block)
        if part_hash.hexdigest() != part["sha256"]:
            raise ValueError(f"Corrupt archive part: {path.name}")
    if whole.hexdigest() != manifest["archive_sha256"]:
        raise ValueError("Whole archive hash mismatch")
    with _PartReader(manifest_path.parent, manifest["parts"], manifest["archive_sha256"]) as stream:
        seen = set()
        with tarfile.open(fileobj=stream, mode="r|xz") as archive:
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
                existing = target.exists()
                if existing and (not target.is_file() or sha256(target) != record["sha256"]):
                    raise FileExistsError(f"Refuse to overwrite different content: {target}")
                source = archive.extractfile(member)
                value = hashlib.sha256()
                # Existing identical files need no disk copy. New members still
                # finish checksum validation before any final-path write.
                with nullcontext(None) if existing else tempfile.TemporaryFile() as checked:
                    for block in iter(lambda: source.read(1 << 20), b""):
                        value.update(block)
                        if checked is not None:
                            checked.write(block)
                    if value.hexdigest() != record["sha256"]:
                        raise ValueError(f"Member checksum mismatch: {member.name}")
                    if not existing:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        checked.seek(0)
                        with target.open("xb") as output:
                            for block in iter(lambda: checked.read(1 << 20), b""):
                                output.write(block)
                seen.add(member.name)
        if seen != set(expected):
            raise ValueError("Archive is missing declared members")
        stream.verify_end()
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
