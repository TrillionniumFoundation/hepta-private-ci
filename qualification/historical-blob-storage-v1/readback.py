#!/usr/bin/env python3
"""Verify four historical artifacts; optionally restore exact bytes outside the repo."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import zlib


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = "qualification/historical-blob-storage-v1/ARCHIVE.json"
MAX_METADATA_BYTES = 65536
MAX_PART_BYTES = 256 * 1024
ORIGINALS = {
    "qualification/cell-six-refactors/evidence/native-a8dd9d46.tar.gz": (
        531052, "4a65450b81e7fe82483f5568d020d821a74587ddf53026f9affa6bfb06b2d655"
    ),
    "qualification/cell-six-refactors/evidence/native-c058c08f.tar.gz": (
        538535, "e9bc765e153a79a15fab46433aa49ca57cfe25d1e48b76941dc627ae6f3634b3"
    ),
    "qualification/cell-six-refactors/evidence/native-cb6f0a4a.tar.gz": (
        563937, "a6f32c739eae672bcb946b8c0496f3c2009a98fa3a6f8542b87d1ccc0d63cb07"
    ),
    "qualification/hcsn/evidence/cloud-20261105/attempt-safe/full.json": (
        830338, "65e999fa43c100b43a0b92b481c3d39ef5575ab1640c7b4cdd09dc1d72ade9a6"
    ),
}
PRESERVED_PATHS = {
    "qualification/cell-six-refactors/evidence/manifest.json",
    *(
        f"qualification/cell-six-refactors/evidence/native-{revision}/archive-verification.json"
        for revision in ("a8dd9d46", "c058c08f", "cb6f0a4a")
    ),
    "qualification/hcsn/evidence/cloud-20261105/attempt-safe/summary.json",
    "qualification/hcsn/evidence/cloud-20261105/attempt-safe/full-population-audit.json",
}


class ArchiveError(ValueError):
    """The stored representation does not match the closed historical inventory."""


def require(condition, message):
    if not condition:
        raise ArchiveError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def safe_path(root, relative):
    require(isinstance(relative, str) and relative, "empty path")
    parts = relative.split("/")
    require(
        not PurePosixPath(relative).is_absolute()
        and all(part not in ("", ".", "..") for part in parts)
        and "\\" not in relative and ":" not in relative,
        f"unsafe relative path: {relative}",
    )
    path = root
    for part in parts:
        path = path / part
        require(not path.is_symlink(), f"symlink: {relative}")
    return path


def bounded_read(root, relative, limit):
    path = safe_path(root, relative)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode), f"not a regular file: {relative}")
        require(info.st_size <= limit, f"stored size exceeds bound: {relative}")
        data = stream.read(limit + 1)
    require(len(data) <= limit, f"read exceeds bound: {relative}")
    return data


def check_pin(data, pin, label):
    require(type(pin["bytes"]) is int and len(data) == pin["bytes"], f"size mismatch: {label}")
    require(hashlib.sha256(data).hexdigest() == pin["sha256"], f"SHA-256 mismatch: {label}")


def decode_gzip(data, expected_size):
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        decoded = decoder.decompress(data, expected_size + 1)
    except zlib.error as error:
        raise ArchiveError(f"invalid gzip: {error}") from error
    require(len(decoded) == expected_size, "decoded size mismatch or overflow")
    require(decoder.eof, "truncated gzip or decoded overflow")
    require(not decoder.unused_data and not decoder.unconsumed_tail, "extra gzip data")
    return decoded


def verify(root):
    root = Path(root).resolve(strict=True)
    manifest = json.loads(
        bounded_read(root, MANIFEST, MAX_METADATA_BYTES), object_pairs_hook=unique_object
    )
    require(manifest["schema"] == "historical-blob-storage-v1", "unknown schema")
    entries = manifest["artifacts"]
    require(isinstance(entries, list) and len(entries) == len(ORIGINALS), "artifact count")
    decoded = {}
    for entry in entries:
        path = entry["path"]
        require(path in ORIGINALS and path not in decoded, "unknown or duplicate artifact")
        size, digest = ORIGINALS[path]
        require(
            type(entry["bytes"]) is int and (entry["bytes"], entry["sha256"]) == (size, digest),
            f"original identity changed: {path}",
        )
        require(not safe_path(root, path).exists(), f"ambiguous original and archive: {path}")
        storage = entry["storage"]
        kind = "concat" if path.endswith(".tar.gz") else "gzip"
        require(storage["kind"] == kind, f"wrong encoding: {path}")
        parts = storage["parts"]
        count = (size + MAX_PART_BYTES - 1) // MAX_PART_BYTES if kind == "concat" else 1
        require(isinstance(parts, list) and len(parts) == count, f"part count: {path}")
        chunks = []
        offset = 0
        for index, part in enumerate(parts):
            expected_path = f"{path}.parts/part-{index:03d}.bin" if kind == "concat" else path + ".gz"
            require(part["path"] == expected_path, f"part order or path: {path}")
            require(type(part["offset"]) is int and part["offset"] == offset, f"part offset: {path}")
            require(type(part["bytes"]) is int and 0 < part["bytes"] <= MAX_PART_BYTES, "part bound")
            if kind == "concat":
                require(part["bytes"] == min(MAX_PART_BYTES, size - offset), "part length")
            data = bounded_read(root, part["path"], part["bytes"])
            check_pin(data, part, part["path"])
            chunks.append(data)
            offset += len(data)
        data = b"".join(chunks)
        if kind == "gzip":
            data = decode_gzip(data, size)
        check_pin(data, entry, path)
        decoded[path] = data
    require(set(decoded) == set(ORIGINALS), "incomplete inventory")
    preserved = manifest["preserved_files"]
    require(isinstance(preserved, list) and len(preserved) == len(PRESERVED_PATHS), "receipt count")
    seen = set()
    for pin in preserved:
        path = pin["path"]
        require(path in PRESERVED_PATHS and path not in seen, "unknown or duplicate receipt")
        check_pin(bounded_read(root, path, MAX_METADATA_BYTES), pin, path)
        seen.add(path)
    require(seen == PRESERVED_PATHS, "incomplete original receipt inventory")
    return decoded


def restore(root, destination):
    root = Path(root).resolve(strict=True)
    data = verify(root)
    destination = Path(destination).absolute()
    require(destination.name not in ("", ".", ".."), "invalid destination")
    destination = destination.parent.resolve(strict=True) / destination.name
    require(destination != root and root not in destination.parents, "restore must be outside repository")
    destination.mkdir(mode=0o700)
    for relative, content in data.items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        with os.fdopen(os.open(path, flags, 0o600), "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        check_pin(
            bounded_read(destination, relative, len(content)),
            {"bytes": len(content), "sha256": ORIGINALS[relative][1]}, relative,
        )
    return destination, data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--restore-dir", type=Path, help="Create a new directory outside the repository")
    args = parser.parse_args()
    try:
        if args.restore_dir is None:
            decoded = verify(args.repo_root)
            destination = None
        else:
            destination, decoded = restore(args.repo_root, args.restore_dir)
        report = {
            "schema": "historical-blob-readback-v1",
            "scope": "storage_integrity_only",
            "status": "pass",
            "restore_directory": str(destination) if destination is not None else None,
            "artifacts": [
                {"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                for path, data in decoded.items()
            ],
            "historical_receipts_verified": len(PRESERVED_PATHS),
            "training_or_model_execution": False,
            "qualification_status_changed": False,
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "fail", "scope": "storage_integrity_only", "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
