#!/usr/bin/env python3
"""Deterministic, sharded publication archives; standard-library, POSIX only.

This is a publication utility, not part of the frozen scientific computation.
Inputs must be quiescent. No checkpoint or NPZ is deserialized or interpreted.
"""

import argparse
import fnmatch
import hashlib
import json
import lzma
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tarfile
import tempfile


FORMAT = "hcsn-publication-tar-xz-v1"
CHUNK_BYTES = 48 * 1024
EXCLUDED_DIRS = {"__pycache__", ".git", ".pytest_cache", "archive", "archives"}
ARCHIVE_GLOBS = ("*.tar", "*.tar.*", "*.tgz", "*.txz", "*.tbz*", "*.zip", "*.7z")
MANIFEST_LIMIT = 128 * 1024 * 1024
BUFFER_BYTES = 1024 * 1024


class ArchiveError(Exception):
    """Unsafe input, inconsistent evidence, or corrupt publication bundle."""


def require(condition, message):
    if not condition:
        raise ArchiveError(message)


def relative_path(value):
    require(isinstance(value, str) and bool(value), "Empty/non-string archive path")
    require(not any(ord(c) < 32 or ord(c) == 127 or c in "\\:" for c in value), f"Unsafe path: {value!r}")
    parts = value.split("/")
    require(all(p not in {"", ".", ".."} for p in parts), f"Unsafe path: {value!r}")
    return tuple(parts)


def absolute_path(value):
    return Path(os.path.abspath(os.fspath(value)))


def open_directory(path, create=False):
    """Walk from / using directory FDs: no ancestor symlink can be followed."""
    path = absolute_path(path)
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in path.parts[1:]:
            if create:
                try:
                    os.mkdir(name, 0o755, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def parent_fd(root_fd, parts, create=False):
    fd = os.dup(root_fd)
    try:
        for name in parts[:-1]:
            if create:
                try:
                    os.mkdir(name, 0o755, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def open_regular(root_fd, parts):
    fd = parent_fd(root_fd, parts)
    try:
        result = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    finally:
        os.close(fd)
    if not stat.S_ISREG(os.fstat(result).st_mode):
        os.close(result)
        raise ArchiveError(f"Not a regular file: {'/'.join(parts)}")
    return result


def signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def digest_file(fd):
    before = signature(os.fstat(fd))
    digest = hashlib.sha256()
    size = 0
    with os.fdopen(os.dup(fd), "rb") as source:
        while block := source.read(BUFFER_BYTES):
            digest.update(block)
            size += len(block)
    require(signature(os.fstat(fd)) == before, "File changed while hashing")
    return size, digest.hexdigest()


def source_inventory(roots, omitted_paths, globs):
    records, excluded = [], []

    def walk(root_index, fd, prefix, source_root, components=()):
        with os.scandir(fd) as scan:
            entries = sorted(scan, key=lambda entry: entry.name)
        for entry in entries:
            parts = components + (entry.name,)
            name = prefix + "/" + "/".join(parts)
            relative_path(name)
            info = entry.stat(follow_symlinks=False)
            require(not stat.S_ISLNK(info.st_mode), f"Source symlink refused: {name}")
            reason = None
            if source_root.joinpath(*parts) in omitted_paths:
                reason = "publication_output"
            elif stat.S_ISDIR(info.st_mode) and entry.name in EXCLUDED_DIRS:
                reason = "excluded_directory"
            elif any(fnmatch.fnmatchcase(name, pattern) for pattern in globs):
                reason = "explicit_exclusion"
            elif stat.S_ISREG(info.st_mode) and any(fnmatch.fnmatchcase(entry.name, p) for p in ARCHIVE_GLOBS):
                reason = "existing_archive"
            elif stat.S_ISSOCK(info.st_mode):
                reason = "socket"
            if reason == "publication_output":
                continue
            if reason:
                excluded.append({"path": name, "reason": reason})
            elif stat.S_ISDIR(info.st_mode):
                child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    walk(root_index, child, prefix, source_root, parts)
                finally:
                    os.close(child)
            else:
                require(stat.S_ISREG(info.st_mode), f"Special source file refused: {name}")
                records.append((name, root_index, parts, signature(info)))

    for index, (prefix, source, fd) in enumerate(roots):
        walk(index, fd, prefix, source)
    records.sort()
    validate_names([record[0] for record in records])
    return records, sorted(excluded, key=lambda item: (item["path"], item["reason"]))


def validate_names(names):
    seen = set()
    for name in sorted(names):
        parts = relative_path(name)
        require(name not in seen, f"Duplicate member: {name}")
        require(not any("/".join(parts[:i]) in seen for i in range(1, len(parts))),
                f"File/parent collision: {name}")
        seen.add(name)


class HashingReader:
    def __init__(self, source):
        self.source, self.sha256, self.bytes = source, hashlib.sha256(), 0

    def read(self, size=-1):
        value = self.source.read(size)
        self.sha256.update(value)
        self.bytes += len(value)
        return value


class ShardWriter:
    def __init__(self, directory, chunk_bytes):
        self.directory, self.chunk_bytes = directory, chunk_bytes
        self.buffer, self.parts = bytearray(), []
        self.sha256, self.bytes = hashlib.sha256(), 0

    def write(self, value):
        self.sha256.update(value)
        self.bytes += len(value)
        view = memoryview(value)
        while view:
            count = min(self.chunk_bytes - len(self.buffer), len(view))
            self.buffer.extend(view[:count])
            view = view[count:]
            if len(self.buffer) == self.chunk_bytes:
                self.finish_part()
        return len(value)

    def finish_part(self):
        if not self.buffer:
            return
        path = f"results.tar.xz.part{len(self.parts) + 1:06d}"
        blob = bytes(self.buffer)
        with (self.directory / path).open("xb") as destination:
            destination.write(blob)
        os.utime(self.directory / path, (0, 0))
        self.parts.append({"path": path, "bytes": len(blob),
                           "sha256": hashlib.sha256(blob).hexdigest(),
                           "git_blob_sha1": hashlib.sha1(f"blob {len(blob)}\0".encode() + blob).hexdigest()})
        self.buffer.clear()

    def flush(self):
        pass


def write_json(path, value):
    data = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()
    with path.open("xb") as destination:
        destination.write(data)
    os.utime(path, (0, 0))
    return hashlib.sha256(data).hexdigest()


def pack(args):
    output = absolute_path(args.output)
    require(not os.path.lexists(output), f"Output already exists: {output}")
    require(1 <= args.chunk_bytes <= 16 * 1024 * 1024, "chunk-bytes must be in [1, 16 MiB]")
    require(1 <= args.dict_mib <= 1024, "dict-mib must be in [1, 1024]")
    roots = []
    stage = None
    try:
        for mapping in args.root:
            prefix, separator, source = mapping.partition("=")
            require(separator and source, "--root requires ARCHIVE_PREFIX=SOURCE_DIRECTORY")
            relative_path(prefix)
            source = absolute_path(source)
            require(output != source and output not in source.parents, "Output cannot contain a source root")
            roots.append((prefix, source, open_directory(source)))
        roots.sort(key=lambda item: item[0])
        require(len({root[0] for root in roots}) == len(roots), "Duplicate root prefix")
        fd = open_directory(output.parent, create=True)
        os.close(fd)
        stage = Path(tempfile.mkdtemp(prefix=".hcsn-publication-", dir=output.parent))
        omitted = {output, stage}
        records, excluded = source_inventory(roots, omitted, args.exclude)
        require(records, "No regular source files selected")
        writer = ShardWriter(stage, args.chunk_bytes)
        members = []
        filters = [{"id": lzma.FILTER_LZMA2, "preset": 6, "dict_size": args.dict_mib * 1024 * 1024}]
        with lzma.LZMAFile(writer, "wb", format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC64, filters=filters) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                for name, index, parts, before in records:
                    fd = open_regular(roots[index][2], parts)
                    with os.fdopen(fd, "rb") as source:
                        require(signature(os.fstat(fd)) == before, f"Source changed before read: {name}")
                        reader = HashingReader(source)
                        info = tarfile.TarInfo(name)
                        info.size, info.mode, info.mtime = before[3], 0o644, 0
                        info.uid = info.gid = 0
                        info.uname = info.gname = ""
                        archive.addfile(info, reader)
                        require(reader.bytes == info.size and source.read(1) == b"", f"Source size changed: {name}")
                        require(signature(os.fstat(fd)) == before, f"Source changed while reading: {name}")
                        members.append({"path": name, "bytes": reader.bytes, "sha256": reader.sha256.hexdigest()})
        writer.finish_part()
        after, _ = source_inventory(roots, omitted, args.exclude)
        require(after == records, "Input inventory changed during pack; stop writers and retry")
        manifest = {"format": FORMAT, "tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "root_prefixes": [root[0] for root in roots], "excluded": excluded,
                    "compression": {"format": "xz", "filter": "LZMA2", "preset": 6,
                                    "dictionary_bytes": args.dict_mib * 1024 * 1024, "check": "CRC64"},
                    "tar": {"format": "pax", "mtime": 0, "uid": 0, "gid": 0, "mode": "0644"},
                    "chunk_bytes": args.chunk_bytes, "members": members, "parts": writer.parts,
                    "total_member_bytes": sum(member["bytes"] for member in members),
                    "archive": {"bytes": writer.bytes, "sha256": writer.sha256.hexdigest()}}
        manifest_hash = write_json(stage / "manifest.json", manifest)
        (stage / "manifest.sha256").write_text(f"{manifest_hash}  manifest.json\n", encoding="ascii")
        os.utime(stage / "manifest.sha256", (0, 0))
        require(not os.path.lexists(output), f"Output appeared during pack: {output}")
        os.rename(stage, output)
        stage = None
        return {"operation": "pack", "output": str(output), "manifest_sha256": manifest_hash,
                "members": len(members), "parts": len(writer.parts), "archive_bytes": writer.bytes,
                "source_bytes": manifest["total_member_bytes"], "tool_sha256": manifest["tool_sha256"],
                "source_roots": {prefix: str(source) for prefix, source, _ in roots}}
    finally:
        for _, _, fd in roots:
            os.close(fd)
        if stage is not None:
            shutil.rmtree(stage)


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, f"Duplicate JSON key: {key}")
        value[key] = item
    return value


def read_small(root_fd, name, limit):
    with os.fdopen(open_regular(root_fd, (name,)), "rb") as source:
        data = source.read(limit + 1)
    require(len(data) <= limit, f"Metadata too large: {name}")
    return data


def nonnegative_integer(value):
    return type(value) is int and value >= 0


def hash_value(value, length=64):
    return isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{length}}}", value) is not None


def load_manifest(bundle_fd, expected_hash=None):
    raw = read_small(bundle_fd, "manifest.json", MANIFEST_LIMIT)
    actual_hash = hashlib.sha256(raw).hexdigest()
    require(read_small(bundle_fd, "manifest.sha256", 256).decode("ascii") == f"{actual_hash}  manifest.json\n",
            "Manifest checksum mismatch")
    require(expected_hash is None or actual_hash == expected_hash, "Trusted manifest SHA256 mismatch")
    manifest = json.loads(raw, object_pairs_hook=unique_object)
    require(isinstance(manifest, dict) and manifest.get("format") == FORMAT, "Unknown manifest format")
    members, parts = manifest.get("members"), manifest.get("parts")
    require(isinstance(members, list) and members and isinstance(parts, list) and parts, "Empty/invalid manifest")
    for member in members:
        require(isinstance(member, dict), "Invalid member metadata")
        relative_path(member.get("path"))
        require(nonnegative_integer(member.get("bytes")) and hash_value(member.get("sha256")), "Invalid member digest/size")
    names = [member["path"] for member in members]
    validate_names(names)
    require(names == sorted(names), "Members must be in canonical path order")
    require(manifest.get("total_member_bytes") == sum(m["bytes"] for m in members), "Member byte total mismatch")
    chunk = manifest.get("chunk_bytes")
    require(type(chunk) is int and 1 <= chunk <= 16 * 1024 * 1024, "Invalid chunk size")
    for index, part in enumerate(parts):
        require(isinstance(part, dict) and part.get("path") == f"results.tar.xz.part{index + 1:06d}", "Invalid/duplicate/reordered part")
        require(type(part.get("bytes")) is int and 0 < part["bytes"] <= chunk, "Invalid part size")
        require(index == len(parts) - 1 or part["bytes"] == chunk, "Short non-final part")
        require(hash_value(part.get("sha256")) and hash_value(part.get("git_blob_sha1"), 40), "Invalid part digest")
    archive = manifest.get("archive")
    require(isinstance(archive, dict) and archive.get("bytes") == sum(p["bytes"] for p in parts)
            and hash_value(archive.get("sha256")), "Invalid archive digest/size")
    with os.scandir(bundle_fd) as scan:
        actual_parts = {entry.name for entry in scan if entry.name.startswith("results.tar.xz.part")}
    require(actual_parts == {part["path"] for part in parts}, "Missing or unlisted archive shard")
    return manifest, actual_hash


def assemble(bundle_fd, manifest, output):
    complete = hashlib.sha256()
    with output.open("xb") as destination:
        for part in manifest["parts"]:
            fd = open_regular(bundle_fd, (part["path"],))
            with os.fdopen(fd, "rb") as source:
                before = signature(os.fstat(fd))
                require(before[3] == part["bytes"], f"Part size mismatch: {part['path']}")
                sha256 = hashlib.sha256()
                git_sha1 = hashlib.sha1(f"blob {part['bytes']}\0".encode())
                while block := source.read(BUFFER_BYTES):
                    sha256.update(block)
                    git_sha1.update(block)
                    complete.update(block)
                    destination.write(block)
                require(signature(os.fstat(fd)) == before, "Part changed during verification")
            require(sha256.hexdigest() == part["sha256"] and git_sha1.hexdigest() == part["git_blob_sha1"],
                    f"Part hash mismatch: {part['path']}")
    require(complete.hexdigest() == manifest["archive"]["sha256"], "Combined archive hash mismatch")


def extract_verified(archive_path, manifest, stage):
    expected = {member["path"]: member for member in manifest["members"]}
    observed = set()
    with tarfile.open(archive_path, "r|xz", ignore_zeros=True) as archive:
        for info in archive:
            parts = relative_path(info.name)
            require(info.isreg() and not info.linkname and info.sparse is None, f"Non-regular tar member: {info.name}")
            require(info.name not in observed, f"Duplicate tar member: {info.name}")
            require(info.name in expected, f"Unexpected tar member: {info.name}")
            member = expected[info.name]
            require(info.size == member["bytes"], f"Tar size mismatch: {info.name}")
            require(info.mtime == 0 and info.uid == 0 and info.gid == 0 and info.mode == 0o644,
                    f"Noncanonical tar metadata: {info.name}")
            require(info.uname == info.gname == "" and set(info.pax_headers) <= {"path", "size"}, "Unexpected tar/PAX metadata")
            require("size" not in info.pax_headers or info.pax_headers["size"] == str(info.size), "Noncanonical PAX size")
            target = stage.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            digest, count = hashlib.sha256(), 0
            with archive.extractfile(info) as source, target.open("xb") as destination:
                while block := source.read(BUFFER_BYTES):
                    count += len(block)
                    require(count <= member["bytes"], f"Oversized member: {info.name}")
                    digest.update(block)
                    destination.write(block)
            require(count == member["bytes"] and digest.hexdigest() == member["sha256"], f"Member hash mismatch: {info.name}")
            os.chmod(target, 0o644)
            os.utime(target, (0, 0))
            observed.add(info.name)
    require(observed == set(expected), "Missing tar members")


def existing_matches(root_fd, member):
    try:
        fd = open_regular(root_fd, relative_path(member["path"]))
    except FileNotFoundError:
        return False
    try:
        require(digest_file(fd) == (member["bytes"], member["sha256"]),
                f"Refusing to overwrite different content: {member['path']}")
    finally:
        os.close(fd)
    return True


def restore(args):
    destination = absolute_path(args.destination)
    bundle_fd = open_directory(args.bundle)
    try:
        manifest, manifest_hash = load_manifest(bundle_fd, args.manifest_sha256)
        fd = open_directory(destination.parent, create=True)
        os.close(fd)
        with tempfile.TemporaryDirectory(prefix=".hcsn-restore-", dir=destination.parent) as temporary:
            temporary = Path(temporary)
            archive_path, stage = temporary / "results.tar.xz", temporary / "members"
            stage.mkdir()
            assemble(bundle_fd, manifest, archive_path)
            extract_verified(archive_path, manifest, stage)
            target_fd = open_directory(destination, create=True)
            stage_fd = open_directory(stage)
            try:
                existing = {m["path"] for m in manifest["members"] if existing_matches(target_fd, m)}
                for member in manifest["members"]:
                    if member["path"] in existing:
                        continue
                    parts = relative_path(member["path"])
                    fd = parent_fd(target_fd, parts, create=True)
                    try:
                        # A hard link publishes verified bytes atomically, never overwriting a path.
                        os.link(member["path"], parts[-1], src_dir_fd=stage_fd, dst_dir_fd=fd, follow_symlinks=False)
                    except FileExistsError:
                        require(existing_matches(target_fd, member), "Destination changed during restoration")
                    finally:
                        os.close(fd)
            finally:
                os.close(stage_fd)
                os.close(target_fd)
        return {"operation": "restore", "destination": str(destination), "manifest_sha256": manifest_hash,
                "verified_parts": len(manifest["parts"]), "verified_members": len(manifest["members"]),
                "verified_member_bytes": manifest["total_member_bytes"], "already_identical_members": len(existing)}
    finally:
        os.close(bundle_fd)


def main():
    require(os.name == "posix" and hasattr(os, "O_NOFOLLOW"), "POSIX directory-FD/no-follow support is required")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    packing = commands.add_parser("pack", help="Pack explicit, quiescent directory roots")
    packing.add_argument("--root", action="append", required=True, metavar="ARCHIVE_PREFIX=SOURCE_DIRECTORY")
    packing.add_argument("--output", required=True, help="New bundle directory; existing paths are refused")
    packing.add_argument("--chunk-bytes", type=int, default=CHUNK_BYTES)
    packing.add_argument("--dict-mib", type=int, default=128)
    packing.add_argument("--exclude", action="append", default=[], help="Additional archive-relative glob to omit")
    restoring = commands.add_parser("restore", help="Verify every shard and member before publishing files")
    restoring.add_argument("--bundle", required=True)
    restoring.add_argument("--destination", required=True)
    restoring.add_argument("--manifest-sha256", help="Optional SHA256 obtained from a trusted publication receipt")
    args = parser.parse_args()
    try:
        result = pack(args) if args.command == "pack" else restore(args)
    except (ArchiveError, OSError, ValueError, tarfile.TarError, lzma.LZMAError) as error:
        parser.exit(2, f"error: {error}\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
