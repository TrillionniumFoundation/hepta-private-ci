"""Deterministic evidence archive parts and verified, non-overwriting restoration.

POSIX/Python 3 utility. Only evidence/ is packaged; no tar extract/extractall is used.
"""

import argparse
from contextlib import contextmanager
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shlex
import stat
import tarfile
import tempfile
import uuid
import zlib


CHUNK = 1024 * 1024
MANIFEST_LIMIT = 64 * CHUNK
SCHEMA = "hepta.evidence-archive.v1"
DEFAULT_DIRECTORY = "archives/evidence_v1"
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


def relative_path(name, evidence=False):
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise ValueError("Invalid relative path")
    path = PurePosixPath(name)
    if path.is_absolute() or str(path) != name or any(p in (".", "..") for p in path.parts):
        raise ValueError("Noncanonical or unsafe relative path: " + name)
    if not path.parts:
        raise ValueError("Empty relative path")
    name.encode("utf-8", errors="strict")
    if evidence and (path.parts[0] != "evidence" or len(path.parts) < 2):
        raise ValueError("Archive members must be files below evidence/: " + name)
    if evidence and "__pycache__" in path.parts:
        raise ValueError("Excluded cache directory in manifest")
    return path.parts


@contextmanager
def parent_fd(root, name, create=False):
    """Traverse only real directories, without following internal symlinks."""
    parts = relative_path(name)
    descriptor = os.open(root, DIRECTORY_FLAGS)
    try:
        for component in parts[:-1]:
            try:
                child = os.open(component, DIRECTORY_FLAGS, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    yield None
                    return
                try:
                    os.mkdir(component, mode=0o755, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(component, DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def regular_file(root, name):
    with parent_fd(root, name) as parent:
        if parent is None:
            raise FileNotFoundError(name)
        descriptor = os.open(relative_path(name)[-1], READ_FLAGS, dir_fd=parent)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("Not a regular file: " + name)
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                yield stream
        finally:
            os.close(descriptor)


def hash_stream(stream, destination=None):
    digest, size = hashlib.sha256(), 0
    while True:
        block = stream.read(CHUNK)
        if not block:
            break
        digest.update(block)
        size += len(block)
        if destination is not None:
            destination.write(block)
    return size, digest.hexdigest()


def snapshot(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def inventory(root):
    evidence = root / "evidence"
    if not stat.S_ISDIR(evidence.lstat().st_mode):
        raise ValueError("evidence/ must be a real directory, not a symlink")
    found = {}
    for directory, directories, files in os.walk(evidence, followlinks=False):
        directories[:] = sorted(d for d in directories if d != "__pycache__")
        for name in directories:
            if not stat.S_ISDIR((Path(directory) / name).lstat().st_mode):
                raise ValueError("Symlink or special directory under evidence/")
        for name in sorted(files):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            relative_path(relative, evidence=True)
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Symlink or special evidence file: " + relative)
            found[relative] = snapshot(info)
    return dict(sorted(found.items()))


class HashingReader:
    def __init__(self, stream):
        self.stream, self.digest, self.size = stream, hashlib.sha256(), 0

    def read(self, size):
        block = self.stream.read(size)
        self.digest.update(block)
        self.size += len(block)
        return block


def write_tar(root, archive, files):
    members = []
    with gzip.GzipFile(filename="", mode="wb", fileobj=archive,
                       compresslevel=6, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as tar:
            for name, expected in files.items():
                with regular_file(root, name) as source:
                    if snapshot(os.fstat(source.fileno())) != expected:
                        raise RuntimeError("Evidence changed before reading: " + name)
                    info = tarfile.TarInfo(name)
                    info.size, info.mode, info.mtime = expected[2], 0o644, 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    reader = HashingReader(source)
                    tar.addfile(info, reader)
                    if reader.size != info.size or snapshot(os.fstat(source.fileno())) != expected:
                        raise RuntimeError("Evidence changed while reading: " + name)
                    members.append({"path": name, "bytes": reader.size,
                                    "sha256": reader.digest.hexdigest()})
    if inventory(root) != files:
        raise RuntimeError("Evidence tree changed during archive creation")
    return members


def create(root, directory):
    parts = relative_path(directory)
    if parts[0] == "evidence":
        raise ValueError("Archive output cannot be inside evidence/")
    files = inventory(root)
    # mkdir is exclusive: even an existing empty output directory is rejected.
    with parent_fd(root, directory, create=True) as parent:
        os.mkdir(parts[-1], mode=0o755, dir_fd=parent)
    output = root.joinpath(*parts)
    records, aggregate, archive_bytes = [], hashlib.sha256(), 0
    with tempfile.TemporaryFile(mode="w+b", dir=output) as archive:
        members = write_tar(root, archive, files)
        archive.seek(0)
        while True:
            block = archive.read(CHUNK)
            if not block:
                break
            name = f"evidence.tar.gz.part-{len(records):06d}"
            with (output / name).open("xb") as stream:
                stream.write(block)
            records.append({"path": name, "bytes": len(block),
                            "sha256": hashlib.sha256(block).hexdigest()})
            aggregate.update(block)
            archive_bytes += len(block)
    manifest = {
        "schema": SCHEMA,
        "scope": {"included_root": "evidence/", "excluded_directory_names": ["__pycache__"],
                  "empty_files_included": True,
                  "not_included": ["archives/ output", "source files outside evidence/",
                                   "top-level reports", "repository Git metadata outside evidence/"]},
        "format": {"tar": "PAX", "compression": "gzip", "compression_level": 6,
                   "gzip_filename": "", "mtime": 0, "uid": 0, "gid": 0,
                   "file_mode": "0644", "member_order": "POSIX path lexicographic",
                   "part_bytes": CHUNK},
        "toolchain": {"python": platform.python_version(), "zlib_compile": zlib.ZLIB_VERSION,
                      "zlib_runtime": zlib.ZLIB_RUNTIME_VERSION},
        "archive": {"name": "evidence.tar.gz", "bytes": archive_bytes,
                    "sha256": aggregate.hexdigest(), "member_count": len(members),
                    "member_bytes": sum(m["bytes"] for m in members)},
        "parts": records, "members": members,
        "restore_command": "python3 archive_evidence.py restore --manifest " + shlex.quote(directory + "/MANIFEST.json"),
        "restore_policy": "Verify every part, aggregate and member before restoring; equal files skip, different files reject.",
    }
    data = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()
    with (output / "MANIFEST.json").open("xb") as stream:
        stream.write(data)
    return {"operation": "create", "directory": directory, "files": len(members),
            "parts": len(records), "archive_bytes": archive_bytes,
            "archive_sha256": aggregate.hexdigest(), "manifest_sha256": hashlib.sha256(data).hexdigest()}


def validate_record(record, name):
    if not isinstance(record, dict) or not isinstance(record.get("bytes"), int) or isinstance(record["bytes"], bool):
        raise ValueError("Invalid byte count: " + name)
    if record["bytes"] < 0 or not re.fullmatch("[0-9a-f]{64}", str(record.get("sha256", ""))):
        raise ValueError("Invalid digest or size: " + name)


def load_manifest(root, directory):
    relative_path(directory)
    with regular_file(root, directory + "/MANIFEST.json") as stream:
        if os.fstat(stream.fileno()).st_size > MANIFEST_LIMIT:
            raise ValueError("Manifest exceeds the bounded metadata limit")
        data = stream.read(MANIFEST_LIMIT + 1)
        if len(data) > MANIFEST_LIMIT:
            raise ValueError("Manifest grew beyond the bounded metadata limit")
        manifest = json.loads(data)
    if manifest.get("schema") != SCHEMA or manifest.get("format", {}).get("part_bytes") != CHUNK:
        raise ValueError("Unsupported archive manifest")
    members, parts = manifest["members"], manifest["parts"]
    if not isinstance(members, list) or not isinstance(parts, list) or not parts:
        raise ValueError("Invalid member/part lists")
    paths = []
    for member in members:
        validate_record(member, "member")
        relative_path(member["path"], evidence=True)
        paths.append(member["path"])
    if paths != sorted(set(paths)):
        raise ValueError("Members must be unique and sorted")
    path_set = set(paths)
    for name in paths:
        if any(parent.as_posix() in path_set for parent in PurePosixPath(name).parents):
            raise ValueError("A declared file is also another member's parent")
    for index, part in enumerate(parts):
        validate_record(part, "part")
        if part.get("path") != f"evidence.tar.gz.part-{index:06d}":
            raise ValueError("Unexpected or unordered part filename")
        if not 0 < part["bytes"] <= CHUNK or (index < len(parts) - 1 and part["bytes"] != CHUNK):
            raise ValueError("Invalid part length")
    archive = manifest["archive"]
    validate_record(archive, "archive")
    if archive["bytes"] != sum(p["bytes"] for p in parts) or archive["member_count"] != len(members):
        raise ValueError("Archive count/size does not match manifest")
    if archive["member_bytes"] != sum(m["bytes"] for m in members):
        raise ValueError("Uncompressed member size mismatch")
    return manifest


def reconstruct(root, directory, manifest, archive):
    aggregate, total = hashlib.sha256(), 0
    for part in manifest["parts"]:
        with regular_file(root, directory + "/" + part["path"]) as source:
            if os.fstat(source.fileno()).st_size != part["bytes"]:
                raise ValueError("Part size mismatch: " + part["path"])
            digest, size = hashlib.sha256(), 0
            while True:
                block = source.read(CHUNK)
                if not block:
                    break
                digest.update(block)
                aggregate.update(block)
                archive.write(block)
                size += len(block)
            if size != part["bytes"] or digest.hexdigest() != part["sha256"]:
                raise ValueError("Part integrity mismatch: " + part["path"])
            total += size
    if total != manifest["archive"]["bytes"] or aggregate.hexdigest() != manifest["archive"]["sha256"]:
        raise ValueError("Aggregate archive integrity mismatch")
    archive.flush()


def read_exact(stream, size):
    data = stream.read(size)
    if len(data) != size:
        raise ValueError("Truncated tar stream")
    return data


def pax_fields(payload):
    """Only the bounded path/size extensions emitted by this writer are accepted."""
    result, offset = {}, 0
    while offset < len(payload):
        space = payload.find(b" ", offset)
        if space < 0 or not payload[offset:space].isdigit():
            raise ValueError("Malformed PAX length")
        end = offset + int(payload[offset:space])
        if end <= space + 1 or end > len(payload) or payload[end - 1:end] != b"\n":
            raise ValueError("Malformed PAX record")
        key, separator, value = payload[space + 1:end - 1].partition(b"=")
        key, value = key.decode("utf-8"), value.decode("utf-8")
        if not separator or key not in ("path", "size") or key in result:
            raise ValueError("Unsupported or duplicate PAX field")
        result[key], offset = value, end
    return result


class MemberReader:
    def __init__(self, stream, size):
        self.stream, self.remaining = stream, size

    def read(self, size=CHUNK):
        if not self.remaining:
            return b""
        amount = min(self.remaining, CHUNK, size if size >= 0 else CHUNK)
        block = read_exact(self.stream, amount)
        self.remaining -= len(block)
        return block


def tar_members(archive, expected):
    # Parse fixed 512-byte headers before reading extensions. tarfile's normal
    # iterator can allocate arbitrary PAX/GNU metadata before yielding a member.
    archive.seek(0)
    count, pending = 0, None
    with gzip.GzipFile(fileobj=archive, mode="rb") as compressed:
        while True:
            header = read_exact(compressed, 512)
            if header == bytes(512):
                if pending is not None or read_exact(compressed, 512) != bytes(512):
                    raise ValueError("Invalid tar terminator")
                break
            info = tarfile.TarInfo.frombuf(header, "utf-8", "strict")
            if info.type == tarfile.XHDTYPE:
                if pending is not None or not 0 <= info.size <= CHUNK:
                    raise ValueError("PAX metadata is repeated or exceeds 1 MiB")
                pending = pax_fields(read_exact(compressed, info.size))
                if any(read_exact(compressed, (-info.size) % 512)):
                    raise ValueError("Nonzero PAX padding")
                continue
            if info.type not in (tarfile.REGTYPE, tarfile.AREGTYPE) or info.linkname:
                raise ValueError("Link, sparse, special or unsupported tar member rejected")
            if pending is not None:
                info.name = pending.get("path", info.name)
                if "size" in pending:
                    if not re.fullmatch("[0-9]+", pending["size"]):
                        raise ValueError("Invalid PAX size")
                    info.size = int(pending["size"])
                pending = None
            if count >= len(expected):
                raise ValueError("Undeclared extra archive member")
            meta = expected[count]
            relative_path(info.name, evidence=True)
            if info.name != meta["path"] or info.size != meta["bytes"]:
                raise ValueError("Tar member identity/size mismatch")
            stream = MemberReader(compressed, info.size)
            yield meta, stream
            if stream.remaining or any(read_exact(compressed, (-info.size) % 512)):
                raise ValueError("Unconsumed member or nonzero tar padding")
            count += 1
        # Read all padding and the gzip trailer/CRC without unbounded allocation.
        while True:
            padding = compressed.read(CHUNK)
            if not padding:
                break
            if any(padding):
                raise ValueError("Unexpected data after tar terminator")
    if count != len(expected):
        raise ValueError("Archive is missing declared members")


def verify_member(meta, stream, destination=None):
    size, digest = hash_stream(stream, destination)
    if size != meta["bytes"] or digest != meta["sha256"]:
        raise ValueError("Member integrity mismatch: " + meta["path"])


def existing_matches(root, meta):
    try:
        with regular_file(root, meta["path"]) as stream:
            if os.fstat(stream.fileno()).st_size != meta["bytes"]:
                return False
            return hash_stream(stream)[1] == meta["sha256"]
    except FileNotFoundError:
        return None


def install_member(root, meta, stream):
    with parent_fd(root, meta["path"], create=True) as parent:
        name = relative_path(meta["path"])[-1]
        temporary = ".archive-restore-" + uuid.uuid4().hex
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=parent)
        try:
            with os.fdopen(descriptor, "wb") as destination:
                verify_member(meta, stream, destination)
                destination.flush()
                os.fchmod(destination.fileno(), 0o644)
                os.fsync(destination.fileno())
            os.utime(temporary, ns=(0, 0), dir_fd=parent, follow_symlinks=False)
            try:
                # link is an atomic no-replace install; replace/rename could overwrite.
                os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                return "restored"
            except FileExistsError:
                if existing_matches(root, meta) is True:
                    return "skipped"
                raise FileExistsError("Refusing to overwrite changed file: " + meta["path"])
        finally:
            os.unlink(temporary, dir_fd=parent)


def restore(root, directory):
    manifest = load_manifest(root, directory)
    restored = skipped = 0
    with tempfile.TemporaryFile(mode="w+b", dir=root) as archive:
        reconstruct(root, directory, manifest, archive)
        # Verify ALL members before creating evidence paths or restoring any file.
        for meta, stream in tar_members(archive, manifest["members"]):
            verify_member(meta, stream)
        for meta in manifest["members"]:
            if existing_matches(root, meta) is False:
                raise FileExistsError("Existing content differs; nothing restored: " + meta["path"])
        for meta, stream in tar_members(archive, manifest["members"]):
            if existing_matches(root, meta) is True:
                verify_member(meta, stream)
                skipped += 1
            else:
                result = install_member(root, meta, stream)
                restored += result == "restored"
                skipped += result == "skipped"
    return {"operation": "restore", "directory": directory, "restored": restored,
            "skipped_identical": skipped, "verified_members": len(manifest["members"]),
            "archive_sha256": manifest["archive"]["sha256"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    create_command = commands.add_parser("create", help="Create a new deterministic archive directory")
    restore_command = commands.add_parser("restore", help="Verify and restore from a manifest")
    for command in (create_command, restore_command):
        command.add_argument("--root", default=str(Path(__file__).resolve().parent))
    create_command.add_argument("--out", default=DEFAULT_DIRECTORY)
    restore_command.add_argument("--manifest", default=DEFAULT_DIRECTORY + "/MANIFEST.json")
    args = parser.parse_args()
    root = Path(args.root).resolve(strict=True)
    if not root.is_dir():
        parser.error("--root must be an existing project directory")
    if args.operation == "create":
        result = create(root, args.out)
    else:
        manifest_parts = relative_path(args.manifest)
        if manifest_parts[-1] != "MANIFEST.json" or len(manifest_parts) < 2:
            parser.error("--manifest must name a relative archive-directory/MANIFEST.json")
        result = restore(root, PurePosixPath(args.manifest).parent.as_posix())
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
