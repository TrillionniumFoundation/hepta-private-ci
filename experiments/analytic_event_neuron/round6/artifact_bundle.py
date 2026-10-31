"""Deterministic raw binary evidence bundles; no network or scientific imports."""

import argparse
from contextlib import contextmanager
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile
import tempfile

SCHEMA = "hepta.raw-artifact-bundle.v1"
MAX_CHUNK = 786432  # Connector base64 readback is complete below one MiB.


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe(name):
    require(isinstance(name, str) and name and "\\" not in name and "\0" not in name,
            "Invalid member name")
    path = PurePosixPath(name)
    require(not path.is_absolute() and ".." not in path.parts and name != "."
            and str(path) == name, "Unsafe or noncanonical member name")
    return name


def snapshot(root):
    members = []
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), "Source symlinks are forbidden")
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts:
            continue
        mode = stat.S_IMODE(path.stat().st_mode) & 0o777
        require(path.is_dir() or path.is_file(), "Only regular files and directories are supported")
        members.append({"name": safe(relative.as_posix()), "kind": "dir" if path.is_dir() else "file",
            "mode": mode, "bytes": 0 if path.is_dir() else path.stat().st_size,
            "sha256": None if path.is_dir() else sha(path)})
    return members


def member_index(members):
    require(isinstance(members, list), "Member inventory must be a list")
    result = {}
    for item in members:
        require(set(item) == {"name", "kind", "mode", "bytes", "sha256"}, "Unknown member fields")
        name = safe(item["name"])
        require(name not in result, "Duplicate member name")
        require("__pycache__" not in PurePosixPath(name).parts, "Excluded cache member")
        require(type(item["mode"]) is int and 0 <= item["mode"] <= 0o777, "Invalid permission mode")
        require(type(item["bytes"]) is int and item["bytes"] >= 0, "Invalid member size")
        require(item["kind"] in ("dir", "file"), "Unsupported member type")
        require((item["kind"] == "dir" and item["bytes"] == 0 and item["sha256"] is None)
                or (item["kind"] == "file" and isinstance(item["sha256"], str)
                    and len(item["sha256"]) == 64), "Invalid member identity")
        result[name] = item
    require(list(result) == sorted(result), "Member inventory order must be canonical")
    for name in result:
        for parent in PurePosixPath(name).parents:
            if str(parent) != ".":
                require(str(parent) in result and result[str(parent)]["kind"] == "dir",
                        "Every parent directory must be declared")
    return result


def check_tar(stream, expected):
    stream.seek(0)
    seen = set()
    with gzip.GzipFile(fileobj=stream, mode="rb") as decoded:
        with tarfile.open(fileobj=decoded, mode="r:") as archive:
            for item in archive:
                name = safe(item.name)
                require(name not in seen and name in expected, "Duplicate or undeclared archive member")
                seen.add(name)
                record = expected[name]
                require((item.isdir() if record["kind"] == "dir" else item.isreg())
                        and not item.issym() and not item.islnk() and item.mode == record["mode"]
                        and item.size == record["bytes"], "Archive type, mode or size mismatch")
                if item.isreg():
                    with archive.extractfile(item) as payload:
                        require(hashlib.file_digest(payload, "sha256").hexdigest() == record["sha256"],
                                "Archive member hash mismatch")
        while tail := decoded.read(1024 * 1024):
            require(not tail.strip(bytes([0])), "Nonzero data after tar terminator")
    require(seen == set(expected), "Missing archive members")
    stream.seek(0)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate manifest key")
        result[key] = value
    return result


def part_identity(name, payload):
    return {"name": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
            "git_blob_sha1": hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()}


@contextmanager
def validated(bundle, expected_manifest_sha256=None):
    bundle = Path(bundle)
    require(not bundle.is_symlink() and bundle.is_dir(), "Bundle must be a real directory")
    manifest_path = bundle / "BUNDLE.json"
    require(not manifest_path.is_symlink() and manifest_path.is_file(), "Manifest must be a regular file")
    if expected_manifest_sha256 is not None:
        require(sha(manifest_path) == expected_manifest_sha256, "Unexpected manifest identity")
    manifest = json.loads(manifest_path.read_text(), object_pairs_hook=unique)
    require(manifest["schema"] == SCHEMA and manifest["excluded_components"] == ["__pycache__"], "Unknown bundle schema")
    require(type(manifest["chunk_bytes"]) is int and 1 <= manifest["chunk_bytes"] <= MAX_CHUNK,
            "Chunk bound exceeds complete connector readback")
    require(type(manifest["root_mode"]) is int and 0 <= manifest["root_mode"] <= 0o777, "Invalid root mode")
    expected = member_index(manifest["members"])
    require(manifest["parts"] and manifest["archive"]["name"] == "archive.tar.gz", "Missing archive identity")
    archive_hash, size = hashlib.sha256(), 0
    with tempfile.TemporaryFile(dir=bundle.parent) as joined:
        for index, part in enumerate(manifest["parts"]):
            require(part["name"] == f"part-{index:05d}.bin", "Unsafe, duplicate or unordered chunk name")
            path = bundle / part["name"]
            require(not path.is_symlink() and path.is_file(), "Chunk must be a regular file")
            require(type(part["bytes"]) is int and 1 <= part["bytes"] <= manifest["chunk_bytes"]
                    and path.stat().st_size == part["bytes"], "Chunk size mismatch")
            payload = path.read_bytes()
            require(part_identity(part["name"], payload) == part, "Chunk SHA256 or Git blob SHA1 mismatch")
            joined.write(payload); archive_hash.update(payload); size += len(payload)
        require(size == manifest["archive"]["bytes"] and archive_hash.hexdigest() == manifest["archive"]["sha256"],
                "Reassembled archive identity mismatch")
        local = bundle / "archive.tar.gz"
        if local.exists() or local.is_symlink():
            require(not local.is_symlink() and local.is_file() and local.stat().st_size == size
                    and sha(local) == archive_hash.hexdigest(), "Local complete archive differs from chunks")
        joined.flush()
        check_tar(joined, expected)
        yield manifest, joined


def verify(bundle, expected_manifest_sha256=None):
    with validated(bundle, expected_manifest_sha256) as (manifest, _):
        return manifest


def pack(source, output, chunk_bytes=MAX_CHUNK):
    source, output = Path(source), Path(output)
    require(not source.is_symlink() and source.is_dir(), "Source must be a real directory")
    source = source.resolve()
    require(not output.resolve().is_relative_to(source), "Bundle output must be outside its source")
    require(type(chunk_bytes) is int and 1 <= chunk_bytes <= MAX_CHUNK, "Invalid chunk size")
    members = snapshot(source); member_index(members)
    root_mode = stat.S_IMODE(source.stat().st_mode) & 0o777
    output.mkdir(parents=True, exist_ok=False)
    archive_path = output / "archive.tar.gz"
    with archive_path.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for member in members:
                    item = tarfile.TarInfo(member["name"])
                    item.mode, item.size = member["mode"], member["bytes"]
                    if member["kind"] == "dir":
                        item.type = tarfile.DIRTYPE; archive.addfile(item)
                    else:
                        with (source / member["name"]).open("rb") as stream: archive.addfile(item, stream)
        raw.flush(); os.fsync(raw.fileno())
    with archive_path.open("rb") as stream: check_tar(stream, member_index(members))
    parts = []
    with archive_path.open("rb") as stream:
        while payload := stream.read(chunk_bytes):
            name = f"part-{len(parts):05d}.bin"
            with (output / name).open("xb") as target:
                target.write(payload); target.flush(); os.fsync(target.fileno())
            parts.append(part_identity(name, payload))
    require(snapshot(source) == members and stat.S_IMODE(source.stat().st_mode) & 0o777 == root_mode,
            "Source changed during packing")
    manifest = {"schema": SCHEMA, "excluded_components": ["__pycache__"], "root_mode": root_mode,
                "chunk_bytes": chunk_bytes, "members": members, "parts": parts,
                "archive": {"name": archive_path.name, "bytes": archive_path.stat().st_size, "sha256": sha(archive_path)}}
    with (output / "BUNDLE.json").open("x") as stream:
        json.dump(manifest, stream, sort_keys=True, indent=2); stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
    verify(output, sha(output / "BUNDLE.json"))
    return manifest


def restore(bundle, destination, expected_manifest_sha256=None):
    destination = Path(destination)
    require(not destination.exists() and not destination.is_symlink(), "Restore destination must be new")
    with validated(bundle, expected_manifest_sha256) as (manifest, stream):
        expected = member_index(manifest["members"])
        destination.mkdir(parents=False, exist_ok=False)  # Only after every chunk/member was checked.
        with tarfile.open(fileobj=stream, mode="r:gz") as archive:
            for item in archive:
                path = destination / safe(item.name)
                if item.isdir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(item) as incoming, path.open("xb") as target:
                        while payload := incoming.read(1024 * 1024): target.write(payload)
                        target.flush(); os.fsync(target.fileno())
                    require(path.stat().st_size == expected[item.name]["bytes"]
                            and sha(path) == expected[item.name]["sha256"], "Restored file readback differs")
                    path.chmod(item.mode)
        for member in reversed(manifest["members"]):
            if member["kind"] == "dir": (destination / member["name"]).chmod(member["mode"])
        destination.chmod(manifest["root_mode"])
        require(all(stat.S_IMODE((destination / member["name"]).stat().st_mode) == member["mode"]
                    for member in manifest["members"]), "Restored modes differ")
        return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    command = sub.add_parser("pack"); command.add_argument("source", type=Path); command.add_argument("output", type=Path)
    command.add_argument("--chunk-bytes", type=int, default=MAX_CHUNK)
    for name in ("verify", "restore"):
        command = sub.add_parser(name); command.add_argument("bundle", type=Path)
        if name == "restore": command.add_argument("destination", type=Path)
        command.add_argument("--expected-manifest-sha256")
    args = parser.parse_args()
    if args.operation == "pack": result = pack(args.source, args.output, args.chunk_bytes); bundle = args.output
    elif args.operation == "restore": result = restore(args.bundle, args.destination, args.expected_manifest_sha256); bundle = args.bundle
    else: result = verify(args.bundle, args.expected_manifest_sha256); bundle = args.bundle
    print(json.dumps({"passed": True, "manifest_sha256": sha(bundle / "BUNDLE.json"),
                      "archive": result["archive"], "chunks": len(result["parts"]), "members": len(result["members"])}))


if __name__ == "__main__":
    main()
