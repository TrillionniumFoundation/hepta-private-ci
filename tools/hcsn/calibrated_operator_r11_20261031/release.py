"""Create, verify and restore a bounded, lossless R11 publication snapshot.

No source file is modified or deleted. Paths are relative to the R11 directory.
Content/numerics use their explicit publication manifests. Failed confirmation_01
includes every _work file. Other _work copies are excluded by the release contract.
Existing upstream archives remain archives; their own restore utilities are kept.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

MAX_FILE = 480000
MAX_PART = 400000
INDEX_TARGET = 300000
MANIFEST = "RELEASE_MANIFEST.json"
GROUPS = ("evidence/confirmation_01", "evidence/smoke_01", "audit/evidence/native_01")
LATE_FILES = {"README.md", "REPORT_ZH.md", "ACCEPTANCE.json"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+"\n").encode()


def safe(path):
    value = PurePosixPath(path)
    if value.is_absolute() or ".." in value.parts or not value.parts:
        raise ValueError(("Unsafe release path", path))
    return str(value)


def put(root, path, data):
    path = safe(path)
    if len(data) > MAX_FILE:
        raise ValueError(("Publication file exceeds limit", path, len(data)))
    target = root/path; target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != data:
            raise ValueError(("Conflicting publication bytes", path))
    else:
        with target.open("xb") as stream:
            stream.write(data)
    if target.read_bytes() != data:
        raise ValueError(("Write/readback mismatch", path))
    return dict(path=path, bytes=len(data), sha256=digest(data))


def source_files(source, content_stage):
    selected, excluded = {}, Counter()
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError(("Source symlink", str(path)))
        if not path.is_file():
            continue
        name = str(path.relative_to(source)); parts = PurePosixPath(name).parts
        if parts[0] in ("content", "numerics") or name in LATE_FILES:
            continue
        if "__pycache__" in parts or ("_work" in parts and not name.startswith("evidence/confirmation_01/")):
            excluded["/".join(parts[:2])] += 1; continue
        selected[name] = path.read_bytes()
    for prefix, folder, manifest_name in (
        ("content", content_stage, "DELIVERY_MANIFEST.json"),
        ("numerics", source/"numerics", "PUBLICATION_MANIFEST.json"),
    ):
        manifest = json.loads((folder/manifest_name).read_text())
        for row in manifest["files"]:
            name = safe(row["path"]); data = (folder/name).read_bytes()
            if len(data) != row["bytes"] or digest(data) != row["sha256"]:
                raise ValueError(("Lane publication identity mismatch", prefix, name))
            selected[f"{prefix}/{name}"] = data
        selected[f"{prefix}/{manifest_name}"] = (folder/manifest_name).read_bytes()
    return selected, dict(excluded)


def store_file(output, name, data):
    item = dict(path=name, bytes=len(data), sha256=digest(data))
    if len(data) <= MAX_FILE:
        put(output, name, data)
        return dict(**item, mode="direct", stored=name)
    codec = "identity" if name.endswith(".gz") else "gzip"
    packed = data if codec == "identity" else gzip.compress(data, mtime=0)
    prefix = f"release_parts/{digest(data)[:20]}_{PurePosixPath(name).name}"
    parts = []
    for offset in range(0, len(packed), MAX_PART):
        parts.append(put(output, f"{prefix}.part{offset//MAX_PART:04d}", packed[offset:offset+MAX_PART]))
    recovered = b"".join((output/p["path"]).read_bytes() for p in parts)
    if (gzip.decompress(recovered) if codec == "gzip" else recovered) != data:
        raise ValueError(("Split-file readback mismatch", name))
    return dict(**item, mode="parts", codec=codec, parts=parts)


def archive_group(output, group, files):
    records, archive_count = [], 0
    readable = {name: raw for name, raw in files.items()
                if PurePosixPath(name).name in ("SUMMARY.json", "STATISTICS.json")
                or (group == "evidence/smoke_01" and name == f"{group}/RESULTS.json")}
    for name, raw in readable.items():
        records.append(store_file(output, name, raw))
    pending = [(name, raw) for name, raw in sorted(files.items()) if name not in readable]

    def emit(items):
        nonlocal archive_count
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for name, raw in items:
                member = tarfile.TarInfo(name); member.size = len(raw); member.mode = 0o644; member.mtime = 0
                archive.addfile(member, io.BytesIO(raw))
        packed = gzip.compress(buffer.getvalue(), mtime=0)
        if len(packed) > MAX_PART:
            if len(items) == 1:
                records.append(store_file(output, items[0][0], items[0][1])); return
            middle = len(items)//2; emit(items[:middle]); emit(items[middle:]); return
        name = f"release_archives/{group.replace('/', '_')}/part{archive_count:04d}.tar.gz"
        archive_count += 1; put(output, name, packed)
        with tarfile.open(fileobj=io.BytesIO(packed), mode="r:gz") as archive:
            loaded = {member.name: archive.extractfile(member).read() for member in archive}
        if loaded != dict(items):
            raise ValueError(("Tar member readback mismatch", group))
        records.extend(dict(path=path, bytes=len(raw), sha256=digest(raw), mode="tar", archive=name, member=path)
                       for path, raw in items)

    block, size = [], 0
    for item in pending:
        block.append(item); size += len(item[1])
        if size >= 1500000:
            emit(block); block, size = [], 0
    if block:
        emit(block)
    return records, dict(original_files=len(files), original_bytes=sum(map(len, files.values())),
                         archive_files=archive_count, readable_files=len(readable), includes_work=group.endswith("confirmation_01"))


def write_index(output, records, sequence=0):
    parts, block = [], []
    for record in sorted(records, key=lambda x: x["path"]):
        trial = block+[record]
        if block and len(encoded(trial)) > INDEX_TARGET:
            parts.append(put(output, f"release_index/originals_{sequence:04d}.json", encoded(block)))
            sequence += 1; block = [record]
        else:
            block = trial
    if block:
        parts.append(put(output, f"release_index/originals_{sequence:04d}.json", encoded(block)))
    return parts


def get_records(root, manifest):
    records = []
    for part in manifest["original_indexes"]:
        raw = (root/safe(part["path"])).read_bytes()
        if digest(raw) != part["sha256"] or len(raw) != part["bytes"]:
            raise ValueError("Original index identity mismatch")
        records.extend(json.loads(raw))
    if len({r["path"] for r in records}) != len(records):
        raise ValueError("Duplicate original paths")
    return records


def finish(output, metadata, records):
    files = [dict(path=str(path.relative_to(output)), bytes=path.stat().st_size, sha256=digest(path.read_bytes()))
             for path in sorted(output.rglob("*")) if path.is_file() and path != output/MANIFEST]
    if any(row["bytes"] > MAX_FILE for row in files):
        raise ValueError("An index or publication file exceeds the size cap")
    manifest = dict(**metadata, files=files, file_count_including_manifest=len(files)+1,
                    original_file_count=len(records), original_bytes=sum(r["bytes"] for r in records),
                    max_file_bytes=max(r["bytes"] for r in files), total_bytes_excluding_manifest=sum(r["bytes"] for r in files))
    raw = encoded(manifest)
    if len(raw) > MAX_FILE:
        raise ValueError("Release manifest needs further sharding")
    (output/MANIFEST).write_bytes(raw)
    return manifest


def verify(root, destination=None):
    manifest = json.loads((root/MANIFEST).read_text())
    for row in manifest["files"]:
        raw = (root/safe(row["path"])).read_bytes()
        if len(raw) != row["bytes"] or digest(raw) != row["sha256"] or len(raw) > MAX_FILE:
            raise ValueError(("Publication identity mismatch", row["path"]))
    if destination is not None:
        destination.mkdir(parents=True, exist_ok=False)
    records = get_records(root, manifest); tar_records = {}

    def consume(record, raw):
        name = safe(record["path"])
        if len(raw) != record["bytes"] or digest(raw) != record["sha256"]:
            raise ValueError(("Original identity mismatch", name))
        if destination is not None:
            path = destination/name; path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(raw)
            if path.read_bytes() != raw:
                raise ValueError(("Restored byte mismatch", name))

    for record in records:
        if record["mode"] == "direct":
            consume(record, (root/safe(record["stored"])).read_bytes())
        elif record["mode"] == "parts":
            blocks = []
            for part in record["parts"]:
                raw = (root/safe(part["path"])).read_bytes()
                if len(raw) != part["bytes"] or digest(raw) != part["sha256"]:
                    raise ValueError("Split part identity mismatch")
                blocks.append(raw)
            raw = b"".join(blocks)
            consume(record, gzip.decompress(raw) if record["codec"] == "gzip" else raw)
        elif record["mode"] == "tar":
            tar_records.setdefault(record["archive"], {})[record["member"]] = record
        else:
            raise ValueError("Unknown original storage mode")
    for archive_path, expected in tar_records.items():
        seen = set()
        with tarfile.open(root/safe(archive_path), "r:gz") as archive:
            for member in archive:
                if not member.isfile() or member.name not in expected or member.name in seen:
                    raise ValueError("Unexpected archive member")
                consume(expected[member.name], archive.extractfile(member).read()); seen.add(member.name)
        if seen != set(expected):
            raise ValueError("Incomplete archive")
    return dict(passed=True, original_files_verified=len(records), original_bytes_verified=sum(r["bytes"] for r in records),
                publication_files=manifest["file_count_including_manifest"],
                publication_bytes=manifest["total_bytes_excluding_manifest"]+(root/MANIFEST).stat().st_size,
                maximum_file_bytes=max(manifest["max_file_bytes"], (root/MANIFEST).stat().st_size),
                manifest_sha256=digest((root/MANIFEST).read_bytes()), restored=destination is not None)


def pack(source, output, content_stage):
    if output.is_relative_to(source):
        raise ValueError("Release staging must be outside its source tree")
    output.mkdir(parents=True, exist_ok=False)
    selected, excluded = source_files(source, content_stage)
    records, groups = [], {}
    for group in GROUPS:
        subset = {name: raw for name, raw in selected.items() if name.startswith(group+"/")}
        grouped, groups[group] = archive_group(output, group, subset); records.extend(grouped)
        for name in subset:
            del selected[name]
    records.extend(store_file(output, name, raw) for name, raw in sorted(selected.items()))
    index = write_index(output, records)
    metadata = dict(schema="hcsn.r11.release.v1", created_at=datetime.now(timezone.utc).isoformat(),
        max_publication_file_bytes=MAX_FILE, max_new_archive_or_split_part_bytes=MAX_PART,
        original_indexes=index, archived_groups=groups, excluded_duplicate_work_or_cache_counts=excluded,
        late_root_reports_excluded=sorted(LATE_FILES),
        source_policy="Content/numerics explicit manifests; failed confirmation_01 includes _work. Existing lane archives preserved byte-for-byte; lane restore utilities remain available.",
        original_sources_modified=False)
    finish(output, metadata, records)
    return verify(output)


def append(root, source, paths):
    old = json.loads((root/MANIFEST).read_text()); verify(root)
    records = get_records(root, old); existing = {row["path"] for row in records}; additions = []
    for name in paths:
        name = safe(name)
        if name in existing:
            raise ValueError(("Append refuses to replace a frozen original", name))
        additions.append(store_file(root, name, (source/name).read_bytes()))
    metadata = {k: v for k, v in old.items() if k not in ("files", "file_count_including_manifest", "original_file_count", "original_bytes", "max_file_bytes", "total_bytes_excluding_manifest")}
    metadata["original_indexes"] += write_index(root, additions, len(old["original_indexes"]))
    metadata["appended_root_reports"] = sorted(set(metadata.get("appended_root_reports", [])) | set(paths))
    metadata["late_root_reports_excluded"] = sorted(set(metadata.get("late_root_reports_excluded", []))-set(paths))
    finish(root, metadata, records+additions)
    return verify(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("mode", choices=["pack", "verify", "restore", "append"])
    parser.add_argument("--source", type=Path); parser.add_argument("--output", type=Path)
    parser.add_argument("--release", type=Path); parser.add_argument("--content-stage", type=Path)
    parser.add_argument("--path", action="append", default=[])
    args = parser.parse_args()
    if args.mode == "pack":
        result = pack(args.source.resolve(), args.output.resolve(), args.content_stage.resolve())
    elif args.mode == "append":
        result = append(args.release.resolve(), args.source.resolve(), args.path)
    else:
        result = verify(args.release.resolve(), args.output.resolve() if args.mode == "restore" else None)
    print(json.dumps(result, indent=2, sort_keys=True))
