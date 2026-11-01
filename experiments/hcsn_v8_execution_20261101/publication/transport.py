"""Byte-exact transport for oversized evidence, including compressed originals.

Original byte chunks are individually gzip-wrapped with mtime zero. Restoration
concatenates their uncompressed bytes; it never rewrites an original gzip/NPZ.
This is for a controlled local destination, not a hostile concurrent filesystem.
"""

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import tempfile


SCHEMA = "hcsn-v8-byte-transport.v1"
RAW_CHUNK_BYTES = 400000
PUBLISHED_PART_LIMIT = 512000


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            result.update(chunk)
    return result.hexdigest()


def relative(value):
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value
            or "\x00" in value or value.startswith("/")):
        raise ValueError("Unsafe relative path")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("Unsafe path component")
    return PurePosixPath(*parts)


def checked_path(root, value):
    path = root
    for component in relative(value).parts:
        path = path / component
        if path.is_symlink():
            raise ValueError("Symlink refused: " + str(path))
    return path


def absolute_root(path):
    path = Path(os.path.abspath(path))
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("Root path contains a symlink")
    if path.exists() and not path.is_dir():
        raise ValueError("Root path is not a directory")
    return path


def gzip_chunk(raw):
    stream = io.BytesIO()
    with gzip.GzipFile(fileobj=stream, mode="wb", filename="", compresslevel=9, mtime=0) as wrapped:
        wrapped.write(raw)
    result = stream.getvalue()
    if len(result) >= PUBLISHED_PART_LIMIT:
        raise ValueError("Wrapped part exceeds publication bound")
    return result


def pack(root, scope, output, threshold=450000):
    root, output = absolute_root(root), absolute_root(output)
    scoped = checked_path(root, scope)
    if not scoped.is_dir() or not output.is_relative_to(scoped):
        raise ValueError("Output must be inside the declared existing namespace")
    if type(threshold) is not int or threshold < 1:
        raise ValueError("Threshold must be a positive integer")
    manifest_path = output / "MANIFEST.json"
    if manifest_path.exists():
        raise FileExistsError("A transport manifest already exists")
    originals = []
    for path in sorted(scoped.rglob("*")):
        if path.is_relative_to(output) or "__pycache__" in path.parts:
            continue
        if path.is_symlink():
            raise ValueError("Source symlink refused: " + str(path))
        if path.is_file() and path.stat().st_size > threshold:
            originals.append(path)
    output.mkdir(parents=True, exist_ok=True)
    (output / "parts").mkdir(exist_ok=True)
    entries = []
    for original in originals:
        original = checked_path(root, original.relative_to(root).as_posix())
        original_sha = digest(original)
        original_size = original.stat().st_size
        parts, observed, total = [], hashlib.sha256(), 0
        with original.open("rb") as stream:
            while raw := stream.read(RAW_CHUNK_BYTES):
                observed.update(raw)
                total += len(raw)
                part_name = f"parts/{original_sha}.{len(parts):04d}.gz"
                wrapped = gzip_chunk(raw)
                target = checked_path(output, part_name)
                if target.exists():
                    if target.read_bytes() != wrapped:
                        raise ValueError("Conflicting transport part")
                else:
                    with target.open("xb") as destination:
                        destination.write(wrapped)
                parts.append({"path": part_name, "bytes": len(wrapped),
                              "sha256": hashlib.sha256(wrapped).hexdigest(),
                              "raw_bytes": len(raw), "raw_sha256": hashlib.sha256(raw).hexdigest()})
        if observed.hexdigest() != original_sha or total != original_size:
            raise ValueError("Original changed during packing")
        entries.append({"path": original.relative_to(root).as_posix(), "bytes": total,
                        "sha256": original_sha, "parts": parts})
    manifest = {"schema": SCHEMA, "scope": str(relative(scope)),
                "format": "Each gzip part wraps an unchanged slice of original bytes; concatenate decoded parts",
                "originals_untouched": True, "threshold_bytes": threshold,
                "raw_chunk_bytes": RAW_CHUNK_BYTES, "gzip_mtime": 0,
                "file_count": len(entries), "original_total_bytes": sum(e["bytes"] for e in entries),
                "files": entries}
    with manifest_path.open("x") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    unique_parts = {part["path"]: part for entry in entries for part in entry["parts"]}
    return {"manifest": str(manifest_path), "files": len(entries), "unique_parts": len(unique_parts),
            "original_bytes": manifest["original_total_bytes"],
            "published_part_bytes": sum(p["bytes"] for p in unique_parts.values()),
            "maximum_part_bytes": max((p["bytes"] for p in unique_parts.values()), default=0)}


def validated_manifest(manifest_path):
    manifest_path = Path(os.path.abspath(manifest_path))
    base = absolute_root(manifest_path.parent)
    if manifest_path.is_symlink() or manifest_path.stat().st_size > 10485760:
        raise ValueError("Invalid manifest file")
    document = json.loads(manifest_path.read_text())
    if document.get("schema") != SCHEMA or document.get("raw_chunk_bytes") != RAW_CHUNK_BYTES:
        raise ValueError("Unsupported transport format")
    scope = relative(document["scope"])
    entries = document["files"]
    if not isinstance(entries, list) or len(entries) > 10000:
        raise ValueError("Invalid original file inventory")
    seen, parts = set(), {}
    for entry in entries:
        original = relative(entry["path"])
        if not original.is_relative_to(scope) or entry["path"] in seen:
            raise ValueError("Original escapes scope or occurs twice")
        seen.add(entry["path"])
        if type(entry["bytes"]) is not int or entry["bytes"] < 1:
            raise ValueError("Invalid original length")
        if not isinstance(entry["parts"], list) or not entry["parts"]:
            raise ValueError("Missing original chunks")
        for part in entry["parts"]:
            if (type(part["raw_bytes"]) is not int or not 1 <= part["raw_bytes"] <= RAW_CHUNK_BYTES
                    or type(part["bytes"]) is not int or not 1 <= part["bytes"] < PUBLISHED_PART_LIMIT):
                raise ValueError("Invalid transport chunk length")
            name = str(relative(part["path"]))
            if not name.startswith("parts/"):
                raise ValueError("Chunk is outside the transport parts directory")
            if name in parts and parts[name] != part:
                raise ValueError("Conflicting shared chunk declarations")
            parts[name] = part
        if sum(p["raw_bytes"] for p in entry["parts"]) != entry["bytes"]:
            raise ValueError("Original length differs from chunk lengths")
    if document["file_count"] != len(entries) or document["original_total_bytes"] != sum(e["bytes"] for e in entries):
        raise ValueError("Manifest totals disagree with originals")
    # Validate every compressed part before writing any restored originals.
    for name, part in parts.items():
        path = checked_path(base, name)
        if not path.is_file() or path.stat().st_size != part["bytes"] or digest(path) != part["sha256"]:
            raise ValueError("Transport part identity mismatch: " + name)
    return base, document


def restore(manifest_path, destination):
    base, document = validated_manifest(manifest_path)
    destination = absolute_root(destination)
    for entry in document["files"]:
        path = checked_path(destination, entry["path"])
        if path.exists() and (not path.is_file() or path.stat().st_size != entry["bytes"] or digest(path) != entry["sha256"]):
            raise FileExistsError("Different existing destination bytes: " + str(path))
        for parent in path.parents:
            if parent == destination:
                break
            if parent.exists() and not parent.is_dir():
                raise FileExistsError("Destination ancestor is not a directory")
    installed = reused = 0
    for entry in document["files"]:
        target = checked_path(destination, entry["path"])
        if target.exists():
            reused += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".transport-", dir=target.parent)
        temporary = Path(temporary_name)
        try:
            combined, total = hashlib.sha256(), 0
            with os.fdopen(fd, "wb") as output:
                for part in entry["parts"]:
                    part_path = checked_path(base, part["path"])
                    with gzip.open(part_path, "rb") as wrapped:
                        raw = wrapped.read(RAW_CHUNK_BYTES + 1)
                    if len(raw) != part["raw_bytes"] or hashlib.sha256(raw).hexdigest() != part["raw_sha256"]:
                        raise ValueError("Decoded chunk identity mismatch")
                    output.write(raw)
                    combined.update(raw)
                    total += len(raw)
            if total != entry["bytes"] or combined.hexdigest() != entry["sha256"]:
                raise ValueError("Reassembled original identity mismatch")
            checked_path(destination, entry["path"])
            # Atomic no-overwrite install; a new concurrent conflict is refused.
            os.link(temporary, target)
            installed += 1
        finally:
            temporary.unlink(missing_ok=True)
    return {"schema": SCHEMA, "destination": str(destination), "installed_files": installed,
            "identical_existing_files": reused, "verified_original_bytes": document["original_total_bytes"],
            "originals_sha256_verified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    packing = sub.add_parser("pack")
    packing.add_argument("--root", type=Path, required=True)
    packing.add_argument("--scope", required=True)
    packing.add_argument("--output", type=Path, required=True)
    packing.add_argument("--threshold", type=int, default=450000)
    restoring = sub.add_parser("restore")
    restoring.add_argument("--manifest", type=Path, required=True)
    restoring.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    result = (pack(args.root, args.scope, args.output, args.threshold) if args.command == "pack"
              else restore(args.manifest, args.destination))
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
