#!/usr/bin/env python3
"""Losslessly package only explicitly pinned, already retained executable bytes.

This is an archive operation, never a build, test, binary discovery, or capture.
An independently reviewed plan and a completed owned-process release proof are
required. Completion requires a successful export job and its completion.json.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import time

BLOCK = 1024 * 1024
PART_BYTES = 4 * 1024 * 1024
MAX_PLAN_BYTES = 2 * 1024 * 1024
MAX_MAP_BYTES = 1024 * 1024
MAX_SOURCE_TOTAL = 4 * 1024 * 1024 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def canonical_absolute(path):
    value = str(path)
    pure = PurePosixPath(value)
    require(pure.is_absolute() and pure.as_posix() == value and ".." not in pure.parts,
            "canonical absolute path required")
    return Path(value)


def metadata(info):
    return dict(device=info.st_dev, inode=info.st_ino, bytes=info.st_size,
                mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns,
                mode=stat.S_IMODE(info.st_mode), nlink=info.st_nlink,
                uid=info.st_uid, gid=info.st_gid)


def open_regular(path, maximum, exact=None):
    """Walk each directory with O_NOFOLLOW, then open one regular single-link file."""
    path = canonical_absolute(path)
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    descriptor = None
    try:
        for part in path.parts[1:-1]:
            next_directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                     dir_fd=directory)
            os.close(directory)
            directory = next_directory
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                             dir_fd=directory)
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                "regular single-link source required: " + str(path))
        require(0 <= info.st_size <= maximum and (exact is None or info.st_size == exact),
                "source size differs from exact plan: " + str(path))
        stream = os.fdopen(descriptor, "rb")
        descriptor = None
        return stream, metadata(info)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)


def actual_hash(path, maximum, exact=None, expected_metadata=None):
    stream, before = open_regular(path, maximum, exact)
    with stream:
        if expected_metadata is not None:
            require(before == expected_metadata, "source path/inode changed before repeated read")
        hasher, size = hashlib.sha256(), 0
        while True:
            block = stream.read(min(BLOCK, maximum - size + 1))
            if not block:
                break
            size += len(block)
            require(size <= maximum, "file grew beyond bound")
            hasher.update(block)
        after = metadata(os.fstat(stream.fileno()))
    require(before == after and size == before["bytes"], "file changed during actual read")
    return hasher.hexdigest(), before


def actual_small(path, maximum, expected):
    stream, before = open_regular(path, maximum)
    with stream:
        raw = stream.read(maximum + 1)
        after = metadata(os.fstat(stream.fileno()))
    require(before == after and len(raw) == before["bytes"] and digest(raw) == expected,
            "small pinned input changed or hash differs")
    return raw


class BoundedWriter:
    def __init__(self, stream, maximum):
        self.stream, self.maximum, self.length = stream, maximum, 0

    def write(self, raw):
        require(self.length + len(raw) <= self.maximum, "compressed output bound exceeded")
        count = self.stream.write(raw)
        require(count == len(raw), "short archive write")
        self.length += count
        return count

    def flush(self):
        self.stream.flush()


class HashingReader:
    def __init__(self, stream):
        self.stream, self.hasher, self.length, self.prefix = stream, hashlib.sha256(), 0, b""

    def read(self, size=-1):
        raw = self.stream.read(size)
        if len(self.prefix) < 4:
            self.prefix += raw[:4 - len(self.prefix)]
        self.length += len(raw)
        self.hasher.update(raw)
        return raw


def add_bytes(archive, name, raw):
    member = tarfile.TarInfo(name)
    member.size, member.mode, member.mtime = len(raw), 0o444, 0
    archive.addfile(member, io.BytesIO(raw))


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def validate_plan(raw):
    plan = json.loads(raw)
    require(plan["schema"] == "hepta-actual-retained-elf-export-plan-v1", "unknown plan schema")
    require(plan["phase"] in ("H1", "H2"), "explicit source phase required")
    require(GIT_SHA.fullmatch(plan["source_commit"]) and GIT_SHA.fullmatch(plan["source_tree"]),
            "full Git source identity required")
    require(plan["part_bytes"] == PART_BYTES and plan["native_reexecution"] is False,
            "part size or no-execution contract changed")
    root = canonical_absolute(plan["source_root"])
    names, sources, hashes = set(), set(), set()
    require(0 < len(plan["files"]) <= 32, "bounded explicit source inventory required")
    for row in plan["files"]:
        source = canonical_absolute(row["source_path"])
        require(source.is_relative_to(root) and source != root and "target" not in source.parts,
                "source must be a retained file inside the pinned evidence root")
        require(SHA256.fullmatch(row["sha256"]) and 4 <= row["bytes"] <= MAX_SOURCE_TOTAL,
                "exact ELF SHA/size required")
        expected_name = plan["phase"] + "/elf/" + row["sha256"] + ".elf"
        require(row["name"] == expected_name and row["name"] not in names and
                str(source) not in sources and row["sha256"] not in hashes, "duplicate or unsafe ELF entry")
        require(row["aliases"] and str(source) in row["aliases"], "selected source must be a retained alias")
        for alias in row["aliases"]:
            require(canonical_absolute(alias).is_relative_to(root), "alias outside pinned evidence root")
        names.add(row["name"])
        sources.add(str(source))
        hashes.add(row["sha256"])
    total = sum(row["bytes"] for row in plan["files"])
    require(total == plan["total_elf_bytes"] and total <= MAX_SOURCE_TOTAL, "exact total differs")
    require(plan["max_archive_bytes"] == total + 64 * 1024 * 1024, "container bound changed")
    require(plan["archive_name"] == plan["phase"] + "-actual-retained-elfs.tar.xz", "archive name differs")
    mapping = base64.b64decode(plan["source_map"]["data_base64"], validate=True)
    require(len(mapping) == plan["source_map"]["bytes"] <= MAX_MAP_BYTES and
            digest(mapping) == plan["source_map"]["sha256"], "pinned source mapping mismatch")
    return plan, mapping


def verify_archive(path, expected):
    seen = set()
    with tarfile.open(path, "r|xz") as archive:
        for member in archive:
            require(member.isfile() and member.name in expected and member.name not in seen,
                    "unexpected or nonregular archive member")
            reference = expected[member.name]
            require(member.size == reference["bytes"], "archive member size differs")
            hasher, size = hashlib.sha256(), 0
            with archive.extractfile(member) as stream:
                while True:
                    block = stream.read(BLOCK)
                    if not block:
                        break
                    hasher.update(block)
                    size += len(block)
            require(size == reference["bytes"] and hasher.hexdigest() == reference["sha256"],
                    "decompressed archive member differs")
            seen.add(member.name)
    require(seen == set(expected), "archive omitted required files")


def publish_without_overwrite(partial, final, maximum, expected_sha256, expected_bytes=None):
    before_hash, before = actual_hash(partial, maximum)
    require(before_hash == expected_sha256 and (expected_bytes is None or before["bytes"] == expected_bytes),
            "output changed before no-overwrite publication")
    os.link(partial, final, follow_symlinks=False)
    partial.unlink()
    after = metadata(final.stat(follow_symlinks=False))
    require(after["nlink"] == 1 and all(after[key] == before[key]
            for key in ("device", "inode", "bytes", "mtime_ns", "mode", "uid", "gid")),
            "published file changed")
    return before_hash, after


def export(plan_path, expected_plan, expected_exporter):
    started = time.monotonic()
    code_path = canonical_absolute(Path(__file__).absolute())
    code_raw = actual_small(code_path, MAX_PLAN_BYTES, expected_exporter)
    plan_raw = actual_small(canonical_absolute(plan_path), MAX_PLAN_BYTES, expected_plan)
    plan, mapping_raw = validate_plan(plan_raw)
    release = plan["release_prerequisite"]
    release_raw = actual_small(canonical_absolute(release["path"]), MAX_MAP_BYTES, release["sha256"])
    release_document = json.loads(release_raw)
    require(release_document["job_id"] == release["job_id"] and
            release_document["owned_processes_clear"] is True and release_document["failures"] == [] and
            release_document["processes_killed"] is False, "required owned-process release is absent")
    output = canonical_absolute(plan["output_directory"])
    require(output.parent.resolve(strict=True) == output.parent and not output.exists(),
            "fresh canonical output directory required")
    output.mkdir(mode=0o700)
    sync_directory(output.parent)
    partial = output / (plan["archive_name"] + ".partial")
    entries, expected_members = [], {}
    metadata_files = {
        "export-plan.json": plan_raw,
        "exporter.py": code_raw,
        plan["phase"] + "/original-source-map.json": mapping_raw,
        "owned-release-proof.json": release_raw,
    }
    with partial.open("xb") as stream:
        bounded = BoundedWriter(stream, plan["max_archive_bytes"])
        with lzma.LZMAFile(bounded, "w", preset=3) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.USTAR_FORMAT) as archive:
                for row in plan["files"]:
                    source, before = open_regular(Path(row["source_path"]), row["bytes"], row["bytes"])
                    with source:
                        reader = HashingReader(source)
                        member = tarfile.TarInfo(row["name"])
                        member.size, member.mode, member.mtime = row["bytes"], 0o444, 0
                        archive.addfile(member, reader)
                        extra = source.read(1)
                        after = metadata(os.fstat(source.fileno()))
                    require(before == after and not extra and reader.length == row["bytes"] and
                            reader.prefix == b"\x7fELF" and reader.hasher.hexdigest() == row["sha256"],
                            "actual retained ELF failed stable byte/hash binding")
                    entry = dict(row, first_read_metadata=before)
                    entries.append(entry)
                    expected_members[row["name"]] = {"bytes": row["bytes"], "sha256": row["sha256"]}
                # These are independent source reads, before any successful archive claim is written.
                for row in entries:
                    second_hash, second = actual_hash(Path(row["source_path"]), row["bytes"],
                                                       row["bytes"], row["first_read_metadata"])
                    require(second_hash == row["sha256"], "retained ELF changed on second actual read")
                    row["second_read_metadata"] = second
                    row["second_read_sha256"] = second_hash
                    row["other_aliases_reopened_by_this_export"] = False
                for name, raw in metadata_files.items():
                    add_bytes(archive, name, raw)
                    expected_members[name] = dict(bytes=len(raw), sha256=digest(raw))
                index = dict(schema="hepta-actual-retained-elf-archive-index-v1", phase=plan["phase"],
                    source_commit=plan["source_commit"], source_tree=plan["source_tree"],
                    plan_sha256=expected_plan, exporter_sha256=expected_exporter, files=entries,
                    total_actual_elf_bytes=plan["total_elf_bytes"],
                    selected_elf_sources_actually_read_twice=True, alias_paths_are_original_mapping_only=True,
                    embedded_metadata_files={name: expected_members[name] for name in metadata_files},
                    original_run_outcome=plan["original_run_outcome"], capture_limits=plan["capture_limits"],
                    archive_scope="Only the selected retained bytes; no new build, execution, capture, or missing-case attribution.",
                    native_reexecution=False)
                index_raw = encoded(index)
                add_bytes(archive, "export-index.json", index_raw)
                expected_members["export-index.json"] = dict(bytes=len(index_raw), sha256=digest(index_raw))
        stream.flush()
        os.fsync(stream.fileno())
    archive_hash, archive_before = actual_hash(partial, plan["max_archive_bytes"])
    verify_archive(partial, expected_members)
    parts, concatenated = [], hashlib.sha256()
    source, before = open_regular(partial, plan["max_archive_bytes"], archive_before["bytes"])
    require(before == archive_before, "archive changed before splitting")
    with source:
        offset = 0
        while offset < before["bytes"]:
            raw = source.read(min(PART_BYTES, before["bytes"] - offset))
            require(raw, "archive truncated during splitting")
            name = plan["archive_name"] + ".part-" + str(len(parts)).zfill(4)
            part = output / (name + ".partial")
            with part.open("xb") as destination:
                require(destination.write(raw) == len(raw), "short part write")
                destination.flush()
                os.fsync(destination.fileno())
            actual, info = actual_hash(part, PART_BYTES, len(raw))
            require(actual == digest(raw), "written part hash mismatch")
            reread, _ = open_regular(part, PART_BYTES, len(raw))
            with reread:
                recovered = reread.read(PART_BYTES + 1)
            require(len(recovered) == len(raw) and digest(recovered) == actual, "part changed during concatenation")
            concatenated.update(recovered)
            parts.append(dict(name=name, index=len(parts), offset=offset, bytes=len(raw), sha256=actual))
            offset += len(raw)
        require(not source.read(1) and metadata(os.fstat(source.fileno())) == before,
                "archive changed while splitting")
    require(concatenated.hexdigest() == archive_hash, "actual part concatenation mismatch")
    for row in entries:
        check, current = open_regular(Path(row["source_path"]), row["bytes"], row["bytes"])
        check.close()
        require(current == row["second_read_metadata"], "source identity changed before publication")
    # No source/inventory assertions remain after final paths are published.
    final_archive = output / plan["archive_name"]
    published_hash, published_metadata = publish_without_overwrite(
        partial, final_archive, plan["max_archive_bytes"], archive_hash, archive_before["bytes"])
    require(published_hash == archive_hash, "archive changed before publication")
    for row in parts:
        actual, _ = publish_without_overwrite(output / (row["name"] + ".partial"),
                                              output / row["name"], PART_BYTES, row["sha256"], row["bytes"])
        require(actual == row["sha256"], "part changed before publication")
    sync_directory(output)
    result = dict(schema="hepta-actual-retained-elf-export-completion-v1", status="COMPLETE", phase=plan["phase"],
        source_commit=plan["source_commit"], source_tree=plan["source_tree"], plan_sha256=expected_plan,
        exporter_sha256=expected_exporter, archive_path=str(final_archive), archive_sha256=archive_hash,
        archive_bytes=published_metadata["bytes"], archive_index_sha256=digest(index_raw),
        unique_actual_elfs=len(entries), total_actual_elf_bytes=plan["total_elf_bytes"],
        all_archive_members_independently_decompressed_and_hashed=True,
        selected_sources_actually_read_twice=True, unselected_aliases_reopened=False,
        all_parts_actually_reopened_and_hashed=True, actual_parts_concatenation_verified=True,
        parts=parts, native_reexecution=False, binary_rebuilt=False, capture_gaps_filled=False,
        original_run_outcome=plan["original_run_outcome"], capture_limits=plan["capture_limits"],
        release_proof_sha256=release["sha256"], elapsed_seconds=time.monotonic() - started,
        completed_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        consumer_contract="Require an authoritative successful export job, this COMPLETE marker, and archive/index/part SHA verification; filenames alone are not completion.")
    completion = output / "completion.json.partial"
    completion_raw = encoded(result)
    with completion.open("xb") as destination:
        destination.write(completion_raw)
        destination.flush()
        os.fsync(destination.fileno())
    publish_without_overwrite(completion, output / "completion.json", MAX_PLAN_BYTES,
                              digest(completion_raw), len(completion_raw))
    sync_directory(output)
    print(json.dumps(result, sort_keys=True), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--expected-exporter-sha256", required=True)
    args = parser.parse_args()
    require(SHA256.fullmatch(args.expected_plan_sha256) and SHA256.fullmatch(args.expected_exporter_sha256),
            "exact plan and exporter SHA256 required")
    export(args.plan, args.expected_plan_sha256, args.expected_exporter_sha256)


if __name__ == "__main__":
    main()
