#!/usr/bin/env python3
"""Preserve an exact Git evidence subtree in bounded, verifiable archive parts.

The payload is one gzip stream of file bytes in manifest order, not an executable
archive or a tar extraction. Verification needs no original long filesystem
paths. Restoration creates a new directory and never overwrites existing files.
The manifest establishes integrity; it does not authenticate evidence or change
the meaning of any recorded result.
"""

import argparse
from contextlib import contextmanager
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile


FORMAT = "hepta-evidence-stream-v1"
PART_BYTES = 480_000
MAX_FILES = 100_000
MAX_TOTAL = 4 * 1024**3
MAX_INDEX = 480_000
MAX_MANIFEST_BYTES = 32 * 1024**2
READ_BYTES = 1024 * 1024


class ArchiveError(ValueError):
    """An archive, source binding, or destination failed validation."""


def require(condition, message):
    if not condition:
        raise ArchiveError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def compressed(data):
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as stream:
        stream.write(data)
    return output.getvalue()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def decoded(data):
    return json.loads(data, object_pairs_hook=unique_object)


def integer(value, maximum, label):
    require(type(value) is int and 0 <= value <= maximum, f"invalid {label}")
    return value


def hex_digest(value, length):
    require(
        isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{length}}}", value),
        "invalid digest",
    )
    return value


def portable_path(value):
    require(
        isinstance(value, str) and 0 < len(value.encode()) <= 4096,
        "invalid member path",
    )
    parts = value.split("/")
    require(
        all(part not in {"", ".", ".."} for part in parts)
        and not PurePosixPath(value).is_absolute()
        and not any(char in value for char in '\\:*?"<>|')
        and all(ord(char) >= 32 for char in value),
        "unsafe member path",
    )
    return value


def regular_bytes(path, limit):
    require(not path.is_symlink() and path.is_file(), f"not a regular file: {path}")
    require(path.stat().st_size <= limit, f"file exceeds bound: {path}")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    require(len(data) <= limit, f"file grew beyond bound: {path}")
    return data


def git_members(repo, revision, prefix):
    hex_digest(revision, 40)
    portable_path(prefix)
    result = subprocess.check_output(
        ["git", "ls-tree", "-rz", revision, "--", f":(literal){prefix}"], cwd=repo
    )
    members = []
    for record in result.split(b"\0"):
        if not record:
            continue
        metadata, name = record.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        path = portable_path(name.decode())
        require(
            kind == "blob" and mode in {"100644", "100755"},
            "only regular Git files can be archived",
        )
        require(path.startswith(prefix + "/"), "source prefix must be a directory")
        members.append({"path": path, "mode": mode, "git_blob": hex_digest(oid, 40)})
    require(0 < len(members) <= MAX_FILES, "empty or oversized source tree")
    return sorted(members, key=lambda item: item["path"])


def blob_hasher(size):
    return hashlib.sha1(b"blob " + str(size).encode() + b"\0")


def copy_member(source, target, size):
    content_hash, git_hash = hashlib.sha256(), blob_hasher(size)
    remaining = size
    while remaining:
        block = source.read(min(remaining, READ_BYTES))
        require(bool(block), "truncated member payload")
        remaining -= len(block)
        content_hash.update(block)
        git_hash.update(block)
        if target is not None:
            target.write(block)
    return content_hash.hexdigest(), git_hash.hexdigest()


def write_file(output, name, data):
    require(len(data) <= PART_BYTES, "archive file exceeds repository blob budget")
    (output / name).write_bytes(data)
    return {"name": name, "bytes": len(data), "sha256": digest(data)}


def pack(repo, revision, prefix, output, part_bytes=PART_BYTES):
    integer(part_bytes, PART_BYTES, "part size")
    require(part_bytes > 0, "part size must be positive")
    members = git_members(repo, revision, prefix)
    require(not output.exists() and not output.is_symlink(), "output already exists")
    output.mkdir(parents=True)
    entries, total = [], 0
    with tempfile.TemporaryFile() as payload:
        with gzip.GzipFile(fileobj=payload, mode="wb", filename="", mtime=0) as zipped:
            for member in members:
                path = repo / member["path"]
                require(
                    path.resolve().is_relative_to(repo.resolve())
                    and not path.is_symlink()
                    and path.is_file(),
                    f"missing or unsafe source file: {path}",
                )
                size = path.stat().st_size
                total += size
                require(total <= MAX_TOTAL, "source exceeds archive byte budget")
                with path.open("rb") as source:
                    content_hash, git_hash = copy_member(source, zipped, size)
                    require(not source.read(1), f"source grew during packing: {path}")
                require(git_hash == member["git_blob"], f"Git blob mismatch: {path}")
                entries.append(dict(member, bytes=size, sha256=content_hash))
        payload.seek(0)
        parts, payload_hash, payload_bytes = [], hashlib.sha256(), 0
        while block := payload.read(part_bytes):
            payload_hash.update(block)
            payload_bytes += len(block)
            parts.append(write_file(output, f"p{len(parts):05d}.bin", block))
    shards, pending, length = [], [], 3
    require(
        sum(len(encoded(entry)) + 1 for entry in entries) + 2 <= MAX_MANIFEST_BYTES,
        "total manifest bytes exceed limit",
    )
    for entry in entries:
        record_size = len(encoded(entry)) + 1
        if pending and length + record_size > MAX_INDEX:
            raw = encoded(pending)
            item = write_file(output, f"m{len(shards):05d}.json.gz", compressed(raw))
            shards.append(
                dict(item, decoded_bytes=len(raw), decoded_sha256=digest(raw))
            )
            pending, length = [], 3
        pending.append(entry)
        length += record_size
    if pending:
        raw = encoded(pending)
        item = write_file(output, f"m{len(shards):05d}.json.gz", compressed(raw))
        shards.append(dict(item, decoded_bytes=len(raw), decoded_sha256=digest(raw)))
    index = {
        "format": FORMAT,
        "source_revision": revision,
        "source_prefix": prefix,
        "source_listing_sha256": digest(encoded(members)),
        "member_count": len(entries),
        "total_bytes": total,
        "payload_bytes": payload_bytes,
        "payload_sha256": payload_hash.hexdigest(),
        "members": shards,
        "parts": parts,
    }
    write_file(
        output,
        "index.json",
        json.dumps(index, indent=2, sort_keys=True).encode() + b"\n",
    )
    return index


def read_file(archive, item, name):
    require(item["name"] == name, "noncanonical archive part name or ordering")
    size = integer(item["bytes"], PART_BYTES, "archive file size")
    data = regular_bytes(archive / name, PART_BYTES)
    require(
        len(data) == size and digest(data) == hex_digest(item["sha256"], 64),
        f"archive file integrity mismatch: {name}",
    )
    return data


def read_index(archive):
    index = decoded(regular_bytes(archive / "index.json", MAX_INDEX))
    require(index["format"] == FORMAT, "unsupported archive format")
    hex_digest(index["source_revision"], 40)
    portable_path(index["source_prefix"])
    integer(index["member_count"], MAX_FILES, "member count")
    integer(index["total_bytes"], MAX_TOTAL, "total bytes")
    integer(index["payload_bytes"], MAX_TOTAL + MAX_TOTAL // 100, "payload bytes")
    require(
        isinstance(index["members"], list) and 0 < len(index["members"]) <= MAX_FILES,
        "invalid member shards",
    )
    require(
        isinstance(index["parts"], list) and 0 < len(index["parts"]) <= MAX_FILES,
        "invalid payload parts",
    )
    entries, decoded_total = [], 0
    for position, item in enumerate(index["members"]):
        data = read_file(archive, item, f"m{position:05d}.json.gz")
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            raw = stream.read(MAX_INDEX + 1)
        require(
            len(raw) == integer(item["decoded_bytes"], MAX_INDEX, "manifest bytes")
            and digest(raw) == hex_digest(item["decoded_sha256"], 64),
            "member manifest integrity mismatch",
        )
        decoded_total += len(raw)
        require(
            decoded_total <= MAX_MANIFEST_BYTES, "total manifest bytes exceed limit"
        )
        shard = decoded(raw)
        require(
            isinstance(shard, list) and 0 < len(shard) <= MAX_FILES - len(entries),
            "invalid member shard",
        )
        entries.extend(shard)
    require(len(entries) == index["member_count"], "member count mismatch")
    previous, total, listing = "", 0, []
    for entry in entries:
        require(
            set(entry) == {"path", "mode", "git_blob", "bytes", "sha256"},
            "unexpected member fields",
        )
        path = portable_path(entry["path"])
        require(
            path > previous and path.startswith(index["source_prefix"] + "/"),
            "duplicate, unordered, or out-of-scope member",
        )
        previous = path
        require(entry["mode"] in {"100644", "100755"}, "invalid file mode")
        hex_digest(entry["git_blob"], 40)
        hex_digest(entry["sha256"], 64)
        total += integer(entry["bytes"], MAX_TOTAL, "member bytes")
        require(total <= MAX_TOTAL, "member bytes exceed limit")
        listing.append({key: entry[key] for key in ("path", "mode", "git_blob")})
    require(total == index["total_bytes"], "total member bytes mismatch")
    require(
        digest(encoded(listing)) == hex_digest(index["source_listing_sha256"], 64),
        "source listing mismatch",
    )
    expected = {"index.json"} | {
        item["name"] for item in index["members"] + index["parts"]
    }
    require(
        {path.name for path in archive.iterdir()} == expected,
        "unlisted or missing archive files",
    )
    return index, entries, listing


def inspect_payload(payload, entries, destination=None):
    payload.seek(0)
    with gzip.GzipFile(fileobj=payload, mode="rb") as stream:
        for entry in entries:
            if destination is None:
                actual = copy_member(stream, None, entry["bytes"])
            else:
                path = destination / entry["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as output:
                    actual = copy_member(stream, output, entry["bytes"])
                path.chmod(0o755 if entry["mode"] == "100755" else 0o644)
            require(
                actual == (entry["sha256"], entry["git_blob"]),
                f"member integrity mismatch: {entry['path']}",
            )
        require(not stream.read(1), "unlisted trailing payload")


@contextmanager
def verified_payload(archive, repo=None, expected_source=None, expected_listing=None):
    index, entries, listing = read_index(archive)
    if expected_source is not None:
        require(
            index["source_revision"] == hex_digest(expected_source, 40),
            "unexpected source revision",
        )
    if expected_listing is not None:
        require(
            index["source_listing_sha256"] == hex_digest(expected_listing, 64),
            "unexpected original source listing",
        )
    if repo is not None:
        require(
            git_members(repo, index["source_revision"], index["source_prefix"])
            == listing,
            "archive does not cover the exact original Git subtree",
        )
    with tempfile.TemporaryFile() as payload:
        payload_hash, total = hashlib.sha256(), 0
        for position, item in enumerate(index["parts"]):
            data = read_file(archive, item, f"p{position:05d}.bin")
            total += len(data)
            require(total <= index["payload_bytes"], "payload exceeds declared size")
            payload_hash.update(data)
            payload.write(data)
        require(
            total == index["payload_bytes"]
            and payload_hash.hexdigest() == hex_digest(index["payload_sha256"], 64),
            "whole payload integrity mismatch",
        )
        inspect_payload(payload, entries)
        yield index, entries, payload


def verify(
    archive, repo=None, expected_source=None, destination=None, expected_listing=None
):
    with verified_payload(archive, repo, expected_source, expected_listing) as (
        index,
        entries,
        payload,
    ):
        if destination is not None:
            require(
                not destination.exists() and not destination.is_symlink(),
                "restore destination must not exist",
            )
            destination.mkdir(parents=False, exist_ok=False)
            inspect_payload(payload, entries, destination)
        return {
            key: index[key]
            for key in (
                "format",
                "source_revision",
                "source_prefix",
                "member_count",
                "total_bytes",
                "payload_bytes",
                "payload_sha256",
                "source_listing_sha256",
            )
        }


def check_tree(repo, revision, max_path, max_blob, prefix=None):
    command = ["git", "ls-tree", "-rzl", revision]
    if prefix is not None:
        command += ["--", f":(literal){portable_path(prefix)}"]
    rows = subprocess.check_output(command, cwd=repo)
    failures = []
    count = 0
    for row in rows.split(b"\0"):
        if not row:
            continue
        metadata, name = row.split(b"\t", 1)
        mode, kind, _oid, size = metadata.decode().split()
        path = name.decode()
        length = len(path.encode("utf-16-le")) // 2
        if kind == "blob" and (length > max_path or int(size) > max_blob):
            failures.append({"path": path, "path_length": length, "bytes": int(size)})
        count += 1
    require(count > 0, "empty checkout scope")
    require(not failures, "checkout budget violations: " + json.dumps(failures))
    return {"files_checked": count, "max_path": max_path, "max_blob": max_blob}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("pack")
    create.add_argument("--repo", type=Path, required=True)
    create.add_argument("--revision", required=True)
    create.add_argument("--prefix", required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--part-bytes", type=int, default=PART_BYTES)
    for command in ("verify", "restore"):
        read = commands.add_parser(command)
        read.add_argument("archive", type=Path)
        read.add_argument("--repo", type=Path)
        read.add_argument("--expected-source")
        read.add_argument("--expected-listing")
        if command == "restore":
            read.add_argument("--destination", type=Path, required=True)
    tree = commands.add_parser("check-tree")
    tree.add_argument("--repo", type=Path, default=Path("."))
    tree.add_argument("--revision", default="HEAD")
    tree.add_argument("--max-path", type=int, default=190)
    tree.add_argument("--max-blob", type=int, default=512_000)
    tree.add_argument("--prefix")
    args = parser.parse_args()
    try:
        if args.command == "pack":
            result = pack(
                args.repo, args.revision, args.prefix, args.output, args.part_bytes
            )
        elif args.command == "check-tree":
            result = check_tree(
                args.repo, args.revision, args.max_path, args.max_blob, args.prefix
            )
        else:
            result = verify(
                args.archive,
                args.repo,
                args.expected_source,
                getattr(args, "destination", None),
                args.expected_listing,
            )
    except (
        ArchiveError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        EOFError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"evidence archive rejected: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
