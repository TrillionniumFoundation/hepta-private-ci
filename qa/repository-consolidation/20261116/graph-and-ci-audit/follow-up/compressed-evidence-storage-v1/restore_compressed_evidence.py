#!/usr/bin/env python3
"""Verify compressed evidence carriers and restore their original logical files."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import zlib

PREFIX = "qa/repository-consolidation/20261116/graph-and-ci-audit/follow-up/"
INDEX = PREFIX + "compressed-evidence-storage-v1/storage-index.json"
SCHEMA = "hepta.compressed-evidence-storage.v1"
MAX_CARRIER_BYTES = 500000
MAX_RAW_CHUNK_BYTES = 480000
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate index key")
        result[key] = value
    return result


def relative_path(value):
    if (
        not isinstance(value, str)
        or not value.startswith(PREFIX)
        or "\\" in value
        or ":" in value
    ):
        raise ValueError("evidence path outside the published audit")
    path = PurePosixPath(value)
    if str(path) != value or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("invalid evidence path")
    return path


def read_regular(root, relative, limit):
    path = root / relative_path(relative)
    for parent in [path, *path.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError("symbolic link in evidence path")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
        raise ValueError("invalid evidence file or size")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) != info.st_size or len(raw) > limit:
        raise ValueError("evidence file changed or exceeded its limit")
    return raw


def check_hash(raw, expected):
    if not isinstance(expected, str) or not re.fullmatch("[0-9a-f]{64}", expected):
        raise ValueError("invalid SHA256")
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("evidence SHA256 mismatch")


def check_blob(raw, expected):
    actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if actual != expected:
        raise ValueError("evidence Git blob mismatch")


def decode_carrier(raw, entry):
    expected = entry["raw_bytes"]
    if type(expected) is not int or not 0 < expected <= MAX_RAW_CHUNK_BYTES:
        raise ValueError("invalid decoded chunk size")
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    decoded = decoder.decompress(raw, expected + 1)
    if (
        len(decoded) != expected
        or not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
    ):
        raise ValueError("truncated, oversized, or extra gzip data")
    check_hash(decoded, entry["raw_sha256"])
    return decoded


def validate(root, document):
    if (
        document.get("schema") != SCHEMA
        or document.get("carrier_limit") != MAX_CARRIER_BYTES
        or document.get("raw_chunk_limit") != MAX_RAW_CHUNK_BYTES
        or not isinstance(document.get("groups"), list)
        or not 0 < len(document["groups"]) <= 32
    ):
        raise ValueError("invalid evidence storage index")
    restored = {}
    archives = {}
    seen_carriers = set()
    total_bytes = 0
    for group in document["groups"]:
        archive = str(relative_path(group["archive_path"]))
        if not archive.endswith(".tar.gz") or archive in archives:
            raise ValueError("invalid or duplicate archive")
        size = group["archive_bytes"]
        if type(size) is not int or not 0 < size <= MAX_ARCHIVE_BYTES:
            raise ValueError("invalid archive size")
        total_bytes += size
        if total_bytes > MAX_TOTAL_BYTES:
            raise ValueError("total archive size exceeds the limit")
        carriers = group["carriers"]
        if not isinstance(carriers, list) or not carriers:
            raise ValueError("missing archive carriers")
        raw_sizes = [entry["raw_bytes"] for entry in carriers]
        if (
            any(
                type(size) is not int or not 0 < size <= MAX_RAW_CHUNK_BYTES
                for size in raw_sizes
            )
            or sum(raw_sizes) != size
        ):
            raise ValueError("declared carrier sizes do not match the archive")
        decoded = []
        expected_names = set()
        for number, entry in enumerate(carriers):
            expected_path = archive + f".fragments/part-{number:04}.gz"
            if entry["path"] != expected_path or expected_path in seen_carriers:
                raise ValueError("unordered, duplicate, or invalid carrier path")
            seen_carriers.add(expected_path)
            expected_names.add(PurePosixPath(expected_path).name)
            raw = read_regular(root, expected_path, MAX_CARRIER_BYTES)
            if len(raw) != entry["bytes"]:
                raise ValueError("carrier length mismatch")
            check_hash(raw, entry["sha256"])
            check_blob(raw, entry["git_blob"])
            decoded.append(decode_carrier(raw, entry))
        actual_names = {
            path.name for path in (root / (archive + ".fragments")).iterdir()
        }
        if actual_names != expected_names:
            raise ValueError("missing or extra carrier file")
        stream = b"".join(decoded)
        if len(stream) != size:
            raise ValueError("archive length mismatch")
        check_hash(stream, group["archive_sha256"])
        offset = 0
        parts = group["original_parts"]
        if not isinstance(parts, list) or not parts:
            raise ValueError("missing original fragment identities")
        for entry in parts:
            path = str(relative_path(entry["path"]))
            if (
                not re.fullmatch(re.escape(archive) + r"\.part-?[0-9]+", path)
                or path in restored
                or entry["offset"] != offset
                or type(entry["bytes"]) is not int
                or not 0 < entry["bytes"] <= MAX_CARRIER_BYTES
            ):
                raise ValueError("invalid original fragment identity or order")
            end = offset + entry["bytes"]
            original = stream[offset:end]
            if len(original) != entry["bytes"]:
                raise ValueError("original fragment length mismatch")
            check_hash(original, entry["sha256"])
            check_blob(original, entry["git_blob"])
            restored[path] = original
            offset = end
        if offset != size:
            raise ValueError("original fragments do not cover the complete archive")
        archives[archive] = stream
    return restored, archives


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--verify-only", action="store_true")
    mode.add_argument("--destination", type=Path)
    args = parser.parse_args(argv)
    try:
        root = args.repository_root.resolve(strict=True)
        document = json.loads(
            read_regular(root, INDEX, 256000), object_pairs_hook=unique_object
        )
        originals, archives = validate(root, document)
        if args.destination is not None:
            destination = args.destination
            if destination.exists() or destination.is_symlink():
                raise ValueError("destination must not already exist")
            destination.parent.resolve(strict=True)
            destination.mkdir(mode=0o700)
            for relative, raw in {**originals, **archives}.items():
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    stream.write(raw)
        print(
            json.dumps(
                {
                    "verified_original_fragments": len(originals),
                    "verified_archives": len(archives),
                    "restored": args.destination is not None,
                    "source_commit": document["source_commit"],
                    "qualification_granted": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (KeyError, TypeError, ValueError, OSError, zlib.error) as error:
        print(f"Evidence storage validation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
