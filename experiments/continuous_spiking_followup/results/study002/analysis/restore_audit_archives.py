"""Restore exact study002 evidence from bounded, lossless gzip parts.

This transport utility imports no model code. All archive bytes and all existing
destinations are checked before any output is created. Existing identical files
are skipped; other existing files are never replaced. Run without concurrent
filesystem writers. The manifest is relative to the supplied study002 root.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import zlib


SCHEMA = "hcsn002-audit-archive-manifest-v1"
MAX_PART_BYTES = 512000
MAX_ORIGINAL_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_RECORDS = 10000


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def relative_path(value):
    if not isinstance(value, str) or not value or any(c in value for c in "\\:\0"):
        raise ValueError("invalid relative evidence path")
    path = PurePosixPath(value)
    if (not path.parts or path.is_absolute() or str(path) != value
            or any(part in {".", ".."} for part in path.parts)):
        raise ValueError("unsafe relative evidence path")
    return path


def identity(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("invalid SHA256 identity")
    return value


def size(value, maximum):
    if type(value) is not int or not 0 < value <= maximum:
        raise ValueError("invalid or excessive byte count")
    return value


def checked_path(root, name, create_parents=False):
    parts = relative_path(name).parts
    current = root
    for index, part in enumerate(parts):
        current = current / part
        final = index == len(parts) - 1
        if not final and create_parents:
            current.mkdir(exist_ok=True)
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode) or (not final and not stat.S_ISDIR(mode)):
            raise ValueError("symlink or non-directory evidence ancestor")
        if final and not stat.S_ISREG(mode):
            raise ValueError("evidence path is not an ordinary file")
    return current


def read_exact(path, expected_bytes, expected_sha):
    if path.is_symlink() or not path.is_file():
        raise ValueError("archive or original is not an ordinary file")
    with path.open("rb") as stream:
        raw = stream.read(expected_bytes + 1)
    if len(raw) != expected_bytes or sha256(raw) != expected_sha:
        raise ValueError("evidence size or SHA256 mismatch")
    return raw


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate manifest key")
        value[key] = item
    return value


def load_manifest(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("manifest must be an ordinary file")
    with path.open("rb") as stream:
        raw = stream.read(MAX_PART_BYTES + 1)
    if len(raw) > MAX_PART_BYTES:
        raise ValueError("manifest exceeds the publication limit")
    value = json.loads(raw, object_pairs_hook=unique_object)
    expected = identity(value.pop("manifest_sha256"))
    if sha256(canonical(value)) != expected or value["schema"] != SCHEMA:
        raise ValueError("manifest identity or schema mismatch")
    if value["root_scope"] != "study002" or value["compression"] != "gzip, mtime=0":
        raise ValueError("unsupported archive scope or encoding")
    archives, originals = value["archives"], value["originals"]
    if not isinstance(archives, dict) or not 0 < len(archives) <= MAX_RECORDS:
        raise ValueError("invalid archive inventory")
    if not isinstance(originals, list) or not 0 < len(originals) <= MAX_RECORDS:
        raise ValueError("invalid original inventory")
    part_paths = set()
    total = 0
    for key, entry in archives.items():
        if identity(key) != identity(entry["original_sha256"]):
            raise ValueError("archive key differs from original identity")
        total += size(entry["original_bytes"], MAX_ORIGINAL_BYTES)
        size(entry["compressed_bytes"], MAX_ORIGINAL_BYTES)
        identity(entry["compressed_sha256"])
        parts = entry["parts"]
        if not isinstance(parts, list) or not 0 < len(parts) <= 256:
            raise ValueError("invalid archive part inventory")
        for part in parts:
            name = str(relative_path(part["path"]))
            if name in part_paths:
                raise ValueError("duplicate archive part path")
            part_paths.add(name)
            size(part["bytes"], MAX_PART_BYTES)
            identity(part["sha256"])
        if sum(part["bytes"] for part in parts) != entry["compressed_bytes"]:
            raise ValueError("archive part sizes do not match")
    if total > MAX_TOTAL_BYTES:
        raise ValueError("total decompressed archive size exceeds the limit")
    original_paths, used, mapped_bytes = set(), set(), 0
    for entry in originals:
        name = str(relative_path(entry["path"]))
        key = identity(entry["sha256"])
        if name in original_paths or name in part_paths or key not in archives:
            raise ValueError("duplicate, colliding or unbound original path")
        original_paths.add(name)
        used.add(key)
        archive = archives[key]
        if (size(entry["bytes"], MAX_ORIGINAL_BYTES) != archive["original_bytes"]
                or entry["compressed_sha256"] != archive["compressed_sha256"]
                or entry["compressed_bytes"] != archive["compressed_bytes"]):
            raise ValueError("original and archive identities differ")
        mapped_bytes += entry["bytes"]
    if mapped_bytes > MAX_TOTAL_BYTES:
        raise ValueError("total mapped original size exceeds the limit")
    if used != set(archives):
        raise ValueError("archive has no mapped original")
    all_paths = original_paths | part_paths
    for name in all_paths:
        if any(str(parent) in all_paths for parent in PurePosixPath(name).parents):
            raise ValueError("file path is an ancestor of another file")
    value["manifest_sha256"] = expected
    return value


def decompress_archive(root, entry):
    compressed = b"".join(
        read_exact(checked_path(root, part["path"]), part["bytes"], part["sha256"])
        for part in entry["parts"]
    )
    if (len(compressed) != entry["compressed_bytes"]
            or sha256(compressed) != entry["compressed_sha256"]):
        raise ValueError("complete archive identity mismatch")
    if compressed[:3] != b"\x1f\x8b\x08" or compressed[4:8] != b"\0" * 4:
        raise ValueError("archive must be gzip with mtime=0")
    decoder = zlib.decompressobj(wbits=31)
    raw = decoder.decompress(compressed, entry["original_bytes"] + 1)
    if (not decoder.eof or decoder.unused_data or decoder.unconsumed_tail
            or len(raw) != entry["original_bytes"]
            or sha256(raw) != entry["original_sha256"]):
        raise ValueError("decompressed identity, length or stream boundary mismatch")
    return raw


def create_only(root, entry, raw):
    path = checked_path(root, entry["path"], create_parents=True)
    if path.exists():
        read_exact(path, entry["bytes"], entry["sha256"])
        return "skipped_identical"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".restore_audit_",
                                         delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        # Hard-link creation fails when any destination already exists; it never
        # replaces a file. The temporary belongs solely to this invocation.
        try:
            os.link(temporary, path)
        except FileExistsError:
            read_exact(checked_path(root, entry["path"]), entry["bytes"], entry["sha256"])
            return "skipped_identical"
        read_exact(path, entry["bytes"], entry["sha256"])
        return "created"
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def restore(study_root, manifest_path, verify_only=False):
    study_root = Path(study_root)
    if study_root.is_symlink() or not study_root.is_dir():
        raise ValueError("study root must be an existing ordinary directory")
    root = study_root.resolve()
    manifest_path = Path(manifest_path)
    try:
        name = manifest_path.absolute().relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("manifest must be inside the study root") from exc
    checked_path(root, name)
    manifest = load_manifest(manifest_path)
    if name in {entry["path"] for entry in manifest["originals"]}:
        raise ValueError("an original cannot overwrite the manifest")
    decoded = {key: decompress_archive(root, entry)
               for key, entry in manifest["archives"].items()}
    present = set()
    for entry in manifest["originals"]:
        path = checked_path(root, entry["path"])
        if path.exists():
            read_exact(path, entry["bytes"], entry["sha256"])
            present.add(entry["path"])
    statuses = []
    for entry in manifest["originals"]:
        status = "verified_existing" if entry["path"] in present else "verified_missing"
        if not verify_only:
            status = create_only(root, entry, decoded[entry["sha256"]])
        statuses.append({"path": entry["path"], "sha256": entry["sha256"],
                         "bytes": entry["bytes"], "status": status})
    return {"schema": "hcsn002-audit-archive-restoration-v1",
            "manifest_sha256": manifest["manifest_sha256"],
            "unique_archives_verified": len(decoded), "originals": statuses,
            "created": sum(row["status"] == "created" for row in statuses),
            "skipped_identical": sum(row["status"] == "skipped_identical" for row in statuses),
            "verify_only": bool(verify_only), "existing_files_overwritten": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(restore(args.study_root, args.manifest, args.verify_only), indent=2))
