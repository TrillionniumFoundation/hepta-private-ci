"""Restore retained audit files without executing archived code or fetching data."""

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import zlib

INDEX_GZIP_SHA256 = "adf6da648c5c39a2b4f9d4f79ac2667c4f961f62e11e8529782e8fd77ae96cca"
INDEX_RAW_SHA256 = "f6875fd1dcf01837ad0a860abab69cbce9e17aea8e36b51cbdc3e43451d91845"
MAX_INDEX_BYTES = 1_048_576
MAX_RAW_BYTES = 134_217_728


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inflate(data, size):
    decoder = zlib.decompressobj(wbits=31)
    raw = decoder.decompress(data, size + 1)
    if (
        len(raw) != size
        or not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
    ):
        raise ValueError("gzip length or stream boundary differs")
    return raw


def relative(value):
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise ValueError("invalid archive path")
    if "\\" in value or "\x00" in value:
        raise ValueError("invalid archive path")
    return path


def read_regular(path, limit):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as source:
        meta = os.fstat(source.fileno())
        if not stat.S_ISREG(meta.st_mode) or meta.st_size > limit:
            raise ValueError("not a bounded regular file")
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError("file exceeds limit")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output", type=Path, help="new directory; existing paths are rejected"
    )
    args = parser.parse_args()
    archive = Path(__file__).resolve().parent
    packed = read_regular(archive / "index.json.gz", 500_000)
    if digest(packed) != INDEX_GZIP_SHA256:
        raise ValueError("index checksum differs")
    with gzip.GzipFile(fileobj=io.BytesIO(packed)) as stream:
        index_raw = stream.read(MAX_INDEX_BYTES + 1)
    if len(index_raw) > MAX_INDEX_BYTES or digest(index_raw) != INDEX_RAW_SHA256:
        raise ValueError("index length or checksum differs")
    index = json.loads(index_raw)
    if (
        index["schemaVersion"] != 1
        or not 0 <= index["rawPayloadBytes"] <= MAX_RAW_BYTES
    ):
        raise ValueError("unsupported archive")
    raw = bytearray()
    for number, chunk in enumerate(index["chunks"]):
        name = f"payload/chunk-{number:05d}.bin.gz"
        if chunk["path"] != name or chunk["rawOffset"] != len(raw):
            raise ValueError("chunk order differs")
        if not 0 < chunk["rawBytes"] <= 480_000:
            raise ValueError("invalid raw chunk length")
        packed = read_regular(archive / name, 500_000)
        if (
            len(packed) != chunk["compressedBytes"]
            or digest(packed) != chunk["compressedSHA256"]
        ):
            raise ValueError("compressed chunk checksum differs")
        block = inflate(packed, chunk["rawBytes"])
        if digest(block) != chunk["rawSHA256"]:
            raise ValueError("raw chunk checksum differs")
        raw.extend(block)
        if len(raw) > MAX_RAW_BYTES:
            raise ValueError("raw archive exceeds limit")
    if len(raw) != index["rawPayloadBytes"] or digest(raw) != index["rawPayloadSHA256"]:
        raise ValueError("raw archive checksum differs")
    objects = {}
    offset = 0
    for item in index["contents"]:
        if item["offset"] != offset or item["bytes"] < 0:
            raise ValueError("content order differs")
        data = bytes(raw[offset : offset + item["bytes"]])
        offset += item["bytes"]
        git_blob = hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data
        ).hexdigest()
        if (
            len(data) != item["bytes"]
            or digest(data) != item["sha256"]
            or git_blob != item["gitBlob"]
        ):
            raise ValueError("content identity differs")
        if item["sha256"] in objects:
            raise ValueError("duplicate content identity")
        objects[item["sha256"]] = data
    if offset != len(raw):
        raise ValueError("unreferenced payload bytes")
    seen = set()
    for entry in index["files"]:
        relative(entry["path"])
        if entry["path"] in seen or entry["contentSHA256"] not in objects:
            raise ValueError("duplicate path or unknown content")
        if entry["mode"] not in (0o400, 0o444, 0o600, 0o644, 0o700, 0o755):
            raise ValueError("unsupported permission mode")
        seen.add(entry["path"])
    output = args.output.absolute()
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    for entry in index["files"]:
        parts = relative(entry["path"]).parts
        parent = output
        for part in parts[:-1]:
            parent = parent / part
            try:
                parent.mkdir(mode=0o700)
            except FileExistsError:
                if not stat.S_ISDIR(parent.lstat().st_mode):
                    raise ValueError("restore parent is not a directory")
        destination = parent / parts[-1]
        descriptor = os.open(
            destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "wb") as target:
            target.write(objects[entry["contentSHA256"]])
            os.fchmod(target.fileno(), entry["mode"])
        restored = read_regular(destination, MAX_RAW_BYTES)
        if (
            digest(restored) != entry["contentSHA256"]
            or stat.S_IMODE(destination.lstat().st_mode) != entry["mode"]
        ):
            raise ValueError("restored file differs")
    print(
        json.dumps(
            {
                "restoredFiles": len(index["files"]),
                "uniqueContents": len(objects),
                "excludedFiles": len(index["excluded"]),
                "rawPayloadSHA256": index["rawPayloadSHA256"],
                "allBytesAndModesVerified": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
