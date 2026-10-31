"""Deterministic USTAR/gzip evidence bundle, binary parts, and bounded restoration.

Only regular files and directories are supported. Unpack verifies every part,
the complete compressed archive, and every member before publishing files.
It never calls tarfile.extract or extractall and never follows archive links.
The caller must exclusively control the destination during restoration. This
is not a sandbox against concurrent adversarial filesystem changes.
"""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import tarfile
import tempfile


PART_BYTES = 512 * 1024
SCHEMA = "hepta.analytic-event.round7.evidence-bundle.v1"
MANIFEST_NAME = "BUNDLE_MANIFEST.json"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
HISTORICAL_NATIVE_SHA256 = "b519cae26325f818d9596aab34504490a0b5355b9eb633369878e6f07a50e179"


@dataclass(frozen=True)
class Limits:
    max_archive_bytes: int = 2 * 1024**3
    max_unpacked_bytes: int = 4 * 1024**3
    max_member_bytes: int = 1024**3
    max_members: int = 50000
    max_manifest_bytes: int = 32 * 1024**2


def _safe_name(name):
    if not isinstance(name, str) or not name or "\\" in name or "\0" in name:
        raise ValueError("empty or nonportable member path")
    path = PurePosixPath(name)
    if (path.is_absolute() or PureWindowsPath(name).drive or ".." in path.parts
            or str(path) != name or name == "."):
        raise ValueError("absolute, traversal, or noncanonical member path")
    return path


def _hex_digest(value):
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("invalid SHA256")
    try:
        decoded = bytes.fromhex(value)
    except ValueError as error:
        raise ValueError("invalid SHA256") from error
    if len(decoded) != 32 or value != value.lower():
        raise ValueError("SHA256 must be canonical lower-case hexadecimal")


def _integer(value, minimum, maximum, name):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} outside its declared size bound")


def _open_regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    stream = os.fdopen(fd, "rb")
    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
        stream.close()
        raise ValueError("evidence/part inputs must be regular files")
    return stream


def _file_digest(path, max_bytes=1024**3):
    result, size = hashlib.sha256(), 0
    with _open_regular(path) as stream:
        if os.fstat(stream.fileno()).st_size > max_bytes:
            raise ValueError("file exceeds configured digest bound")
        while block := stream.read(1024 * 1024):
            result.update(block)
            size += len(block)
            if size > max_bytes:
                raise ValueError("file grew beyond configured digest bound")
    return size, result.hexdigest()


class _PartWriter:
    def __init__(self, output, limit):
        self.output, self.limit = output, limit
        self.parts, self.stream, self.part_hash = [], None, None
        self.part_size, self.size = 0, 0
        self.archive_hash = hashlib.sha256()

    def write(self, data):
        view = memoryview(data)
        if self.size + len(view) > self.limit:
            raise ValueError("compressed archive exceeds configured bound")
        self.archive_hash.update(view)
        self.size += len(view)
        offset = 0
        while offset < len(view):
            if self.stream is None:
                self.name = f"part-{len(self.parts):05d}.bin"
                self.stream = (self.output / self.name).open("xb")
                self.part_hash, self.part_size = hashlib.sha256(), 0
            end = min(len(view), offset + PART_BYTES - self.part_size)
            block = view[offset:end]
            self.stream.write(block)
            self.part_hash.update(block)
            self.part_size += len(block)
            offset = end
            if self.part_size == PART_BYTES:
                self._close_part()
        return len(view)

    def flush(self):
        if self.stream is not None:
            self.stream.flush()

    def _close_part(self):
        if self.stream is not None:
            self.stream.close()
            self.parts.append({"name": self.name, "bytes": self.part_size,
                               "sha256": self.part_hash.hexdigest()})
            self.stream = None

    def finish(self):
        self._close_part()
        return self.parts, self.size, self.archive_hash.hexdigest()

    def abort(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


class _HashReader:
    def __init__(self, stream):
        self.stream, self.digest, self.size = stream, hashlib.sha256(), 0

    def read(self, size):
        data = self.stream.read(size)
        self.digest.update(data)
        self.size += len(data)
        return data


def _inventory(source, output, limits):
    members, unpacked = [], 0
    for current, directories, files in os.walk(source, followlinks=False):
        parent = Path(current)
        kept = []
        for name in sorted(directories):
            path = parent / name
            if name == "__pycache__" or path.resolve() == output:
                continue
            if path.is_symlink():
                raise ValueError("evidence contains a directory symlink")
            kept.append(name)
            members.append({"path": path.relative_to(source).as_posix(), "kind": "directory",
                            "bytes": 0, "sha256": EMPTY_SHA256,
                            "mode": stat.S_IMODE(path.stat().st_mode) & 0o777})
        directories[:] = kept
        for name in sorted(files):
            path = parent / name
            if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError("evidence contains a link or special file")
            size, digest = _file_digest(path, limits.max_member_bytes)
            if size > limits.max_member_bytes:
                raise ValueError("evidence member exceeds configured bound")
            unpacked += size
            if unpacked > limits.max_unpacked_bytes:
                raise ValueError("evidence exceeds configured total bound")
            members.append({"path": path.relative_to(source).as_posix(), "kind": "file",
                            "bytes": size, "sha256": digest,
                            "mode": stat.S_IMODE(path.stat().st_mode) & 0o777})
        if len(members) > limits.max_members:
            raise ValueError("too many evidence members")
    members.sort(key=lambda row: row["path"])
    for member in members:
        _safe_name(member["path"])
        if member["path"] == "native_reuse/analytic_event" and member["sha256"] != HISTORICAL_NATIVE_SHA256:
            raise ValueError("historical native executable differs from its pinned identity")
    return members, unpacked


def pack(source, output, limits=Limits()):
    source, output = Path(source), Path(output)
    if source.is_symlink() or not source.is_dir():
        raise ValueError("source must be a real directory")
    source, output = source.resolve(), output.resolve()
    if output == source or source.is_relative_to(output):
        raise ValueError("bundle output cannot replace or contain the evidence source")
    output.mkdir(parents=True, exist_ok=False)
    writer = _PartWriter(output, limits.max_archive_bytes)
    try:
        members, unpacked = _inventory(source, output, limits)
        with gzip.GzipFile(filename="", mode="wb", fileobj=writer, mtime=0, compresslevel=6) as compressed:
            with tarfile.open(mode="w|", fileobj=compressed, format=tarfile.USTAR_FORMAT,
                              encoding="utf-8", errors="strict") as archive:
                for member in members:
                    info = tarfile.TarInfo(member["path"])
                    info.size, info.mode = member["bytes"], member["mode"]
                    info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
                    if member["kind"] == "directory":
                        info.type = tarfile.DIRTYPE
                        archive.addfile(info)
                    else:
                        with _open_regular(source / member["path"]) as stream:
                            reader = _HashReader(stream)
                            archive.addfile(info, reader)
                            if (reader.size != member["bytes"] or stream.read(1)
                                    or reader.digest.hexdigest() != member["sha256"]):
                                raise ValueError("evidence changed while the bundle was being written")
        parts, archive_bytes, digest = writer.finish()
        manifest = {
            "schema": SCHEMA, "archive_format": "ustar+gzip", "part_bytes": PART_BYTES,
            "archive_bytes": archive_bytes, "archive_sha256": digest,
            "member_count": len(members), "unpacked_file_bytes": unpacked,
            "parts": parts, "members": members,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "excluded": ["every __pycache__ directory", "this bundle output directory if nested within source"],
            "retention": "All other development failures, superseded fits, final fits, confirmation records, broker artifacts, and native traces present in the source are retained.",
            "historical_native": {"path": "native_reuse/analytic_event", "sha256": HISTORICAL_NATIVE_SHA256,
                                  "fresh_compile_claim": False,
                                  "scope": "If present, this is the reused historical binary with its original build and restoration receipts, included for complete offline evidence replay."},
        }
        (output / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        return manifest
    except Exception as error:
        writer.abort()
        (output / "BUNDLE_FAILURE.json").write_text(json.dumps({
            "status": "failed", "error_type": type(error).__name__, "error": str(error),
            "partial_parts_retained": True}, indent=2) + "\n")
        raise


def _manifest(bundle, limits):
    path = bundle / MANIFEST_NAME
    with _open_regular(path) as stream:
        data = stream.read(limits.max_manifest_bytes + 1)
    if len(data) > limits.max_manifest_bytes:
        raise ValueError("manifest exceeds configured bound")
    result = json.loads(data)
    if result.get("schema") != SCHEMA or result.get("archive_format") != "ustar+gzip":
        raise ValueError("unsupported evidence bundle format")
    if result.get("part_bytes") != PART_BYTES:
        raise ValueError("expected fixed 512 KiB binary parts")
    _integer(result["archive_bytes"], 1, limits.max_archive_bytes, "archive bytes")
    _hex_digest(result["archive_sha256"])
    members, parts = result["members"], result["parts"]
    if not isinstance(members, list) or len(members) > limits.max_members:
        raise ValueError("invalid member count")
    if result["member_count"] != len(members):
        raise ValueError("member count mismatch")
    expected, total = {}, 0
    for member in members:
        name = str(_safe_name(member["path"]))
        if name in expected or member["kind"] not in ("file", "directory"):
            raise ValueError("duplicate or unsupported member")
        _integer(member["bytes"], 0, limits.max_member_bytes, "member bytes")
        _integer(member["mode"], 0, 0o777, "member mode")
        _hex_digest(member["sha256"])
        if member["kind"] == "directory" and (member["bytes"] or member["sha256"] != EMPTY_SHA256):
            raise ValueError("directory cannot carry data")
        total += member["bytes"]
        expected[name] = member
    if total > limits.max_unpacked_bytes or total != result["unpacked_file_bytes"]:
        raise ValueError("unpacked total outside its declared bound")
    for name in expected:
        for parent in PurePosixPath(name).parents:
            if str(parent) != "." and (str(parent) not in expected or expected[str(parent)]["kind"] != "directory"):
                raise ValueError("every member parent must be an explicit directory")
    max_parts = (limits.max_archive_bytes + PART_BYTES - 1) // PART_BYTES
    if not isinstance(parts, list) or not 1 <= len(parts) <= max_parts:
        raise ValueError("invalid part count")
    for index, part in enumerate(parts):
        if part["name"] != f"part-{index:05d}.bin":
            raise ValueError("noncanonical part identity")
        _integer(part["bytes"], 1, PART_BYTES, "part bytes")
        if index + 1 < len(parts) and part["bytes"] != PART_BYTES:
            raise ValueError("only the last part may be short")
        _hex_digest(part["sha256"])
    if sum(p["bytes"] for p in parts) != result["archive_bytes"]:
        raise ValueError("part/archive byte count mismatch")
    return result, expected, hashlib.sha256(data).hexdigest()


def _existing_matches(output, expected):
    if output.is_symlink() or (output.exists() and not output.is_dir()):
        raise ValueError("restore target must be absent or a real matching directory")
    if not output.exists():
        return
    for current, directories, files in os.walk(output, followlinks=False):
        for name in directories + files:
            path = Path(current) / name
            relative = path.relative_to(output).as_posix()
            record = expected.get(relative)
            if path.is_symlink() or record is None:
                raise ValueError("existing restore target contains a link or unexpected member")
            if record["kind"] == "directory":
                if not path.is_dir():
                    raise ValueError("existing target member type differs")
            else:
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError("existing target files must be regular with no hard links")
                if (info.st_size != record["bytes"]
                        or _file_digest(path, record["bytes"]) != (record["bytes"], record["sha256"])):
                    raise ValueError("existing target bytes differ; no files were overwritten")


def unpack(bundle, output, limits=Limits()):
    bundle, output = Path(bundle).resolve(), Path(output)
    if output.is_symlink():
        raise ValueError("restore target cannot be a symlink")
    output = output.absolute()
    manifest, expected, manifest_sha = _manifest(bundle, limits)
    _existing_matches(output, expected)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=output.parent) as compressed:
        archive_hash = hashlib.sha256()
        for part in manifest["parts"]:
            digest, count = hashlib.sha256(), 0
            with _open_regular(bundle / part["name"]) as stream:
                while block := stream.read(1024 * 1024):
                    count += len(block)
                    if count > part["bytes"]:
                        raise ValueError("part exceeds its declared length")
                    digest.update(block)
                    archive_hash.update(block)
                    compressed.write(block)
            if count != part["bytes"] or digest.hexdigest() != part["sha256"]:
                raise ValueError("part checksum/length mismatch")
        if archive_hash.hexdigest() != manifest["archive_sha256"]:
            raise ValueError("archive checksum mismatch")
        compressed.seek(0)
        with tempfile.TemporaryDirectory(prefix="hepta-bundle-stage-", dir=output.parent) as directory:
            stage, seen, tar_bytes = Path(directory), set(), 0
            max_tar = limits.max_unpacked_bytes + limits.max_members * 1024 + 10240
            with gzip.GzipFile(fileobj=compressed, mode="rb") as archive:
                def read_exact(size):
                    nonlocal tar_bytes
                    if tar_bytes + size > max_tar:
                        raise ValueError("decompressed tar exceeds configured bound")
                    data = archive.read(size)
                    tar_bytes += len(data)
                    if len(data) != size:
                        raise ValueError("truncated tar member/header")
                    return data

                while True:
                    header = read_exact(512)
                    if header == bytes(512):
                        if read_exact(512) != bytes(512):
                            raise ValueError("invalid tar end marker")
                        while tail := archive.read(1024 * 1024):
                            tar_bytes += len(tail)
                            if tar_bytes > max_tar or any(tail):
                                raise ValueError("nonzero/trailing or oversized tar data")
                        break
                    if header[257:263] != b"ustar\0":
                        raise ValueError("only bounded USTAR headers are supported")
                    member = tarfile.TarInfo.frombuf(header, "utf-8", "strict")
                    if member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE) or member.linkname:
                        raise ValueError("links, special files, sparse files, and extension headers are forbidden")
                    name = str(_safe_name(member.name))
                    if name in seen or name not in expected:
                        raise ValueError("duplicate or undeclared tar member")
                    record = expected[name]
                    kind = "directory" if member.isdir() else "file"
                    if (kind != record["kind"] or member.size != record["bytes"]
                            or member.mode != record["mode"]):
                        raise ValueError("tar metadata differs from member manifest")
                    target = stage / name
                    if kind == "directory":
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        digest, remaining = hashlib.sha256(), member.size
                        with target.open("xb") as stream:
                            while remaining:
                                block = read_exact(min(1024 * 1024, remaining))
                                digest.update(block)
                                stream.write(block)
                                remaining -= len(block)
                        if digest.hexdigest() != record["sha256"]:
                            raise ValueError("unpacked member checksum mismatch")
                        padding = (-member.size) % 512
                        if padding and read_exact(padding) != bytes(padding):
                            raise ValueError("nonzero tar member padding")
                    seen.add(name)
                if seen != set(expected):
                    raise ValueError("archive does not contain exactly the declared members")
            # Recheck immediately before publishing; identical existing bytes are retained.
            _existing_matches(output, expected)
            output.mkdir(exist_ok=True)
            directories = [r for r in manifest["members"] if r["kind"] == "directory"]
            for record in directories:
                (output / record["path"]).mkdir(parents=True, exist_ok=True)
            for record in manifest["members"]:
                destination = output / record["path"]
                if record["kind"] == "file":
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if not destination.exists():
                        os.replace(stage / record["path"], destination)
                    destination.chmod(record["mode"])
            for record in sorted(directories, key=lambda row: row["path"].count("/"), reverse=True):
                (output / record["path"]).chmod(record["mode"])
    return {"status": "verified_and_restored", "archive_sha256": manifest["archive_sha256"],
            "manifest_sha256": manifest_sha, "members": len(expected),
            "unpacked_file_bytes": manifest["unpacked_file_bytes"], "output": str(output),
            "all_part_archive_member_checksums_verified": True, "existing_mismatches_overwritten": False}


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="operation", required=True)
    create = sub.add_parser("pack")
    create.add_argument("--source", required=True)
    create.add_argument("--output", required=True)
    restore = sub.add_parser("unpack")
    restore.add_argument("--bundle", required=True)
    restore.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.operation == "pack":
        result = pack(args.source, args.output)
        print(json.dumps({key: result[key] for key in
                          ("archive_sha256", "archive_bytes", "member_count", "unpacked_file_bytes")}))
    else:
        print(json.dumps(unpack(args.bundle, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
