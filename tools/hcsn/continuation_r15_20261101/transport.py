"""Transport frozen ZIP bytes in small, independently valid gzip containers."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import zipfile

RAW_CHUNK_BYTES = 450_000
STRICT_BLOB_LIMIT = 500_000
SCHEMA = "hcsn-r15-lossless-transport-v1"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def safe_path(root, name):
    """Reject traversal, alternate path syntax and existing symlink components."""
    relative = PurePosixPath(name)
    if (not name or str(relative) != name or relative.is_absolute()
            or ".." in relative.parts or "\\" in name or ":" in name):
        raise ValueError("Unsafe transport path")
    root = Path(root).resolve()
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("Symlink in transport path")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Transport path escapes destination")
    return path


def write_identical(path, data):
    """Create a file exclusively, accepting an already identical regular file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as output:
            output.write(data)
    except FileExistsError:
        if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
            raise FileExistsError("Refuse to overwrite different existing bytes")


def verify_members(data, members):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = [member["path"] for member in members]
        if len(set(names)) != len(names) or sorted(archive.namelist()) != sorted(names):
            raise ValueError("Unexpected or duplicate ZIP members")
        for member in members:
            name = member["path"]
            relative = PurePosixPath(name)
            if (not name or str(relative) != name or relative.is_absolute()
                    or ".." in relative.parts or "\\" in name or ":" in name):
                raise ValueError("Unsafe ZIP member path")
            if archive.getinfo(name).file_size != member["size"]:
                raise ValueError("ZIP member size differs")
            if sha256(archive.read(name)) != member["sha256"]:
                raise ValueError("ZIP member hash differs")


def pack(repository_root, indexes, destination, source_commit):
    """Preserve original manifests and wrap only files exceeding the new limit."""
    root, destination = Path(repository_root).resolve(), Path(destination).resolve()
    manifest = dict(schema=SCHEMA, source_commit=source_commit,
                    raw_chunk_bytes=RAW_CHUNK_BYTES, strict_blob_limit=STRICT_BLOB_LIMIT,
                    frozen_indexes=[], archives=[], removal_paths=[])
    seen = set()
    for index_name in indexes:
        index = safe_path(root, index_name)
        index_data = index.read_bytes()
        manifest["frozen_indexes"].append(dict(path=index_name, size=len(index_data),
                                              sha256=sha256(index_data), git_blob=git_blob(index_data)))
        for original in json.loads(index_data)["archives"]:
            name = original["file"]
            if PurePosixPath(name).name != name:
                raise ValueError("Archive name must be a basename")
            relative = (PurePosixPath(index_name).parent / name).as_posix()
            source = safe_path(root, relative)
            if original["size"] < STRICT_BLOB_LIMIT:
                continue
            data = source.read_bytes()
            if len(data) != original["size"] or sha256(data) != original["sha256"]:
                raise ValueError("Original ZIP differs from frozen manifest")
            verify_members(data, original["members"])
            if relative in seen:
                raise ValueError("Duplicate source archive")
            seen.add(relative)
            entry = dict(source_path=relative, source_git_blob=git_blob(data),
                         size=len(data), sha256=sha256(data), frozen_index=index_name,
                         members=original["members"], chunks=[])
            for number, offset in enumerate(range(0, len(data), RAW_CHUNK_BYTES)):
                raw = data[offset:offset + RAW_CHUNK_BYTES]
                encoded = gzip.compress(raw, compresslevel=9, mtime=0)
                if len(encoded) >= STRICT_BLOB_LIMIT:
                    raise ValueError("Compressed container exceeds strict blob limit")
                chunk_name = f"chunks/{git_blob(data)}.{number:03d}.gz"
                write_identical(safe_path(destination, chunk_name), encoded)
                entry["chunks"].append(dict(file=chunk_name, size=len(encoded),
                                            sha256=sha256(encoded), raw_size=len(raw),
                                            raw_sha256=sha256(raw)))
            manifest["archives"].append(entry)
            manifest["removal_paths"].append(relative)
    encoded = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    write_identical(safe_path(destination, "MANIFEST.json"), encoded)
    return manifest


def restore(manifest_path, destination):
    """Validate every container and member before creating any reconstructed ZIP."""
    manifest_path, destination = Path(manifest_path), Path(destination).resolve()
    manifest = json.loads(manifest_path.read_bytes())
    if manifest["schema"] != SCHEMA:
        raise ValueError("Unknown transport schema")
    pending, targets, member_count = [], set(), 0
    for entry in manifest["archives"]:
        target = safe_path(destination, entry["source_path"])
        if target in targets:
            raise ValueError("Duplicate reconstructed archive path")
        targets.add(target)
        pieces = []
        for chunk in entry["chunks"]:
            path = safe_path(manifest_path.parent, chunk["file"])
            if not 0 < chunk["size"] < STRICT_BLOB_LIMIT or path.stat().st_size != chunk["size"]:
                raise ValueError("Invalid compressed container size")
            encoded = path.read_bytes()
            if sha256(encoded) != chunk["sha256"]:
                raise ValueError("Compressed container hash differs")
            if not 0 < chunk["raw_size"] <= RAW_CHUNK_BYTES:
                raise ValueError("Invalid decompressed chunk size")
            with gzip.GzipFile(fileobj=io.BytesIO(encoded)) as stream:
                raw = stream.read(chunk["raw_size"] + 1)
            if len(raw) != chunk["raw_size"] or sha256(raw) != chunk["raw_sha256"]:
                raise ValueError("Decompressed chunk differs")
            pieces.append(raw)
        data = b"".join(pieces)
        if (len(data) != entry["size"] or sha256(data) != entry["sha256"]
                or git_blob(data) != entry["source_git_blob"]):
            raise ValueError("Reconstructed ZIP differs from original bytes")
        verify_members(data, entry["members"])
        if target.exists() and (not target.is_file() or target.read_bytes() != data):
            raise FileExistsError("Refuse to overwrite different existing bytes")
        pending.append((target, data))
        member_count += len(entry["members"])
    for target, data in pending:
        write_identical(target, data)
    return dict(restored_archives=len(pending), verified_members=member_count,
                original_git_blobs_verified=True, byte_identities_verified=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("pack", "restore"))
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--index", action="append", default=[])
    parser.add_argument("--source-commit")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.operation == "pack":
        if not args.index or not args.source_commit:
            parser.error("pack requires --index and --source-commit")
        manifest = pack(args.repository_root, args.index, args.destination, args.source_commit)
        result = dict(archives=len(manifest["archives"]),
                      chunks=sum(len(item["chunks"]) for item in manifest["archives"]))
    else:
        if args.manifest is None:
            parser.error("restore requires --manifest")
        result = restore(args.manifest, args.destination)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
