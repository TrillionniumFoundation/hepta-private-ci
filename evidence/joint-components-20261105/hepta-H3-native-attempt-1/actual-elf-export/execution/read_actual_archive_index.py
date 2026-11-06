"""Read one pinned completed H3 archive, verify it, and retain its actual index."""
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import time

ARCHIVE = Path("/home/qian-qi/work/hepta-h3-actual-elf-export-20261105-93bfc-01/H3-actual-retained-elfs.tar.xz")
ARCHIVE_BYTES = 283427280
ARCHIVE_SHA = "5365fcf900781044108e9642ae02a110e4ac8d031d9ee516c4f0b0e471e1e773"
INDEX_SHA = "b023aca6ab2dccf4324dccab2e5319a00ef9b32773e0dc73127efc9af3caa002"
OUTPUT = Path("/home/qian-qi/work/hepta-h3-archive-index-readback-20261105-93bfc-01")
BLOCK = 1024 * 1024


def require(ok, message):
    if not ok:
        raise ValueError(message)


def identity(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_mode, s.st_nlink)


def open_source(path):
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    descriptor = None
    try:
        for part in path.parts[1:-1]:
            next_directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size == ARCHIVE_BYTES, "exact regular archive required")
        result = os.fdopen(descriptor, "rb")
        descriptor = None
        return result, identity(info)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)


class HashReader:
    def __init__(self, stream):
        self.stream, self.digest, self.count = stream, hashlib.sha256(), 0

    def read(self, n=-1):
        data = self.stream.read(n)
        self.count += len(data)
        require(self.count <= ARCHIVE_BYTES, "archive grew while read")
        self.digest.update(data)
        return data


started = time.monotonic()
source, before = open_source(ARCHIVE)
members = {}
index_raw = None
with source:
    reader = HashReader(source)
    with tarfile.open(fileobj=reader, mode="r|xz") as archive:
        for member in archive:
            require(member.isfile() and member.name not in members and 0 <= member.size <= 1674575368, "unexpected member")
            require(len(members) < 16, "member count exceeds frozen inventory")
            if member.name == "export-index.json":
                require(member.size <= 2 * BLOCK, "bounded index required")
            hasher, size, chunks = hashlib.sha256(), 0, []
            with archive.extractfile(member) as stream:
                while True:
                    data = stream.read(BLOCK)
                    if not data:
                        break
                    size += len(data)
                    require(size <= member.size, "member extent changed")
                    hasher.update(data)
                    if member.name == "export-index.json":
                        chunks.append(data)
            require(size == member.size, "truncated member")
            members[member.name] = dict(bytes=size, sha256=hasher.hexdigest())
            if member.name == "export-index.json":
                index_raw = b"".join(chunks)
    while reader.read(BLOCK):
        pass
    require(identity(os.fstat(source.fileno())) == before, "archive changed during read")
require(reader.count == ARCHIVE_BYTES and reader.digest.hexdigest() == ARCHIVE_SHA, "actual complete archive hash differs")
require(index_raw is not None and hashlib.sha256(index_raw).hexdigest() == INDEX_SHA, "actual index hash differs")
index = json.loads(index_raw)
require(index["phase"] == "H3" and index["source_commit"] == "6db78eca53a5acdda0d96873d3f4cd65863426f0" and
        index["source_tree"] == "e91f5994017fc5d2cfe58d405a20ee6ad9376772", "wrong actual source phase")
require(index["plan_sha256"] == "7c140e2a83e9df657aff17c66bb1f307bb6b8a22db6cbba04e38841d7b9ef7a0" and
        index["exporter_sha256"] == "9eb404993262589a948a19946819e890ff15875bef1133eab5fe9cee6bb14f53", "wrong frozen exporter/plan")
require(index["original_run_outcome"]["result"] == "FAILED" and index["native_reexecution"] is False, "original native outcome changed")
require(len(index["files"]) == 11 and sum(row["bytes"] for row in index["files"]) == 1674575368, "wrong complete images")
expected = {row["name"]: dict(bytes=row["bytes"], sha256=row["sha256"]) for row in index["files"]}
expected.update(index["embedded_metadata_files"])
expected["export-index.json"] = dict(bytes=len(index_raw), sha256=INDEX_SHA)
require(members == expected and len(members) == 16, "actual member content differs from pinned index")
require(OUTPUT.parent.resolve(strict=True) == OUTPUT.parent and not OUTPUT.exists(), "fresh output required")
OUTPUT.mkdir(mode=0o700)
path = OUTPUT / "export-index.json"
with path.open("xb") as destination:
    require(destination.write(index_raw) == len(index_raw), "short index write")
    destination.flush()
    os.fsync(destination.fileno())
require(path.read_bytes() == index_raw, "written actual index differs")
report = dict(schema="H3-completed-archive-index-actual-readback-v1", archive_path=str(ARCHIVE),
    archive_bytes=ARCHIVE_BYTES, archive_sha256=ARCHIVE_SHA, source_identity_before=before,
    archive_and_all_members_actually_rehashed=True, actual_members=members,
    index_path=str(path), index_bytes=len(index_raw), index_sha256=INDEX_SHA,
    elapsed_seconds=time.monotonic() - started, native_reexecution=False, original_native_outcome="FAILED")
raw = (json.dumps(report, sort_keys=True, indent=2) + "\n").encode()
with (OUTPUT / "readback.json").open("xb") as destination:
    destination.write(raw)
    destination.flush()
    os.fsync(destination.fileno())
for directory in (OUTPUT, OUTPUT.parent):
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
print(json.dumps(report, sort_keys=True), flush=True)
