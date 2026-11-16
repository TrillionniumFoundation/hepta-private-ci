#!/usr/bin/env python3
"""Load or package the root caller manifest without changing its TOML bytes.

The small CALLERS.toml index binds ordered gzip parts to the complete original
document. Small native TOML manifests remain supported for verifier fixtures.

Inspect or edit the original text outside the checkout:
  python3 scripts/hepta_caller_manifest.py unpack CALLERS.toml /tmp/callers.toml
  python3 scripts/hepta_caller_manifest.py pack /tmp/callers.toml /tmp/callers-package

Both output paths must be absent. Review and copy the resulting index and parts
together, then run the original caller verifier and B4 source tests.
"""

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import stat
import tomllib
import zlib
from pathlib import Path
from typing import Any

STORAGE_FORMAT = "hepta-callers-gzip-v1"
PARTS_DIRECTORY = "scripts/hepta_callers_manifest_parts"
MAX_DOCUMENT_BYTES = 512_000
MAX_INDEX_BYTES = 65_536
MAX_PART_BYTES = 500_000
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_PARTS = 64
INDEX_FIELDS = frozenset(
    {
        "storage_format",
        "manifest_bytes",
        "manifest_sha256",
        "boundary_count",
        "protected_file_count",
        "part",
    }
)
PART_FIELDS = frozenset(
    {"path", "compressed_bytes", "compressed_sha256", "raw_bytes", "raw_sha256"}
)
PAYLOAD_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "plan_id",
        "source_roots",
        "ignored_path_fragments",
        "privileged_inventory",
        "boundary",
        "protected_file",
        "authority",
    }
)
PAYLOAD_OPTIONAL_FIELDS = frozenset({"plan_version", "rule"})


class ManifestStorageError(ValueError):
    """The manifest or its storage representation is incomplete or invalid."""


def _fail(message: str) -> None:
    raise ManifestStorageError(message)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bounded_file(path: Path, limit: int) -> bytes:
    """Read only one regular file, bounded independently of declared lengths."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        _fail(f"manifest input must be a regular file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(opened.st_mode)
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            or opened.st_size > limit
        ):
            _fail(f"manifest input changed or exceeds its size bound: {path}")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    changed = any(
        getattr(after, field) != getattr(opened, field)
        for field in (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
    )
    if len(data) > limit or len(data) != opened.st_size or changed:
        _fail(f"manifest input changed or exceeds its size bound: {path}")
    return data


def _toml(raw: bytes) -> dict[str, Any]:
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ManifestStorageError(f"invalid caller TOML: {exc}") from exc


def _positive_integer(value: Any, limit: int, name: str) -> int:
    if type(value) is not int or not 0 < value <= limit:
        _fail(f"{name} must be an integer in 1..{limit}")
    return value


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        _fail(f"{name} must be a lowercase SHA256 digest")
    return value


def _payload_shape(data: dict[str, Any]) -> tuple[int, int]:
    """Check storage schema; the existing verifier retains all caller rules."""
    if (
        not PAYLOAD_REQUIRED_FIELDS <= data.keys()
        or data.keys() - PAYLOAD_REQUIRED_FIELDS - PAYLOAD_OPTIONAL_FIELDS
    ):
        _fail("packaged caller manifest has missing or unknown fields")
    if type(data["schema_version"]) is not int or data["schema_version"] != 2:
        _fail("packaged caller manifest schema_version must be 2")
    if data["plan_id"] != "HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN":
        _fail("packaged caller manifest plan_id mismatch")
    counts = []
    for section, key in (("boundary", "id"), ("protected_file", "path")):
        rows = data[section]
        if not isinstance(rows, list) or not rows:
            _fail(f"packaged caller manifest requires {section} rows")
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get(key), str):
                _fail(f"packaged caller manifest requires {section}.{key}")
            value = row[key]
            if not value or value in seen:
                _fail(f"packaged caller manifest duplicate or empty {section}.{key}")
            seen.add(value)
        counts.append(len(rows))
    return counts[0], counts[1]


def _unpack(index: dict[str, Any], path: Path) -> bytes:
    if set(index) != INDEX_FIELDS or index["storage_format"] != STORAGE_FORMAT:
        _fail("caller storage index has unknown fields or storage format")
    size = _positive_integer(
        index["manifest_bytes"], MAX_MANIFEST_BYTES, "manifest_bytes"
    )
    digest = _sha256(index["manifest_sha256"], "manifest_sha256")
    boundary_count = _positive_integer(
        index["boundary_count"], MAX_MANIFEST_BYTES, "boundary_count"
    )
    protected_count = _positive_integer(
        index["protected_file_count"], MAX_MANIFEST_BYTES, "protected_file_count"
    )
    parts = index["part"]
    if not isinstance(parts, list) or not 0 < len(parts) <= MAX_PARTS:
        _fail("caller storage index requires a bounded nonempty part list")
    expected_names = set()
    raw_total = 0
    for position, part in enumerate(parts):
        if not isinstance(part, dict) or set(part) != PART_FIELDS:
            _fail("caller storage part has missing or unknown fields")
        name = f"part-{position:04d}.toml.gz"
        if part["path"] != f"{PARTS_DIRECTORY}/{name}":
            _fail("caller storage parts must use unique ordered local paths")
        expected_names.add(name)
        _positive_integer(part["compressed_bytes"], MAX_PART_BYTES, "compressed_bytes")
        raw_total += _positive_integer(
            part["raw_bytes"], MAX_MANIFEST_BYTES, "raw_bytes"
        )
        _sha256(part["compressed_sha256"], "compressed_sha256")
        _sha256(part["raw_sha256"], "raw_sha256")
    if raw_total != size:
        _fail("caller storage part lengths do not sum to manifest_bytes")
    directory = path.parent
    for component in Path(PARTS_DIRECTORY).parts:
        directory = directory / component
        if not stat.S_ISDIR(directory.lstat().st_mode):
            _fail("caller storage parts directory must be a real directory")
    if {entry.name for entry in directory.iterdir()} != expected_names:
        _fail("caller storage parts directory has missing or extra entries")
    chunks = []
    for part in parts:
        compressed = _bounded_file(path.parent / part["path"], MAX_PART_BYTES)
        if (
            len(compressed) != part["compressed_bytes"]
            or _digest(compressed) != part["compressed_sha256"]
        ):
            _fail("caller storage compressed part length or digest mismatch")
        decoder = zlib.decompressobj(wbits=31)
        try:
            raw = decoder.decompress(compressed, part["raw_bytes"] + 1)
        except zlib.error as exc:
            raise ManifestStorageError(f"invalid caller gzip part: {exc}") from exc
        if (
            len(raw) != part["raw_bytes"]
            or not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
        ):
            _fail("caller gzip part is truncated, oversized, or has trailing data")
        if _digest(raw) != part["raw_sha256"]:
            _fail("caller storage raw part digest mismatch")
        chunks.append(raw)
    raw = b"".join(chunks)
    if len(raw) != size or _digest(raw) != digest:
        _fail("caller manifest length or digest mismatch")
    if _payload_shape(_toml(raw)) != (boundary_count, protected_count):
        _fail("caller manifest boundary or protected-file count mismatch")
    return raw


def read_manifest_bytes(path: Path) -> bytes:
    """Return exact original bytes; refuse incomplete or ambiguous packages."""
    try:
        raw = _bounded_file(path, MAX_DOCUMENT_BYTES)
        data = _toml(raw)
        if not data.keys() & INDEX_FIELDS:
            return raw
        if len(raw) > MAX_INDEX_BYTES:
            _fail("caller storage index exceeds its size bound")
        return _unpack(data, path)
    except OSError as exc:
        raise ManifestStorageError(
            f"cannot read caller manifest storage: {exc}"
        ) from exc


def load_manifest(path: Path) -> dict[str, Any]:
    return _toml(read_manifest_bytes(path))


def _gzip(raw: bytes) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(
        filename="", mode="wb", fileobj=output, mtime=0, compresslevel=9
    ) as stream:
        stream.write(raw)
    return output.getvalue()


def build_package(raw: bytes) -> dict[str, bytes]:
    """Package exact TOML bytes deterministically, without modifying the input."""
    if not 0 < len(raw) <= MAX_MANIFEST_BYTES:
        _fail("caller manifest exceeds its size bound")
    boundary_count, protected_count = _payload_shape(_toml(raw))
    pending = [raw]
    chunks = []
    while pending:
        chunk = pending.pop(0)
        compressed = _gzip(chunk)
        if len(compressed) > MAX_PART_BYTES:
            midpoint = len(chunk) // 2
            pending[0:0] = [chunk[:midpoint], chunk[midpoint:]]
        else:
            chunks.append((chunk, compressed))
        if len(pending) + len(chunks) > MAX_PARTS:
            _fail("caller manifest requires too many storage parts")
    lines = [
        "# Exact caller TOML bytes; use scripts/hepta_caller_manifest.py to inspect or edit.",
        f'storage_format = "{STORAGE_FORMAT}"',
        f"manifest_bytes = {len(raw)}",
        f'manifest_sha256 = "{_digest(raw)}"',
        f"boundary_count = {boundary_count}",
        f"protected_file_count = {protected_count}",
    ]
    result = {}
    for position, (chunk, compressed) in enumerate(chunks):
        relative = f"{PARTS_DIRECTORY}/part-{position:04d}.toml.gz"
        result[relative] = compressed
        lines.extend(
            [
                "",
                "[[part]]",
                f'path = "{relative}"',
                f"compressed_bytes = {len(compressed)}",
                f'compressed_sha256 = "{_digest(compressed)}"',
                f"raw_bytes = {len(chunk)}",
                f'raw_sha256 = "{_digest(chunk)}"',
            ]
        )
    result["CALLERS.toml"] = ("\n".join(lines) + "\n").encode("utf-8")
    if len(result["CALLERS.toml"]) > MAX_INDEX_BYTES:
        _fail("caller storage index exceeds its size bound")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("unpack", "pack"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("source", type=Path)
        subparser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "unpack":
            raw = read_manifest_bytes(args.source)
            with args.destination.open("xb") as stream:
                stream.write(raw)
            print(json.dumps({"bytes": len(raw), "sha256": _digest(raw)}))
        else:
            files = build_package(_bounded_file(args.source, MAX_MANIFEST_BYTES))
            args.destination.mkdir()
            for relative, raw in files.items():
                target = args.destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    stream.write(raw)
            print(json.dumps({"files": sorted(files)}))
    except (ManifestStorageError, OSError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
