"""Bounded, content-verified stage archives and an explicit external Library ACK.

Linux execution04 operations only. No scientific module or Library client is
imported. Remote identity is attested by the supervising root's tool receipts;
this module verifies the exact local readback bytes and all descriptor bindings.
"""

import gzip
import hashlib
import json
import os
from pathlib import Path
import stat
import tarfile
import time

MiB = 1024 ** 2
PART_PAYLOAD_LIMIT = 128 * MiB


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def write_json(path, value, replace=False):
    """Atomic publication; existing immutable receipts are never overwritten."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".writing")
    require(not path.exists() or replace, "Refusing to replace " + str(path))
    with temporary.open("xb") as stream:
        stream.write(encode(value))
        stream.flush()
        os.fsync(stream.fileno())
    if replace:
        os.replace(temporary, path)
    else:
        os.link(temporary, path)
        temporary.unlink()
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return descriptor(path)


def identity(path):
    info = Path(path).lstat()
    require(stat.S_ISREG(info.st_mode), "Nonregular or symbolic-link input: " + str(path))
    # Exact strings survive JSON clients which use IEEE-754 numbers.
    return {"device": str(info.st_dev), "inode": str(info.st_ino),
            "mtime_ns": str(info.st_mtime_ns), "ctime_ns": str(info.st_ctime_ns),
            "bytes": info.st_size}


def sha256(path, heartbeat=lambda: None):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(MiB):
            digest.update(chunk)
            heartbeat()
    return digest.hexdigest()


def descriptor(path, heartbeat=lambda: None):
    path = Path(path).absolute()
    before = identity(path)
    value = {"path": str(path), "bytes": before["bytes"], "sha256": sha256(path, heartbeat)}
    require(identity(path) == before, "Input changed while hashing: " + str(path))
    return value


def verify_descriptor(value, heartbeat=lambda: None):
    require(isinstance(value, dict) and set(("path", "bytes", "sha256")) <= set(value),
            "An artifact requires a complete path/bytes/sha256 descriptor")
    require(Path(value["path"]).is_absolute(), "Artifact path must be absolute")
    actual = descriptor(value["path"], heartbeat)
    require(all(actual[key] == value[key] for key in actual), "Artifact bytes differ: " + value["path"])
    return actual


def safe_relative(name):
    path = Path(name)
    require(name and not path.is_absolute() and ".." not in path.parts and "\\" not in name,
            "Unsafe archive logical path")
    return name


def regular_tree(directory):
    """Only callers choose closed roots; never follow a symlink directory."""
    directory = Path(directory)
    require(directory.is_dir() and not directory.is_symlink(), "Missing/linked closed directory")
    result = []
    for base, dirs, files in os.walk(directory, followlinks=False):
        for name in dirs:
            require(not (Path(base) / name).is_symlink(), "Linked archive directory")
        for name in files:
            path = Path(base) / name
            identity(path)
            result.append(path)
    return sorted(result)


class ChunkReader:
    """A tar member view; both chunk and complete logical-file hashes stream."""

    def __init__(self, stream, size, whole_hash, heartbeat):
        self.stream, self.remaining = stream, size
        self.digest, self.whole_hash, self.heartbeat = hashlib.sha256(), whole_hash, heartbeat

    def read(self, size=-1):
        size = self.remaining if size < 0 else min(size, self.remaining)
        value = self.stream.read(min(size, MiB))
        require(bool(value) or self.remaining == 0, "Archive source was truncated")
        self.remaining -= len(value)
        self.digest.update(value)
        self.whole_hash.update(value)
        self.heartbeat()
        return value


def verify_parts(manifest, directory, heartbeat=lambda: None):
    """Reconstruct every logical hash in order, without materializing a file."""
    directory = Path(directory)
    files = manifest["files"]
    require(len({safe_relative(row["path"]) for row in files}) == len(files), "Duplicate logical archive path")
    hashes = {row["path"]: hashlib.sha256() for row in files}
    offsets = {row["path"]: 0 for row in files}
    seen = []
    for part in manifest["parts"]:
        require(Path(part["name"]).name == part["name"] and part["name"], "Unsafe part filename")
        actual = descriptor(directory / part["name"], heartbeat)
        require(all(actual[k] == part["artifact"][k] for k in ("bytes", "sha256")), "Compressed archive part differs")
        expected = [(row, chunk) for row in files for chunk in row["chunks"]
                    if chunk["part"] == part["name"]]
        require(sum(chunk["bytes"] for _, chunk in expected) == part["payload_bytes"],
                "Part payload accounting differs")
        with tarfile.open(directory / part["name"], "r|gz") as archive:
            for row, chunk in expected:
                member = archive.next()
                require(member is not None and member.isfile() and member.name == chunk["member"]
                        and member.size == chunk["bytes"], "Archive member identity differs")
                require(offsets[row["path"]] == chunk["offset"], "Logical chunk order/gap differs")
                stream, digest, count = archive.extractfile(member), hashlib.sha256(), 0
                while value := stream.read(MiB):
                    digest.update(value)
                    hashes[row["path"]].update(value)
                    count += len(value)
                    heartbeat()
                require(count == chunk["bytes"] and digest.hexdigest() == chunk["sha256"],
                        "Archive chunk bytes differ")
                offsets[row["path"]] += count
                seen.append((row["path"], chunk["offset"], count))
            require(archive.next() is None, "Unexpected extra archive member")
    for row in files:
        require(offsets[row["path"]] == row["bytes"]
                and hashes[row["path"]].hexdigest() == row["sha256"],
                "Reconstructed logical file differs: " + row["path"])
    return {"verification_complete": True, "logical_files_verified": len(files),
            "logical_bytes_verified": sum(row["bytes"] for row in files),
            "chunks_verified": len(seen), "parts_verified": len(manifest["parts"]),
            "method": "independent streaming decompression and complete logical-file SHA256",
            "literal_files_written": 0, "scientific_values_interpreted": False}


def build_archive(directory, paths, binding, heartbeat=lambda: None, payload_limit=PART_PAYLOAD_LIMIT):
    """Closed paths only. A large file is split across bounded gzip/tar parts."""
    require(0 < payload_limit <= PART_PAYLOAD_LIMIT, "Invalid archive part payload bound")
    started, cpu = time.monotonic(), time.process_time()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    require(paths, "No closed artifacts selected")
    rows, plan, part, used = [], [], [], 0
    for index, (name, source) in enumerate(sorted(paths.items())):
        safe_relative(name)
        source = Path(source).absolute()
        before = identity(source)
        row = {"path": name, "source": str(source), "identity": before,
               "bytes": before["bytes"], "chunks": []}
        rows.append(row)
        offset, chunk_index = 0, 0
        while offset < before["bytes"] or chunk_index == 0:
            if used == payload_limit:
                plan.append(part)
                part, used = [], 0
            length = min(before["bytes"] - offset, payload_limit - used)
            chunk = {"member": f"payload/{index:08d}/{chunk_index:08d}",
                     "offset": offset, "bytes": length}
            row["chunks"].append(chunk)
            part.append((row, chunk))
            used += length
            offset += length
            chunk_index += 1
    if part:
        plan.append(part)
    hashes = {row["path"]: hashlib.sha256() for row in rows}
    parts = []
    for index, members in enumerate(plan):
        name = f"part-{index:04d}.tar.gz"
        output = directory / name
        with output.open("xb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0, compresslevel=1) as zipped:
                with tarfile.open(fileobj=zipped, mode="w|") as archive:
                    for row, chunk in members:
                        require(identity(row["source"]) == row["identity"], "Input changed before archive")
                        chunk["part"] = name
                        member = tarfile.TarInfo(chunk["member"])
                        member.size, member.mode, member.mtime = chunk["bytes"], 0o600, 0
                        with Path(row["source"]).open("rb") as source:
                            source.seek(chunk["offset"])
                            stream = ChunkReader(source, chunk["bytes"], hashes[row["path"]], heartbeat)
                            archive.addfile(member, stream)
                            require(stream.remaining == 0, "Incomplete archive member")
                            chunk["sha256"] = stream.digest.hexdigest()
                        require(identity(row["source"]) == row["identity"], "Input changed during archive")
            raw.flush()
            os.fsync(raw.fileno())
        parts.append({"name": name, "payload_bytes": sum(c["bytes"] for _, c in members),
                      "artifact": descriptor(output, heartbeat)})
    for row in rows:
        require(identity(row["source"]) == row["identity"], "Input changed after archive")
        row["sha256"] = hashes[row["path"]].hexdigest()
    manifest = {"schema": "hepta.fullstudy.durable-archive-manifest.1", "binding": binding,
                "part_payload_limit_bytes": payload_limit, "files": rows, "parts": parts,
                "logical_files": len(rows), "logical_bytes": sum(row["bytes"] for row in rows),
                "format": "gzip tar parts with ordered per-file chunks; preserve by concatenation",
                "scientific_values_interpreted": False, "external_uploads_performed_here": 0}
    verification = {"schema": "hepta.fullstudy.durable-archive-verification.1", "binding": binding,
                    **verify_parts(manifest, directory, heartbeat)}
    manifest_desc = write_json(directory / "MANIFEST.json", manifest)
    verification["manifest"] = manifest_desc
    verification_desc = write_json(directory / "VERIFIED.json", verification)
    cost = {"schema": "hepta.fullstudy.durable-archive-cost.1", "binding": binding,
            "wall_seconds": time.monotonic() - started, "cpu_seconds": time.process_time() - cpu,
            "physical_archive_bytes": sum(row["artifact"]["bytes"] for row in parts),
            "logical_bytes_processed": manifest["logical_bytes"],
            "measurement_scope": "archive construction, compressed hashes, independent stream verification and manifest writes; excludes this receipt write",
            "nested_in_supervisor_self_cpu_do_not_add_again": True}
    cost_desc = write_json(directory / "ARCHIVE_COST.json", cost)
    items = [row["artifact"] for row in parts] + [manifest_desc, verification_desc, cost_desc]
    request = {"schema": "hepta.fullstudy.library-archive-request.1", "binding": binding,
               "state": "AWAITING_EXTERNAL_UPLOAD_AND_REMOTE_READBACK", "items": items,
               "manifest": manifest_desc, "archive_verification": verification_desc,
               "upload_execution": "external root; no implicit retries after unknown outcome",
               "required_ack_schema": "hepta.fullstudy.library-archive-ack.1"}
    return write_json(directory / "REQUEST.json", request)


def verify_ack(ack_path, request_descriptor, heartbeat=lambda: None):
    """Missing ACK waits; present but invalid/uncertain ACK fails closed."""
    verify_descriptor(request_descriptor, heartbeat)
    request = read(request_descriptor["path"])
    ack = read(ack_path)
    require(ack.get("schema") == request["required_ack_schema"]
            and ack.get("status") == "VERIFIED_REMOTE_READBACK"
            and ack.get("unknown_upload_outcome") is False
            and ack.get("request") == request_descriptor
            and ack.get("binding") == request["binding"], "ACK identity or outcome is not verified")
    items = ack.get("items", [])
    require(len(items) == len(request["items"]), "ACK must cover every ordered upload item")
    remote_ids = set()
    for expected, item in zip(request["items"], items):
        require(item.get("local") == expected and item.get("upload_item_success") is True
                and item.get("remote_readback_performed") is True, "Upload item is not fully verified")
        remote = item.get("remote_identity", {})
        remote_id = remote.get("library_file_id")
        require(isinstance(remote_id, str) and bool(remote_id) and remote_id not in remote_ids
                and item.get("readback_remote_identity") == remote,
                "Remote readback identity differs or is duplicated")
        remote_ids.add(remote_id)
        verify_descriptor(item["upload_receipt"], heartbeat)
        verify_descriptor(item["readback_receipt"], heartbeat)
        actual = verify_descriptor(item["readback"], heartbeat)
        require(actual["bytes"] == expected["bytes"] and actual["sha256"] == expected["sha256"],
                "Actual remote readback bytes do not match uploaded artifact")
        require(Path(actual["path"]).resolve() != Path(expected["path"]).resolve()
                and (os.stat(actual["path"]).st_dev, os.stat(actual["path"]).st_ino)
                != (os.stat(expected["path"]).st_dev, os.stat(expected["path"]).st_ino),
                "Readback must be a distinct materialized file, not the source or a hardlink")
    return {"ack": descriptor(ack_path, heartbeat), "request": request_descriptor, "binding": request["binding"],
            "items_verified": len(items), "remote_library_file_ids": sorted(remote_ids),
            "remote_identity_trust_boundary": "external root tool receipts; no service authentication by this stdlib verifier",
            "readback_bytes_verified_here": True}
