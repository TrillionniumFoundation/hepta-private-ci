"""Restore verified evidence as inert regular files, never execute its sources."""

import argparse
import hashlib
import io
import json
import lzma
from pathlib import Path
from pathlib import PurePosixPath
import re
import tarfile
import zlib


EXPECTED_INDEX_SHA256 = (
    "862f4e4d75c75cd19013d036cdc5db60c42c5fc527a63d5669dee8bf25752c4e"
)
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_COMPRESSED_BYTES = 64 * 1024 * 1024
MAX_FILES = 2048
MAX_PART_BYTES = 450000
MAX_SEGMENT_BYTES = 440000


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_name(name):
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or ":" in name
        or "\x00" in name
    ):
        raise ValueError("invalid evidence path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in name.split("/")):
        raise ValueError("non-canonical evidence path")
    if path.as_posix() != name:
        raise ValueError("non-canonical evidence path")
    return path


def check_size(value, limit):
    if type(value) is not int or value < 0 or value > limit:
        raise ValueError("invalid evidence size")
    return value


def verify_members(index, raw_tar):
    entries = index["files"]
    if not isinstance(entries, list) or not 0 < len(entries) <= MAX_FILES:
        raise ValueError("invalid evidence inventory")
    expected = {}
    for entry in entries:
        name = str(safe_name(entry["path"]))
        if name in expected:
            raise ValueError("duplicate inventory path")
        check_size(entry["bytes"], MAX_ARCHIVE_BYTES)
        if not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"]):
            raise ValueError("invalid file digest")
        expected[name] = entry
    for name in expected:
        if any(str(parent) in expected for parent in PurePosixPath(name).parents):
            raise ValueError("inventory file conflicts with a parent directory")
    restored = {}
    with tarfile.open(fileobj=io.BytesIO(raw_tar), mode="r:") as archive:
        for member in archive:
            name = str(safe_name(member.name))
            if not member.isreg() or member.linkname:
                raise ValueError("evidence contains a non-regular member")
            if name not in expected or name in restored:
                raise ValueError("unlisted or repeated archive member")
            entry = expected[name]
            if member.size != entry["bytes"]:
                raise ValueError("archive member size mismatch")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("unreadable archive member")
            data = stream.read(member.size + 1)
            if len(data) != entry["bytes"] or digest(data) != entry["sha256"]:
                raise ValueError("archive member digest mismatch")
            restored[name] = data
    if set(restored) != set(expected):
        raise ValueError("incomplete evidence inventory")
    return restored


def read_package(package):
    raw_index = (package / "INDEX.json").read_bytes()
    if digest(raw_index) != EXPECTED_INDEX_SHA256:
        raise ValueError("INDEX does not match this fixed restore script")
    index = json.loads(raw_index)
    if index["format"] != "native-blocker-evidence-v1":
        raise ValueError("unknown evidence format")
    size = check_size(index["archive_bytes"], MAX_ARCHIVE_BYTES)
    compressed_size = check_size(index["compressed_bytes"], MAX_COMPRESSED_BYTES)
    chunks, names = [], set()
    parts = index["parts"]
    if not isinstance(parts, list) or not 0 < len(parts) <= 160:
        raise ValueError("invalid archive part inventory")
    for part in parts:
        name = part["name"]
        if (
            not re.fullmatch(r"native-evidence\.tar\.xz\.part[0-9]{3}\.gz", name)
            or name in names
        ):
            raise ValueError("invalid or duplicate archive part")
        names.add(name)
        check_size(part["bytes"], MAX_PART_BYTES)
        path = package / name
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != part["bytes"]
        ):
            raise ValueError("missing or unexpected archive part")
        chunk = path.read_bytes()
        if digest(chunk) != part["sha256"]:
            raise ValueError("archive part digest mismatch")
        segment_size = check_size(part["segment_bytes"], MAX_SEGMENT_BYTES)
        decoder = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
        segment = decoder.decompress(chunk, segment_size + 1)
        if (
            not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
            or len(segment) != segment_size
            or digest(segment) != part["segment_sha256"]
        ):
            raise ValueError("invalid, excessive, or concatenated gzip part")
        chunks.append(segment)
    compressed = b"".join(chunks)
    if (
        len(compressed) != compressed_size
        or digest(compressed) != index["compressed_sha256"]
    ):
        raise ValueError("compressed archive mismatch")
    decoder = lzma.LZMADecompressor()
    raw_tar = decoder.decompress(compressed, max_length=size + 1)
    if not decoder.eof or decoder.unused_data or len(raw_tar) != size:
        raise ValueError("truncated, excessive, or concatenated compressed archive")
    if digest(raw_tar) != index["archive_sha256"]:
        raise ValueError("uncompressed archive mismatch")
    return index, verify_members(index, raw_tar)


def restore(package, destination):
    index, files = read_package(package)
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("destination already exists; refusing overwrite")
    parent = destination.parent.resolve(strict=True)
    destination = parent / destination.name
    destination.mkdir(mode=0o755, exist_ok=False)
    for name, data in sorted(files.items()):
        target = destination.joinpath(*safe_name(name).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
        target.chmod(0o644)
    return {
        "files": len(files),
        "bytes": sum(map(len, files.values())),
        "index_sha256": EXPECTED_INDEX_SHA256,
        "destination": str(destination),
        "restored_permissions": "0644 regular files; original modes are evidence only",
        "executed_sources": False,
        "archive_sha256": index["archive_sha256"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(restore(Path(__file__).resolve().parent, args.destination), indent=2)
    )


if __name__ == "__main__":
    main()
