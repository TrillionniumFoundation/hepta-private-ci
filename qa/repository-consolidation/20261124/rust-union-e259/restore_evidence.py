#!/usr/bin/env python3
"""Verify or restore a standard tar+gzip evidence archive from bounded chunks."""

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tarfile
import tempfile


MAX_COMPRESSED_BYTES = 128 * 1024 * 1024
MAX_TAR_BYTES = 512 * 1024 * 1024
MAX_CHUNK_BYTES = 90_000
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def safe_member_name(name):
    require(isinstance(name, str) and name, "empty or non-string member name")
    require("\\" not in name and "\0" not in name and ":" not in name, "unsafe member name")
    path = PurePosixPath(name)
    require(not path.is_absolute(), "absolute archive member")
    require(path.as_posix() == name, "noncanonical archive member")
    require(all(part not in {"", ".", ".."} for part in path.parts), "traversal member")
    return path


def digest_valid(value):
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def read_bounded_regular(path, limit, expected_size=None):
    before = path.stat(follow_symlinks=False)
    require(stat.S_ISREG(before.st_mode), "input must be a regular file")
    require(before.st_size <= limit, "input exceeds read bound")
    if expected_size is not None:
        require(before.st_size == expected_size, "declared input size mismatch")

    def identity(value):
        return value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns

    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        require(identity(os.fstat(stream.fileno())) == identity(before), "input changed before open")
        data = stream.read(limit + 1)
        require(identity(os.fstat(stream.fileno())) == identity(before), "input changed during read")
    require(identity(path.stat(follow_symlinks=False)) == identity(before), "input path changed during read")
    require(len(data) == before.st_size and len(data) <= limit, "bounded input length mismatch")
    return data


class CountingReader:
    def __init__(self, stream, limit):
        self.stream = stream
        self.limit = limit
        self.bytes = 0
        self.sha256 = hashlib.sha256()

    def read(self, size=-1):
        if size < 0:
            size = min(1024 * 1024, self.limit - self.bytes + 1)
        data = self.stream.read(size)
        self.bytes += len(data)
        require(self.bytes <= self.limit, "decompressed archive exceeds declared bound")
        self.sha256.update(data)
        return data


def verify_checkpoint(manifest_path, destination=None):
    manifest_path = Path(manifest_path).resolve(strict=True)
    document = json.loads(read_bounded_regular(manifest_path, 32 * 1024 * 1024))
    require(document.get("schema") == "hepta.audit.checkpoint.v1", "unknown manifest schema")
    archive = document["archive"]
    members = document["members"]
    chunks = document["chunks"]
    require(type(archive["bytes"]) is int and 0 < archive["bytes"] <= MAX_COMPRESSED_BYTES, "compressed size bound")
    require(type(archive["tar_bytes"]) is int and 0 < archive["tar_bytes"] <= MAX_TAR_BYTES, "tar size bound")
    require(digest_valid(archive["sha256"]) and digest_valid(archive["tar_sha256"]), "archive digest invalid")
    require(isinstance(members, list) and 0 < len(members) <= 20_000, "member count bound")
    require(isinstance(chunks, list) and chunks, "missing chunks")
    expected = {}
    casefolded = set()
    total_payload = 0
    for member in members:
        name = member["path"]
        safe_member_name(name)
        require(name not in expected and name.casefold() not in casefolded, "duplicate/case-alias member")
        require(type(member["bytes"]) is int and 0 <= member["bytes"] <= MAX_TAR_BYTES, "member size bound")
        require(digest_valid(member["sha256"]), "member digest invalid")
        require(type(member["mode"]) is int and 0 <= member["mode"] <= 0o777, "member mode invalid")
        expected[name] = member
        casefolded.add(name.casefold())
        total_payload += member["bytes"]
    require(total_payload <= MAX_TAR_BYTES, "payload size bound")
    compressed = bytearray()
    seen_chunks = set()
    for index, chunk in enumerate(chunks):
        name = chunk["path"]
        require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name), "unsafe chunk name")
        require(name not in seen_chunks and chunk["index"] == index, "duplicate/unordered chunk")
        require(type(chunk["bytes"]) is int and 0 < chunk["bytes"] <= MAX_CHUNK_BYTES, "chunk size bound")
        require(digest_valid(chunk["sha256"]), "chunk digest invalid")
        path = manifest_path.parent / name
        require(not path.is_symlink() and path.is_file(), "chunk must be a regular file")
        require(path.resolve().parent == manifest_path.parent, "chunk path escapes checkpoint")
        data = read_bounded_regular(path, MAX_CHUNK_BYTES, chunk["bytes"])
        require(hashlib.sha256(data).hexdigest() == chunk["sha256"], "chunk digest mismatch")
        require(len(compressed) + len(data) <= archive["bytes"], "chunks exceed declared archive size")
        compressed.extend(data)
        seen_chunks.add(name)
    require(len(compressed) == archive["bytes"], "archive byte count mismatch")
    require(hashlib.sha256(compressed).hexdigest() == archive["sha256"], "archive digest mismatch")

    stage = None
    destination_path = None
    if destination is not None:
        destination_path = Path(destination).absolute()
        require(not destination_path.exists() and not destination_path.is_symlink(), "restore destination must not exist")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".hepta-audit-restore-", dir=destination_path.parent))
    observed = set()
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as stream:
            reader = CountingReader(stream, archive["tar_bytes"])
            with tarfile.open(fileobj=reader, mode="r|") as container:
                for entry in container:
                    name = entry.name
                    safe_member_name(name)
                    require(entry.isfile() and not entry.issparse(), "archive contains a nonregular member")
                    require(name in expected and name not in observed, "unexpected/duplicate tar member")
                    metadata = expected[name]
                    require(entry.size == metadata["bytes"], "tar member size mismatch")
                    require(entry.mode == metadata["mode"], "tar member mode mismatch")
                    digest = hashlib.sha256()
                    count = 0
                    target = None
                    if stage is not None:
                        target_path = stage.joinpath(*PurePosixPath(name).parts)
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        target = target_path.open("xb")
                    try:
                        source = container.extractfile(entry)
                        require(source is not None, "tar member unreadable")
                        with source:
                            while data := source.read(1024 * 1024):
                                count += len(data)
                                digest.update(data)
                                if target is not None:
                                    target.write(data)
                        require(count == metadata["bytes"], "member byte count mismatch")
                        require(digest.hexdigest() == metadata["sha256"], "member digest mismatch")
                    finally:
                        if target is not None:
                            target.close()
                    if stage is not None:
                        target_path.chmod(metadata["mode"])
                    observed.add(name)
            # Drain through the counting layer to check the complete gzip CRC,
            # complete tar digest and any bytes after tar's end-of-archive blocks.
            while reader.read(1024 * 1024):
                pass
            require(reader.bytes == archive["tar_bytes"], "complete tar byte count mismatch")
            require(reader.sha256.hexdigest() == archive["tar_sha256"], "complete tar digest mismatch")
        require(observed == set(expected), "archive is missing declared members")
        if stage is not None:
            require(not destination_path.exists() and not destination_path.is_symlink(), "restore destination appeared during verification")
            os.rename(stage, destination_path)
            stage = None
        return {
            "verified": True,
            "archive_sha256": archive["sha256"],
            "archive_bytes": archive["bytes"],
            "tar_sha256": archive["tar_sha256"],
            "tar_bytes": archive["tar_bytes"],
            "verified_chunks": len(chunks),
            "verified_members": len(observed),
            "verified_payload_bytes": total_payload,
            "restored_to": str(destination_path) if destination_path is not None else None,
        }
    finally:
        if stage is not None:
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("EVIDENCE-MANIFEST.json"))
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument("--verify-only", action="store_true")
    output.add_argument("--destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_checkpoint(args.manifest, args.destination), indent=2))


if __name__ == "__main__":
    main()
