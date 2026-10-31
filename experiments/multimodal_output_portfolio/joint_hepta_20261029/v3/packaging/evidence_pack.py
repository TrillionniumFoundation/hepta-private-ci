"""Deterministic tar.xz evidence bundles with bounded, verified transport chunks.

No tarfile.extract APIs are used. All source bytes, relative paths, empty
directories and ordinary permission bits are preserved. Owner IDs and times
are canonicalized, not presented as a filesystem-metadata backup.
"""

import argparse
import hashlib
import io
import json
import lzma
import os
from pathlib import Path
import re
import shutil
import stat
import tarfile
import time
import unicodedata


CHUNK_BYTES = 384 * 1024
PAGE_ENTRIES = 128
MANIFEST_LIMIT = 64 * 1024 * 1024
MANIFEST_NAME = ".evidence-manifest.json"
SCHEMA = "hepta.lossless-evidence.v1"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def strict_json(data):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate JSON metadata key")
            value[key] = item
        return value
    return json.loads(data, object_pairs_hook=unique)


def safe_relative(value):
    if not isinstance(value, str) or not value or len(value) > 4096 or "\\" in value:
        raise ValueError("Unsafe relative path")
    parts = value.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if any(part in {"", ".", ".."} or ":" in part or part.endswith((" ", "."))
           or any(ord(c) < 32 for c in part) or part.split(".")[0].upper() in reserved for part in parts):
        raise ValueError("Unsafe relative path: " + value)
    return parts


def checked_directory(path):
    """Reject symlinks in every existing component of an explicit local path."""
    path = Path(os.path.abspath(path))
    for part in reversed((path, *path.parents)):
        if part.is_symlink():
            raise ValueError("Symlink directory component: " + str(part))
    if not path.is_dir():
        raise ValueError("Expected existing directory: " + str(path))
    return path


def open_regular(path):
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    if Path(path).is_symlink():
        raise ValueError("Symlink file: " + str(path))
    descriptor = os.open(path, flags)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError("Expected regular file: " + str(path))
    return os.fdopen(descriptor, "rb")


def signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def scan(source, with_hashes):
    entries, identities, normalized = [], {}, set()
    identities[""] = signature(source.stat())
    def fail_on_walk_error(error):
        raise error
    for directory, names, files in os.walk(source, followlinks=False, onerror=fail_on_walk_error):
        for name in sorted(names + files):
            path = Path(directory) / name
            relative = path.relative_to(source).as_posix()
            safe_relative(relative)
            canonical = unicodedata.normalize("NFC", relative).casefold()
            if canonical in normalized:
                raise ValueError("Duplicate or nonportable case-colliding path: " + relative)
            normalized.add(canonical)
            info = path.lstat()
            identities[relative] = signature(info)
            mode = stat.S_IMODE(info.st_mode)
            if mode & ~0o777:
                raise ValueError("Special permission bits are not accepted")
            if stat.S_ISDIR(info.st_mode):
                entries.append({"path": relative, "type": "directory", "size": 0, "mode": mode})
            elif stat.S_ISREG(info.st_mode):
                entry = {"path": relative, "type": "file", "size": info.st_size, "mode": mode}
                if with_hashes:
                    value = hashlib.sha256()
                    with open_regular(path) as handle:
                        if signature(os.fstat(handle.fileno())) != identities[relative]:
                            raise ValueError("Source changed before hashing: " + relative)
                        for block in iter(lambda: handle.read(1024 * 1024), b""):
                            value.update(block)
                        if signature(os.fstat(handle.fileno())) != identities[relative]:
                            raise ValueError("Source changed during hashing: " + relative)
                    entry["sha256"] = value.hexdigest()
                entries.append(entry)
            else:
                raise ValueError("Symlinks and special source files are forbidden: " + relative)
    return sorted(entries, key=lambda item: item["path"]), identities


def write_new(path, data):
    with Path(path).open("xb") as handle:
        handle.write(data)


class ChunkWriter:
    def __init__(self, output):
        self.output, self.buffer, self.records = output, bytearray(), []
        self.hasher, self.size = hashlib.sha256(), 0

    def write(self, data):
        self.hasher.update(data)
        self.size += len(data)
        view = memoryview(data)
        while view:
            take = min(CHUNK_BYTES - len(self.buffer), len(view))
            self.buffer.extend(view[:take])
            view = view[take:]
            if len(self.buffer) == CHUNK_BYTES:
                self.emit()
        return len(data)

    def emit(self):
        if not self.buffer:
            return
        name = f"archive.part-{len(self.records):06d}.bin"
        data = bytes(self.buffer)
        write_new(self.output / name, data)
        self.records.append({"path": name, "size": len(data), "sha256": digest(data),
                             "offset": len(self.records) * CHUNK_BYTES})
        self.buffer.clear()

    def flush(self):
        pass


class HashingReader:
    def __init__(self, handle):
        self.handle, self.hasher = handle, hashlib.sha256()

    def read(self, size=-1):
        data = self.handle.read(size)
        self.hasher.update(data)
        return data


def tar_info(name, entry):
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE if entry["type"] == "directory" else tarfile.REGTYPE
    info.size, info.mode = entry["size"], entry["mode"]
    info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
    return info


def pack(source, output, preset=6):
    started, cpu = time.perf_counter(), time.process_time()
    source, output = checked_directory(source), Path(os.path.abspath(output))
    checked_directory(output.parent)
    if source == output or source in output.parents:
        raise ValueError("Bundle must be outside the source tree")
    if os.path.lexists(output):
        raise FileExistsError("Refusing to overwrite bundle")
    if preset not in range(10):
        raise ValueError("XZ preset must be 0 through 9")
    entries, before = scan(source, True)
    manifest = {"schema": SCHEMA, "root_name": source.name,
                "root_mode": stat.S_IMODE(source.stat().st_mode), "entries": entries}
    if manifest["root_mode"] & ~0o777:
        raise ValueError("Special root permission bits are forbidden")
    manifest_data = json_bytes(manifest)
    if len(manifest_data) > MANIFEST_LIMIT:
        raise ValueError("Manifest exceeds the explicit memory bound")
    output.mkdir(mode=0o700)
    writer = ChunkWriter(output)
    with lzma.LZMAFile(writer, "wb", format=lzma.FORMAT_XZ, preset=preset) as compressed:
        with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
            archive.addfile(tar_info(MANIFEST_NAME, {"type": "file", "size": len(manifest_data), "mode": 0o644}),
                            io.BytesIO(manifest_data))
            archive.addfile(tar_info("payload", {"type": "directory", "size": 0, "mode": manifest["root_mode"]}))
            # Keep repeated parameter payloads within the XZ dictionary instead
            # of separating them by thousands of small episode artifacts.
            parameter_suffixes = {".pt", ".pth", ".safetensors", ".npz", ".npy"}
            def archive_order(entry):
                if entry["type"] == "directory":
                    return (0, entry["path"].count("/"), entry["path"])
                suffix = Path(entry["path"]).suffix
                if suffix in parameter_suffixes:
                    # Path order keeps each experiment cell/core and its
                    # pretrained/frozen/joint weights adjacent. Large array
                    # dumps follow model checkpoints instead of splitting them.
                    return (1, int(suffix in {".npz", ".npy"}), entry["path"])
                return (2, 0, entry["path"])
            for number, entry in enumerate(sorted(entries, key=archive_order)):
                info = tar_info("payload/" + entry["path"], entry)
                if entry["type"] == "directory":
                    archive.addfile(info)
                else:
                    with open_regular(source / entry["path"]) as handle:
                        if signature(os.fstat(handle.fileno())) != before[entry["path"]]:
                            raise ValueError("Source changed before compression")
                        reader = HashingReader(handle)
                        archive.addfile(info, reader)
                        if reader.hasher.hexdigest() != entry["sha256"] or signature(os.fstat(handle.fileno())) != before[entry["path"]]:
                            raise ValueError("Source changed while compressing: " + entry["path"])
                if number and number % 2000 == 0:
                    print(json.dumps({"packed_members": number, "compressed_bytes_so_far": writer.size}), flush=True)
    writer.emit()
    _, after = scan(source, False)
    if before != after:
        raise ValueError("Source tree changed; partial chunks have no valid INDEX")
    pages = []
    for number, offset in enumerate(range(0, len(writer.records), PAGE_ENTRIES)):
        name = f"CHUNKS-{number:06d}.json"
        records = writer.records[offset:offset + PAGE_ENTRIES]
        data = json_bytes({"schema": SCHEMA, "chunks": records})
        if len(data) > CHUNK_BYTES:
            raise ValueError("Chunk page exceeds publication bound")
        write_new(output / name, data)
        pages.append({"path": name, "size": len(data), "sha256": digest(data), "count": len(records)})
    index = {"schema": SCHEMA, "format": "tar.xz", "xz_preset": preset, "chunk_bytes": CHUNK_BYTES,
             "archive_order": "directories-then-parameter-types-by-path-then-path.v1",
             "chunk_pages": pages, "chunk_count": len(writer.records), "archive_bytes": writer.size,
             "archive_sha256": writer.hasher.hexdigest(),
             "manifest": {"path": MANIFEST_NAME, "size": len(manifest_data), "sha256": digest(manifest_data)},
             "root_name": source.name, "file_count": sum(e["type"] == "file" for e in entries),
             "directory_count": sum(e["type"] == "directory" for e in entries),
             "file_bytes": sum(e["size"] for e in entries), "member_count": len(entries) + 2,
             "metadata_policy": "exact bytes/paths/permission bits; canonical uid/gid/names/mtime"}
    data = json_bytes(index)
    if len(data) > CHUNK_BYTES:
        raise ValueError("Root index exceeds publication bound; use smaller source groups")
    write_new(output / "INDEX.json", data)
    verified = verify(output, expected_index_sha256=digest(data))
    report = {**verified, "source_tree_unchanged_after_full_walk": True,
              "wall_seconds": time.perf_counter() - started, "cpu_seconds": time.process_time() - cpu,
              "source_file_bytes_read_for_hash_and_pack": 2 * index["file_bytes"],
              "compressed_bytes_written": writer.size, "verification_decompressed_file_bytes": index["file_bytes"]}
    write_new(output / "PACK_REPORT.json", json_bytes(report))
    return report


def read_bounded(path, maximum):
    with open_regular(path) as handle:
        data = handle.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("Metadata exceeds explicit size bound")
    return data


def load_index(bundle, expected_index_sha256=None):
    bundle = checked_directory(bundle)
    raw = read_bounded(bundle / "INDEX.json", CHUNK_BYTES)
    if expected_index_sha256 is not None and digest(raw) != expected_index_sha256:
        raise ValueError("Trusted root INDEX digest mismatch")
    index, chunks = strict_json(raw), []
    if index["schema"] != SCHEMA or index["format"] != "tar.xz" or index["chunk_bytes"] != CHUNK_BYTES:
        raise ValueError("Unsupported evidence format")
    for number, page in enumerate(index["chunk_pages"]):
        if page["path"] != f"CHUNKS-{number:06d}.json":
            raise ValueError("Unsafe or duplicate chunk-page path")
        data = read_bounded(bundle / page["path"], CHUNK_BYTES)
        if len(data) != page["size"] or digest(data) != page["sha256"]:
            raise ValueError("Chunk-page integrity mismatch")
        value = strict_json(data)
        if value["schema"] != SCHEMA or len(value["chunks"]) != page["count"] or not 1 <= page["count"] <= PAGE_ENTRIES:
            raise ValueError("Invalid chunk page")
        chunks.extend(value["chunks"])
    if len(chunks) != index["chunk_count"] or not chunks:
        raise ValueError("Incomplete chunk index")
    archive_hash, total = hashlib.sha256(), 0
    for number, chunk in enumerate(chunks):
        if chunk["path"] != f"archive.part-{number:06d}.bin" or chunk["offset"] != total:
            raise ValueError("Unsafe, duplicate, or misordered chunk path")
        if not 1 <= chunk["size"] <= CHUNK_BYTES or (number < len(chunks) - 1 and chunk["size"] != CHUNK_BYTES):
            raise ValueError("Chunk exceeds bound or has an invalid boundary")
        data = read_bounded(bundle / chunk["path"], CHUNK_BYTES)
        if len(data) != chunk["size"] or digest(data) != chunk["sha256"]:
            raise ValueError("Chunk integrity mismatch: " + chunk["path"])
        archive_hash.update(data)
        total += len(data)
    if total != index["archive_bytes"] or archive_hash.hexdigest() != index["archive_sha256"]:
        raise ValueError("Complete archive integrity mismatch")
    return bundle, index, chunks, digest(raw)


class ChunkReader(io.RawIOBase):
    def __init__(self, bundle, chunks):
        super().__init__()
        self.bundle, self.chunks, self.number, self.handle = bundle, chunks, 0, None

    def readable(self):
        return True

    def readinto(self, buffer):
        while self.number < len(self.chunks):
            if self.handle is None:
                self.handle = open_regular(self.bundle / self.chunks[self.number]["path"])
            count = self.handle.readinto(buffer)
            if count:
                return count
            self.handle.close()
            self.handle = None
            self.number += 1
        return 0

    def close(self):
        if self.handle is not None:
            self.handle.close()
        super().close()


def validated_manifest(data, index):
    if len(data) != index["manifest"]["size"] or digest(data) != index["manifest"]["sha256"]:
        raise ValueError("Embedded file manifest integrity mismatch")
    manifest = strict_json(data)
    if manifest["schema"] != SCHEMA or manifest["root_name"] != index["root_name"]:
        raise ValueError("Manifest identity mismatch")
    if len(safe_relative(manifest["root_name"])) != 1 or manifest["root_mode"] & ~0o777:
        raise ValueError("Unsafe root metadata")
    expected, normalized = {}, set()
    for entry in manifest["entries"]:
        path = entry["path"]
        safe_relative(path)
        canonical = unicodedata.normalize("NFC", path).casefold()
        if path in expected or canonical in normalized:
            raise ValueError("Duplicate manifest path")
        normalized.add(canonical)
        if entry["type"] not in {"file", "directory"} or type(entry["mode"]) is not int or entry["mode"] & ~0o777:
            raise ValueError("Unsafe member type or mode")
        if type(entry["size"]) is not int or entry["size"] < 0:
            raise ValueError("Invalid member size")
        if entry["type"] == "directory" and entry["size"] != 0:
            raise ValueError("Nonempty directory member")
        if entry["type"] == "file" and not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise ValueError("Invalid file hash")
        expected[path] = entry
    for path in expected:
        parent = path.rpartition("/")[0]
        if parent and (parent not in expected or expected[parent]["type"] != "directory"):
            raise ValueError("Missing or nondirectory parent")
    if (sum(e["type"] == "file" for e in expected.values()) != index["file_count"]
            or sum(e["type"] == "directory" for e in expected.values()) != index["directory_count"]
            or sum(e["size"] for e in expected.values()) != index["file_bytes"]
            or len(expected) + 2 != index["member_count"]):
        raise ValueError("Manifest totals disagree with index")
    return manifest, expected


def process_archive(bundle, index, chunks, destination=None):
    if index["manifest"]["path"] != MANIFEST_NAME or not 1 <= index["manifest"]["size"] <= MANIFEST_LIMIT:
        raise ValueError("Unsafe embedded manifest declaration")
    with ChunkReader(bundle, chunks) as raw, io.BufferedReader(raw) as buffered:
        with lzma.LZMAFile(buffered, "rb") as compressed:
            with tarfile.open(fileobj=compressed, mode="r|", ignore_zeros=True) as archive:
                first = archive.next()
                if first is None or first.name != MANIFEST_NAME or not first.isreg() or first.linkname or first.size != index["manifest"]["size"]:
                    raise ValueError("Archive must start with its bounded regular manifest")
                manifest, expected = validated_manifest(archive.extractfile(first).read(MANIFEST_LIMIT + 1), index)
                root = archive.next()
                if root is None or root.name.rstrip("/") != "payload" or not root.isdir() or root.linkname:
                    raise ValueError("Missing plain payload root")
                seen = set()
                while (member := archive.next()) is not None:
                    if not member.name.startswith("payload/") or member.linkname or not (member.isreg() or member.isdir()):
                        raise ValueError("Links, special files and unexpected archive paths are forbidden")
                    relative = member.name[len("payload/"):].rstrip("/") if member.isdir() else member.name[len("payload/"):]
                    safe_relative(relative)
                    if relative in seen or relative not in expected:
                        raise ValueError("Duplicate or unexpected archive member")
                    seen.add(relative)
                    entry = expected[relative]
                    if member.size != entry["size"] or member.mode != entry["mode"] or member.isdir() != (entry["type"] == "directory"):
                        raise ValueError("Archive member metadata disagrees with manifest")
                    target = None if destination is None else destination.joinpath(*safe_relative(relative))
                    if member.isdir():
                        if target is not None:
                            target.mkdir(mode=0o700)
                    else:
                        hasher, size = hashlib.sha256(), 0
                        source = archive.extractfile(member)
                        handle = None if target is None else target.open("xb")
                        try:
                            for block in iter(lambda: source.read(1024 * 1024), b""):
                                size += len(block)
                                hasher.update(block)
                                if handle is not None:
                                    handle.write(block)
                        finally:
                            if handle is not None:
                                handle.close()
                            source.close()
                        if size != entry["size"] or hasher.hexdigest() != entry["sha256"]:
                            raise ValueError("Restored file bytes disagree with manifest: " + relative)
                if seen != set(expected):
                    raise ValueError("Archive omits manifest members")
    if destination is not None:
        for entry in sorted(expected.values(), key=lambda e: e["path"].count("/"), reverse=True):
            os.chmod(destination / entry["path"], entry["mode"])
        os.chmod(destination, manifest["root_mode"])
    return {"file_count": index["file_count"], "directory_count": index["directory_count"],
            "file_bytes": index["file_bytes"], "archive_bytes": index["archive_bytes"],
            "archive_sha256": index["archive_sha256"], "manifest_sha256": index["manifest"]["sha256"],
            "chunk_count": len(chunks), "all_file_bytes_verified": True}


def verify(bundle, expected_index_sha256=None):
    bundle, index, chunks, index_sha = load_index(bundle, expected_index_sha256)
    return {**process_archive(bundle, index, chunks), "index_sha256": index_sha}


def unpack(bundle, destination, expected_index_sha256=None):
    started, cpu = time.perf_counter(), time.process_time()
    destination = Path(os.path.abspath(destination))
    checked_directory(destination.parent)
    if os.path.lexists(destination):
        raise FileExistsError("Refusing to overwrite any existing destination")
    bundle, index, chunks, index_sha = load_index(bundle, expected_index_sha256)
    destination.mkdir(mode=0o700)
    try:
        report = process_archive(bundle, index, chunks, destination)
    except BaseException:
        shutil.rmtree(destination)
        raise
    return {**report, "index_sha256": index_sha,
            "wall_seconds": time.perf_counter() - started, "cpu_seconds": time.process_time() - cpu,
            "restored_bytes_written": index["file_bytes"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("pack", "verify", "unpack"))
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path, nargs="?")
    parser.add_argument("--expected-index-sha256")
    parser.add_argument("--preset", type=int, default=6)
    args = parser.parse_args()
    if args.operation == "pack":
        result = pack(args.source, args.destination, args.preset)
    elif args.operation == "unpack":
        result = unpack(args.source, args.destination, args.expected_index_sha256)
    else:
        result = verify(args.source, args.expected_index_sha256)
    print(json.dumps(result, indent=2), flush=True)
