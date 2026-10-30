"""Verify and restore a base64-part evidence archive without tar extraction APIs."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import tarfile
import tempfile


SCHEMA = "hepta.evidence.text-archive.v1"
CHUNK_BYTES = 128 * 1024
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_MEMBERS = 100_000


def canonical_json(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative_name(name, *, directory=False):
    if not isinstance(name, str) or "\\" in name or "\0" in name:
        raise ValueError("invalid member path")
    name = name[:-1] if directory and name.endswith("/") else name
    parts = name.split("/")
    if (not name or any(p in ("", ".", "..") for p in parts)
            or name.startswith("/") or PureWindowsPath(name).drive
            or PurePosixPath(name).as_posix() != name):
        raise ValueError("absolute, escaping, or noncanonical member path")
    return name


def inspect_archive(path, *, max_bytes=MAX_UNCOMPRESSED_BYTES):
    """Stream every member, rejecting links/devices and hashing file contents."""
    members, seen, total = [], set(), 0
    with tarfile.open(path, mode="r|xz") as archive:
        for member in archive:
            if len(members) >= MAX_MEMBERS or not (member.isfile() or member.isdir()):
                raise ValueError("unsupported member type or member-count bound")
            name = relative_name(member.name, directory=member.isdir())
            if name in seen or member.size < 0 or (member.isdir() and member.size):
                raise ValueError("duplicate member or invalid size")
            seen.add(name)
            total += member.size
            if total > max_bytes:
                raise ValueError("uncompressed archive exceeds configured bound")
            if member.isfile():
                digest, actual = hashlib.sha256(), 0
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError("missing regular-file body")
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
                    actual += len(block)
                if actual != member.size:
                    raise ValueError("truncated archive member")
                members.append(dict(path=name, type="file", bytes=actual, sha256=digest.hexdigest()))
            else:
                members.append(dict(path=name, type="directory", bytes=0))
    files = {m["path"] for m in members if m["type"] == "file"}
    for member in members:
        if any(parent.as_posix() in files for parent in PurePosixPath(member["path"]).parents if parent.as_posix() != "."):
            raise ValueError("a regular file is also an ancestor directory")
    members.sort(key=lambda m: m["path"])
    return dict(schema="hepta.evidence.file-inventory.v1", members=members,
                file_count=len(files), directory_count=len(members) - len(files),
                total_file_bytes=total)


def restore(package, output=None, *, archive_output=None, verify_only=False,
            max_bytes=MAX_UNCOMPRESSED_BYTES):
    package = Path(package).resolve()
    manifest = json.loads((package / "MANIFEST.json").read_text())
    if manifest.get("schema") != SCHEMA or manifest.get("chunk_bytes") != CHUNK_BYTES:
        raise ValueError("unsupported package schema or chunk size")
    if manifest["inventory"]["path"] != "INVENTORY.json":
        raise ValueError("inventory must use the fixed package-local filename")
    archive_length = manifest["archive"]["bytes"]
    if not isinstance(archive_length, int) or not 0 < archive_length <= max_bytes + 64 * 1024 * 1024:
        raise ValueError("compressed archive exceeds configured bound")
    inventory_file = package / relative_name(manifest["inventory"]["path"])
    if inventory_file.is_symlink() or sha256_file(inventory_file) != manifest["inventory"]["sha256"]:
        raise ValueError("inventory hash mismatch")
    inventory = json.loads(inventory_file.read_text())
    if inventory["total_file_bytes"] > max_bytes:
        raise ValueError("declared output exceeds configured bound")
    if output is None and not verify_only:
        raise ValueError("output directory is required")
    target = Path(output).absolute() if output is not None else None
    if target is not None and (target.exists() or target.is_symlink()):
        raise ValueError("restore output must not already exist")
    if archive_output is not None and (Path(archive_output).exists() or Path(archive_output).is_symlink()):
        raise ValueError("archive output must not already exist")
    temporary_parent = target.parent if target is not None else package.parent
    temporary_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".evidence-restore-", dir=temporary_parent) as temporary:
        temporary = Path(temporary)
        assembled = temporary / "archive.tar.xz"
        archive_digest, archive_bytes = hashlib.sha256(), 0
        parts = manifest.get("parts", [])
        if len(parts) != (archive_length + CHUNK_BYTES - 1) // CHUNK_BYTES:
            raise ValueError("archive part count differs from declared byte length")
        with assembled.open("xb") as destination:
            for index, part in enumerate(parts):
                name = relative_name(part["path"])
                if name != f"part-{index:05d}.b64":
                    raise ValueError("noncontiguous archive part numbering")
                path = package / name
                if path.is_symlink() or not 0 < part["binary_bytes"] <= CHUNK_BYTES:
                    raise ValueError("invalid archive part")
                if index < len(parts) - 1 and part["binary_bytes"] != CHUNK_BYTES:
                    raise ValueError("short nonfinal archive part")
                if path.stat().st_size != part["text_bytes"] or part["text_bytes"] > 4 * ((CHUNK_BYTES + 2) // 3) + 1:
                    raise ValueError("archive part text-size mismatch")
                text = path.read_bytes()
                if hashlib.sha256(text).hexdigest() != part["text_sha256"] or not text.endswith(b"\n"):
                    raise ValueError("archive part text hash or framing mismatch")
                block = base64.b64decode(text[:-1], validate=True)
                if len(block) != part["binary_bytes"] or hashlib.sha256(block).hexdigest() != part["binary_sha256"]:
                    raise ValueError("decoded archive part differs")
                archive_digest.update(block)
                archive_bytes += len(block)
                if archive_bytes > archive_length:
                    raise ValueError("archive parts exceed declared byte length")
                destination.write(block)
        if archive_bytes != manifest["archive"]["bytes"] or archive_digest.hexdigest() != manifest["archive"]["sha256"]:
            raise ValueError("whole archive identity differs")
        actual = inspect_archive(assembled, max_bytes=max_bytes)
        if actual != inventory:
            raise ValueError("archive member inventory differs")
        if not verify_only:
            staging = temporary / "restored"
            staging.mkdir()
            expected = {m["path"]: m for m in inventory["members"]}
            with tarfile.open(assembled, mode="r|xz") as archive:
                for member in archive:
                    name = relative_name(member.name, directory=member.isdir())
                    row = expected[name]
                    path = staging.joinpath(*PurePosixPath(name).parts)
                    if not path.resolve().is_relative_to(staging.resolve()):
                        raise ValueError("restore path escaped staging")
                    if row["type"] == "directory":
                        path.mkdir(parents=True, exist_ok=True)
                        path.chmod(0o755)
                        continue
                    if not member.isfile() or member.size != row["bytes"]:
                        raise ValueError("archive changed between validation and extraction")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    source = archive.extractfile(member)
                    with path.open("xb") as destination:
                        shutil.copyfileobj(source, destination, length=1024 * 1024)
                    path.chmod(0o644)
                    if path.stat().st_size != row["bytes"] or sha256_file(path) != row["sha256"]:
                        raise ValueError("restored file identity differs")
            actual_files = {p.relative_to(staging).as_posix() for p in staging.rglob("*") if p.is_file()}
            if actual_files != {m["path"] for m in inventory["members"] if m["type"] == "file"}:
                raise ValueError("restored file set differs")
            os.rename(staging, target)
        if archive_output is not None:
            destination = Path(archive_output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream, assembled.open("rb") as source:
                shutil.copyfileobj(source, stream, length=1024 * 1024)
    return dict(archive_sha256=manifest["archive"]["sha256"], archive_bytes=archive_bytes,
                files_verified=inventory["file_count"], file_bytes_verified=inventory["total_file_bytes"],
                restored=not verify_only, output=str(target) if not verify_only else None)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--archive-output", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--max-bytes", type=int, default=MAX_UNCOMPRESSED_BYTES)
    arguments = parser.parse_args()
    print(json.dumps(restore(arguments.package, arguments.output, archive_output=arguments.archive_output,
                             verify_only=arguments.verify_only, max_bytes=arguments.max_bytes), sort_keys=True))
