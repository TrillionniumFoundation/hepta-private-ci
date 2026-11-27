"""Restore and verify the bounded CI evidence files in this directory."""

import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tarfile
import zlib

MAX_PART_BYTES = 500_000
MAX_RAW_PART_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def positive_integer(value, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError("invalid byte count")
    return value


def safe_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", value):
        raise ValueError("invalid file name")
    return value


def restore(output, manifest_path):
    root = manifest_path.parent
    if manifest_path.is_symlink() or manifest_path.stat().st_size > 500_000:
        raise ValueError("invalid manifest file")
    manifest = json.loads(manifest_path.read_bytes(), object_pairs_hook=unique_pairs)
    if manifest["schema_version"] != 1:
        raise ValueError("unsupported schema")
    groups = manifest["groups"]
    if not isinstance(groups, list) or not 1 <= len(groups) <= 16:
        raise ValueError("invalid group count")
    total = sum(positive_integer(group["raw_bytes"], MAX_TOTAL_BYTES) for group in groups)
    if total > MAX_TOTAL_BYTES:
        raise ValueError("total byte bound exceeded")
    restored = {}
    seen_parts = set()
    for group in groups:
        name = safe_name(group["restored_name"])
        if name in restored:
            raise ValueError("duplicate restored name")
        parts = group["parts"]
        if not isinstance(parts, list) or not 1 <= len(parts) <= 128:
            raise ValueError("invalid part count")
        size = positive_integer(group["raw_bytes"], MAX_TOTAL_BYTES)
        if sum(positive_integer(part["raw_bytes"], MAX_RAW_PART_BYTES) for part in parts) != size:
            raise ValueError("part sizes do not match the group")
        chunks = []
        for number, part in enumerate(parts):
            if type(part["index"]) is not int or part["index"] != number:
                raise ValueError("invalid part order")
            file_name = safe_name(part["path"])
            if file_name in seen_parts:
                raise ValueError("duplicate carrier")
            seen_parts.add(file_name)
            path = root / file_name
            encoded_size = positive_integer(part["bytes"], MAX_PART_BYTES)
            if path.is_symlink() or not path.is_file() or path.stat().st_size != encoded_size:
                raise ValueError("carrier file mismatch")
            encoded = path.read_bytes()
            if digest(encoded) != part["sha256"]:
                raise ValueError("carrier digest mismatch")
            decoder = zlib.decompressobj(31)
            raw = decoder.decompress(encoded, part["raw_bytes"] + 1)
            if (
                len(raw) != part["raw_bytes"]
                or not decoder.eof
                or decoder.unused_data
                or decoder.unconsumed_tail
                or digest(raw) != part["raw_sha256"]
            ):
                raise ValueError("invalid gzip member")
            chunks.append(raw)
        value = b"".join(chunks)
        if len(value) != size or digest(value) != group["sha256"]:
            raise ValueError("restored group mismatch")
        restored[name] = value
    archive = restored["audit.tar"]
    expected = {member["path"]: member for member in manifest["members"]}
    if len(expected) != len(manifest["members"]):
        raise ValueError("duplicate member")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as source:
        members = source.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise ValueError("archive member set mismatch")
        for member in members:
            parts = Path(member.name).parts
            if (
                not member.isfile()
                or member.name.startswith("/")
                or "\\" in member.name
                or ":" in member.name
                or ".." in parts
            ):
                raise ValueError("unsafe archive member")
            stream = source.extractfile(member)
            if stream is None:
                raise ValueError("missing archive member")
            data = stream.read()
            if len(data) != expected[member.name]["bytes"] or digest(data) != expected[member.name]["sha256"]:
                raise ValueError("archive member digest mismatch")
    output.mkdir(mode=0o700, exist_ok=False)
    for name, value in restored.items():
        (output / name).write_bytes(value)
    print(json.dumps({"groups": len(restored), "members": len(expected), "all_bytes_verified": True}))


if __name__ == "__main__":
    restore(
        Path(sys.argv[1]),
        Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).with_name("proof-manifest.json"),
    )
