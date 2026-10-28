"""Mechanical lossless evidence packaging; never trains or scores a study.

The original study/ and engineering/ layouts and file bytes are preserved.
INDEX.json binds ordered archive and compressed-manifest parts; the latter
contains every original file path, byte length and SHA256. Existing output
directories, symlinks, special files, duplicate names and unsafe paths reject.
"""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile
import tempfile

LIMIT = 480000
SCHEMA = "hepta.continuous-boundary.evidence-bundle.v1"


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def document(data):
    return json.loads(data, object_pairs_hook=unique_object)


def safe_name(name, *, part=False):
    path = PurePosixPath(name)
    if (
        not isinstance(name, str)
        or not name
        or str(path) != name
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in name
        or ":" in name
        or any(ord(c) < 32 for c in name)
    ):
        raise ValueError(f"Unsafe path: {name!r}")
    if part and len(path.parts) != 1:
        raise ValueError("Part name must be a basename")
    if not part and (len(path.parts) < 1 or path.parts[0] not in {"study", "engineering"}):
        raise ValueError("Member is outside the registered layout")
    return path


def regular(path):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    if path.is_symlink():
        raise ValueError(f"Symlink rejected: {path}")
    stream = os.fdopen(os.open(path, flags), "rb")
    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
        stream.close()
        raise ValueError(f"Nonregular input: {path}")
    return stream


class HashedReader:
    def __init__(self, stream):
        self.stream, self.hash, self.size = stream, hashlib.sha256(), 0

    def read(self, size):
        value = self.stream.read(size)
        self.hash.update(value)
        self.size += len(value)
        return value


def split_file(path, output, prefix):
    whole, parts, size = hashlib.sha256(), [], 0
    with regular(path) as stream:
        while chunk := stream.read(LIMIT):
            name = f"{prefix}-{len(parts):05d}.part"
            with (output / name).open("xb") as target:
                target.write(chunk)
            parts.append({"order": len(parts), "name": name, "bytes": len(chunk), "sha256": hashlib.sha256(chunk).hexdigest()})
            whole.update(chunk)
            size += len(chunk)
    return {"bytes": size, "sha256": whole.hexdigest(), "parts": parts}


def join_parts(bundle, description, destination, maximum):
    if not 0 < description["bytes"] <= maximum or not description["parts"]:
        raise ValueError("Invalid declared archive size")
    whole, size, seen = hashlib.sha256(), 0, set()
    with destination.open("xb") as target:
        for order, part in enumerate(description["parts"]):
            safe_name(part["name"], part=True)
            if part["order"] != order or part["name"] in seen:
                raise ValueError("Duplicate or reordered part")
            seen.add(part["name"])
            with regular(bundle / part["name"]) as source:
                chunk = source.read(LIMIT + 1)
            if not 0 < len(chunk) <= LIMIT or len(chunk) != part["bytes"] or hashlib.sha256(chunk).hexdigest() != part["sha256"]:
                raise ValueError("Part byte/hash mismatch")
            whole.update(chunk)
            size += len(chunk)
            if size > description["bytes"]:
                raise ValueError("Part bytes exceed declared total")
            target.write(chunk)
    if size != description["bytes"] or whole.hexdigest() != description["sha256"]:
        raise ValueError("Complete archive byte/hash mismatch")


def pack(study, engineering, output):
    roots = {"study": study, "engineering": engineering}
    files, directories = [], []
    for label, root in roots.items():
        if root.is_symlink() or not root.is_dir():
            raise ValueError(f"Expected a real source directory: {root}")
        if output.is_relative_to(root.resolve()) or root.resolve().is_relative_to(output):
            raise ValueError("Input and output directories overlap")
        directories.append(label)
        for path in sorted(root.rglob("*")):
            name = f"{label}/{path.relative_to(root).as_posix()}"
            safe_name(name)
            if path.is_symlink():
                raise ValueError(f"Symlink rejected: {path}")
            if path.is_dir():
                directories.append(name)
            elif path.is_file():
                files.append((name, path))
            else:
                raise ValueError(f"Special input rejected: {path}")
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    records = []
    with tempfile.TemporaryDirectory(prefix=".pack-", dir=output) as temporary:
        archive = Path(temporary) / "evidence.tar.gz"
        with archive.open("xb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as zipped:
            with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as tar:
                for name in sorted(directories):
                    info = tarfile.TarInfo(name)
                    info.type, info.mode, info.mtime = tarfile.DIRTYPE, 0o700, 0
                    tar.addfile(info)
                for name, path in sorted(files):
                    with regular(path) as stream:
                        before = os.fstat(stream.fileno())
                        info = tarfile.TarInfo(name)
                        info.size, info.mode, info.mtime = before.st_size, 0o600 | (before.st_mode & 0o100), 0
                        reader = HashedReader(stream)
                        tar.addfile(info, reader)
                        after = os.fstat(stream.fileno())
                        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
                        if (
                            reader.size != before.st_size
                            or stream.read(1)
                            or any(getattr(before, key) != getattr(after, key) for key in fields)
                        ):
                            raise ValueError(f"Source changed while packing: {name}")
                        records.append({"path": name, "bytes": reader.size, "sha256": reader.hash.hexdigest(), "mode": info.mode})
        manifest = encoded({"files": records, "directories": sorted(directories)})
        manifest_path = Path(temporary) / "files.json.gz"
        manifest_path.write_bytes(gzip.compress(manifest, mtime=0))
        index = {
            "schema": SCHEMA,
            "scope": "mechanical-evidence-only",
            "archive": split_file(archive, output, "archive"),
            "file_manifest": split_file(manifest_path, output, "manifest"),
            "manifest_uncompressed_bytes": len(manifest),
            "file_count": len(records),
            "directory_count": len(directories),
            "original_bytes": sum(row["bytes"] for row in records),
        }
        data = encoded(index) + b"\n"
        if len(data) > LIMIT:
            raise ValueError("Index exceeds publication size limit")
        with (output / "INDEX.json").open("xb") as target:
            target.write(data)
    return index


def unpack(bundle, output, maximum):
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    with regular(bundle / "INDEX.json") as stream:
        raw_index = stream.read(LIMIT + 1)
    if len(raw_index) > LIMIT:
        raise ValueError("Oversized index")
    index = document(raw_index)
    if index["schema"] != SCHEMA or index["scope"] != "mechanical-evidence-only":
        raise ValueError("Unknown bundle schema/scope")
    if (
        not 0 <= index["original_bytes"] <= maximum
        or not 0 <= index["file_count"] <= 100000
        or not 0 <= index["directory_count"] <= 100000
    ):
        raise ValueError("Unpacked size/file limit exceeded")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".verify-", dir=output.parent) as temporary:
        temporary = Path(temporary)
        join_parts(bundle, index["file_manifest"], temporary / "manifest.gz", 64 << 20)
        with gzip.open(temporary / "manifest.gz", "rb") as source:
            data = source.read((64 << 20) + 1)
        if len(data) > 64 << 20 or len(data) != index["manifest_uncompressed_bytes"]:
            raise ValueError("Manifest expansion limit or size mismatch")
        manifest = document(data)
        files, directories = {}, set()
        for name in manifest["directories"]:
            safe_name(name)
            if name in directories:
                raise ValueError("Duplicate manifest directory")
            directories.add(name)
        for row in manifest["files"]:
            safe_name(row["path"])
            if (
                row["path"] in files
                or row["path"] in directories
                or type(row["bytes"]) is not int
                or row["bytes"] < 0
                or row["mode"] not in (0o600, 0o700)
            ):
                raise ValueError("Invalid or duplicate manifest file")
            files[row["path"]] = row
        if (
            len(files) != index["file_count"]
            or len(directories) != index["directory_count"]
            or sum(row["bytes"] for row in files.values()) != index["original_bytes"]
        ):
            raise ValueError("Manifest/index totals mismatch")
        archive = temporary / "archive.tar.gz"
        join_parts(bundle, index["archive"], archive, maximum)
        output.mkdir(mode=0o700)
        seen = set()
        with tarfile.open(archive, mode="r:gz") as tar:
            for member in tar:
                safe_name(member.name)
                if member.name in seen:
                    raise ValueError("Duplicate archive member")
                seen.add(member.name)
                target = output / member.name
                if member.type == tarfile.DIRTYPE and member.name in directories:
                    target.mkdir(parents=True, exist_ok=True, mode=0o700)
                    continue
                row = files.get(member.name)
                if (
                    member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE)
                    or row is None
                    or member.size != row["bytes"]
                    or member.mode != row["mode"]
                ):
                    raise ValueError("Unexpected member, link, type, size or mode")
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                hasher, size = hashlib.sha256(), 0
                with tar.extractfile(member) as source, target.open("xb") as destination:
                    while chunk := source.read(1 << 20):
                        hasher.update(chunk)
                        size += len(chunk)
                        destination.write(chunk)
                if size != row["bytes"] or hasher.hexdigest() != row["sha256"]:
                    raise ValueError("Restored file byte/hash mismatch")
                target.chmod(row["mode"])
        if seen != set(files) | directories:
            raise ValueError("Missing or extra archive members")
    return {"verified": True, "files": len(files), "original_bytes": index["original_bytes"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    writer = commands.add_parser("pack")
    writer.add_argument("--study-dir", type=Path, required=True)
    writer.add_argument("--engineering-dir", type=Path, required=True)
    reader = commands.add_parser("unpack")
    reader.add_argument("--bundle-dir", type=Path, required=True)
    reader.add_argument("--max-unpacked-bytes", type=int, default=4 << 30)
    for command in (writer, reader):
        command.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "pack":
        index = pack(args.study_dir.absolute(), args.engineering_dir.absolute(), args.output_dir.resolve())
        result = {
            "files": index["file_count"],
            "archive_sha256": index["archive"]["sha256"],
            "archive_parts": len(index["archive"]["parts"]),
            "index": str(args.output_dir / "INDEX.json"),
        }
    else:
        result = unpack(args.bundle_dir.absolute(), args.output_dir.resolve(), args.max_unpacked_bytes)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
