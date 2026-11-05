#!/usr/bin/env python3
"""Cloud draft: H4 actual-byte archival with one exact complete H3 dependency.

This external post-terminal storage tool never runs native code or repairs
capture evidence. Actual inputs and the launch request are not frozen yet.
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
PINNED_PARENT = {
    "phase": "H3",
    "archive_bytes": 283427280,
    "archive_sha256": "5365fcf900781044108e9642ae02a110e4ac8d031d9ee516c4f0b0e471e1e773",
    "index_bytes": 294654,
    "index_sha256": "b023aca6ab2dccf4324dccab2e5319a00ef9b32773e0dc73127efc9af3caa002",
    "completion_sha256": "93d7bf08914054e4bcf05f17eea3cd5ef36fac9bbf0d1e601dda59084e758cd3",
    "plan_sha256": "7c140e2a83e9df657aff17c66bb1f307bb6b8a22db6cbba04e38841d7b9ef7a0",
    "exporter_sha256": "9eb404993262589a948a19946819e890ff15875bef1133eab5fe9cee6bb14f53",
    "source_commit": "6db78eca53a5acdda0d96873d3f4cd65863426f0",
    "source_tree": "e91f5994017fc5d2cfe58d405a20ee6ad9376772",
    "images": 11,
    "image_bytes": 1674575368,
    "members": 16,
}

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


def pinned_parent(spec):
    require(set(spec) == set(PINNED_PARENT) | {"archive_path", "completion_path"}, "one explicit parent only")
    require(all(spec[key] == value for key, value in PINNED_PARENT.items()), "parent differs from fixed complete H3 archive")
    canonical_absolute(spec["archive_path"])
    canonical_absolute(spec["completion_path"])


class BoundedHashReader(HashingReader):
    def __init__(self, stream, maximum):
        super().__init__(stream)
        self.maximum = maximum

    def read(self, size=-1):
        raw = super().read(size)
        require(self.length <= self.maximum, "archive grew while read")
        return raw


def read_verified_archive(path, size, expected_sha, expected_index, captures=()):
    """Verify compressed bytes before parsing, then hash every actual member."""
    require(0 < size <= MAX_SOURCE_TOTAL + 64 * BLOCK, "bounded complete archive required")
    first_sha, first = actual_hash(canonical_absolute(path), size, size)
    require(first_sha == expected_sha, "actual complete archive SHA mismatch")
    source, before = open_regular(canonical_absolute(path), size, size)
    require(before == first, "archive changed before independent parsing read")
    members, small, total = {}, {}, 0
    wanted = set(captures) | {"export-index.json"}
    require(len(wanted) <= 8, "bounded metadata capture required")
    with source:
        reader = BoundedHashReader(source, size)
        with tarfile.open(fileobj=reader, mode="r|xz") as archive:
            for member in archive:
                name = PurePosixPath(member.name)
                require(member.isfile() and not name.is_absolute() and name.as_posix() == member.name and
                        ".." not in name.parts and member.name not in members, "unsafe or repeated member")
                total += member.size
                require(len(members) < 64 and 0 <= member.size <= MAX_SOURCE_TOTAL and
                        total <= MAX_SOURCE_TOTAL + 16 * BLOCK, "archive member bounds exceeded")
                if member.name in wanted:
                    require(member.size <= MAX_PLAN_BYTES, "metadata exceeds bound")
                with archive.extractfile(member) as stream:
                    hasher, count, prefix, chunks = hashlib.sha256(), 0, b"", []
                    while True:
                        raw = stream.read(BLOCK)
                        if not raw:
                            break
                        count += len(raw)
                        require(count <= member.size, "member grew")
                        hasher.update(raw)
                        prefix = (prefix + raw[:4])[:4]
                        if member.name in wanted:
                            chunks.append(raw)
                    require(count == member.size, "truncated member")
                members[member.name] = dict(bytes=count, sha256=hasher.hexdigest(), elf_magic=prefix == b"\x7fELF")
                if member.name in wanted:
                    small[member.name] = b"".join(chunks)
        while reader.read(BLOCK):
            pass
        require(metadata(os.fstat(source.fileno())) == before and reader.length == size and
                reader.hasher.hexdigest() == expected_sha, "archive changed while independently parsed")
    require("export-index.json" in small and digest(small["export-index.json"]) == expected_index,
            "actual archive index SHA mismatch")
    return dict(members=members, small=small, index=json.loads(small["export-index.json"]),
                metadata=before, archive_sha256=expected_sha, archive_bytes=size)


def verify_member_inventory(actual, expected):
    require(set(actual) == set(expected), "archive member set differs from its exact index")
    for name, record in expected.items():
        require(actual[name]["bytes"] == record["bytes"] and actual[name]["sha256"] == record["sha256"],
                "actual member differs from index: " + name)


def verify_parent(spec):
    pinned_parent(spec)
    completion_raw = actual_small(canonical_absolute(spec["completion_path"]), MAX_PLAN_BYTES,
                                  spec["completion_sha256"])
    completion = json.loads(completion_raw)
    require(completion["status"] == "COMPLETE" and completion["phase"] == "H3" and
            completion["archive_bytes"] == spec["archive_bytes"] and
            completion["archive_sha256"] == spec["archive_sha256"] and
            completion["archive_index_sha256"] == spec["index_sha256"], "parent completion mismatch")
    actual = read_verified_archive(spec["archive_path"], spec["archive_bytes"],
                                   spec["archive_sha256"], spec["index_sha256"])
    index = actual["index"]
    require(len(actual["small"]["export-index.json"]) == spec["index_bytes"] and
            index["phase"] == "H3" and index["source_commit"] == spec["source_commit"] and
            index["source_tree"] == spec["source_tree"] and index["plan_sha256"] == spec["plan_sha256"] and
            index["exporter_sha256"] == spec["exporter_sha256"], "parent identity differs")
    require(not index.get("partial_prefix_representations") and not index.get("parent_reference") and
            not index.get("parents"), "parent must have complete images and no transitive dependency")
    rows = index["files"]
    require(len(rows) == spec["images"] and sum(row["bytes"] for row in rows) == spec["image_bytes"],
            "parent complete-image count/total differs")
    by_hash, expected = {}, dict(index["embedded_metadata_files"])
    for row in rows:
        require(SHA256.fullmatch(row["sha256"]) and row["name"] == "H3/elf/" + row["sha256"] + ".elf" and
                row["sha256"] not in by_hash and row["name"] not in expected and
                row["role"] in ("complete-recorded-test-image", "complete-live-daemon-image") and
                "representation" not in row, "parent row is not a unique directly embedded complete image")
        require(actual["members"].get(row["name"], {}).get("elf_magic") is True,
                "parent image lacks actual ELF bytes")
        by_hash[row["sha256"]] = row
        expected[row["name"]] = dict(bytes=row["bytes"], sha256=row["sha256"])
    expected["export-index.json"] = dict(bytes=spec["index_bytes"], sha256=spec["index_sha256"])
    require(len(actual["members"]) == spec["members"], "fixed parent member count differs")
    verify_member_inventory(actual["members"], expected)
    report = dict(archive_path=spec["archive_path"], archive_bytes=spec["archive_bytes"],
        archive_sha256=spec["archive_sha256"], index_sha256=spec["index_sha256"],
        actual_archive_metadata=actual["metadata"], complete_images=len(rows),
        all_actual_members=actual["members"], complete_parent_actually_rehashed=True,
        parent_native_outcome=index["original_run_outcome"], no_parent_native_credit_transferred=True)
    return dict(actual=actual, by_hash=by_hash, report=report, completion_raw=completion_raw)


def validate_plan(raw, parent):
    plan = json.loads(raw)
    require(plan["schema"] == "hepta-H4-reference-archive-plan-v1" and plan["phase"] == "H4",
            "explicit H4 reference plan required")
    require(plan["native_reexecution"] is False and plan["part_bytes"] == PART_BYTES and
            plan["transport_budget_seconds"] == 900, "storage-only original transport bounds changed")
    require(GIT_SHA.fullmatch(plan["source_commit"]) and GIT_SHA.fullmatch(plan["source_tree"]),
            "full actual H4 source identity required")
    pinned_parent(plan["parent"])
    mapping_raw = base64.b64decode(plan["source_map"]["data_base64"], validate=True)
    require(len(mapping_raw) == plan["source_map"]["bytes"] <= MAX_MAP_BYTES and
            digest(mapping_raw) == plan["source_map"]["sha256"], "exact original H4 inventory required")
    mapping = json.loads(mapping_raw)
    require(mapping["source_commit"] == plan["source_commit"] and mapping["source_tree"] == plan["source_tree"],
            "H4 source identity differs from its own inventory")
    require(mapping["partial_artifacts"] == [], "partial artifacts require separate explicit review, never complete references")
    rows, originals = plan["files"], mapping["images"]
    require(0 < len(rows) == len(originals) <= 32, "bounded exact H4 complete inventory required")
    require(len({row["sha256"] for row in originals}) == len(originals), "duplicate original complete SHA")
    originals_by_sha = {row["sha256"]: row for row in originals}
    root = canonical_absolute(plan["source_root"])
    names, selected, all_aliases, references = set(), set(), set(), 0
    new_bytes, logical_bytes = 0, 0
    for row in rows:
        require(SHA256.fullmatch(row["sha256"]) and 4 <= row["bytes"] <= MAX_SOURCE_TOTAL,
                "exact complete H4 SHA/size required")
        require(row["sha256"] in originals_by_sha, "image absent from actual H4 inventory")
        original = originals_by_sha[row["sha256"]]
        require(original["kind"] in ("test-image", "ordinary-daemon"), "partial/non-complete input refused")
        require(row["bytes"] == original["bytes"] and row["aliases"] == original["retained_aliases"] and
                row["original_actual_paths"] == original["actual_paths"] and
                row["original_observations"] == original["observations"], "H4 actual observation/alias binding differs")
        require(row["aliases"] and len(row["aliases"]) == len(set(row["aliases"])), "unique actual aliases required")
        source = canonical_absolute(row["source_path"])
        require(str(source) in row["aliases"] and source.is_relative_to(root) and source != root and
                "target" not in source.parts and str(source) not in selected, "exact unique H4 retained source required")
        require(row["name"] == "H4/elf/" + row["sha256"] + ".elf" and row["name"] not in names,
                "unique safe H4 logical image name required")
        for alias in row["aliases"]:
            require(canonical_absolute(alias).is_relative_to(root) and alias not in all_aliases,
                    "H4 retained alias repeated or outside source root")
            all_aliases.add(alias)
        for observation in row["original_observations"]:
            require(observation["retained_copy"] in row["aliases"] and
                    observation["source_commit"] == plan["source_commit"] and
                    observation["source_tree"] == plan["source_tree"], "observation belongs to another source/run path")
        if row["representation"] == "referenced-complete-image":
            require(row["sha256"] in parent["by_hash"], "reference is not a complete fixed-parent image")
            original_parent = parent["by_hash"][row["sha256"]]
            expected = dict(archive_sha256=plan["parent"]["archive_sha256"],
                archive_bytes=plan["parent"]["archive_bytes"], index_sha256=plan["parent"]["index_sha256"],
                member=original_parent["name"], bytes=row["bytes"], sha256=row["sha256"])
            require(row["bytes"] == original_parent["bytes"] and row["parent_reference"] == expected,
                    "partial, transitive, or different parent reference refused")
            references += 1
        elif row["representation"] == "embedded-complete-image":
            require("parent_reference" not in row, "embedded image cannot carry an alternate parent")
            new_bytes += row["bytes"]
        else:
            raise ValueError("unknown/partial image representation")
        names.add(row["name"])
        selected.add(str(source))
        logical_bytes += row["bytes"]
    require(references > 0, "no actual overlap: use the existing standalone exporter instead")
    require(logical_bytes == plan["total_actual_elf_bytes"] == mapping["complete_image_unique_bytes"] <= MAX_SOURCE_TOTAL,
            "H4 logical complete source total differs")
    require(len(all_aliases) == mapping["complete_retained_alias_count"], "original H4 alias count differs")
    require(new_bytes == plan["embedded_elf_bytes"] and logical_bytes - new_bytes == plan["referenced_elf_bytes"] and
            plan["max_archive_bytes"] == new_bytes + 64 * BLOCK, "physical/reference storage totals differ")
    require(plan["archive_name"] == "H4-actual-retained-image-references.tar.xz", "explicit dependency archive name required")
    outcome = {key: value for key, value in mapping.items() if key not in ("images", "source_commit", "source_tree")}
    outcome.update(result=mapping["status"], native_job_id=plan["release_prerequisite"]["job_id"])
    require(plan["original_run_outcome"] == outcome, "original H4 native evidence/outcome altered")
    return plan, mapping_raw


def verify_logical_views(index, child_members, parent):
    """Hashes here come from complete actual member reads in each package."""
    views = []
    for row in index["files"]:
        if row["representation"] == "embedded-complete-image":
            actual = child_members.get(row["name"])
            source = dict(kind="actual-child-member", member=row["name"])
        elif row["representation"] == "referenced-complete-image":
            reference = row["parent_reference"]
            require(reference["archive_sha256"] == PINNED_PARENT["archive_sha256"] and
                    reference["archive_bytes"] == PINNED_PARENT["archive_bytes"] and
                    reference["index_sha256"] == PINNED_PARENT["index_sha256"], "unknown/transitive logical parent")
            require(row["sha256"] in parent["by_hash"] and
                    reference["member"] == parent["by_hash"][row["sha256"]]["name"] and
                    reference["bytes"] == row["bytes"] and reference["sha256"] == row["sha256"],
                    "logical view does not name a complete exact parent image")
            actual = parent["actual"]["members"].get(reference["member"])
            source = dict(kind="actual-complete-parent-member", member=reference["member"],
                          archive_sha256=reference["archive_sha256"])
        else:
            raise ValueError("partial or unknown logical view")
        require(actual is not None and actual["bytes"] == row["bytes"] and
                actual["sha256"] == row["sha256"] and actual["elf_magic"] is True,
                "complete actual logical ELF view differs from the H4 source")
        require(row["first_read_metadata"] == row["second_read_metadata"] and
                row["first_read_metadata"]["bytes"] == row["bytes"] and
                row["second_read_sha256"] == row["sha256"] and
                row["other_aliases_reopened_by_this_export"] is False, "two original H4 complete reads required")
        views.append(dict(name=row["name"], bytes=row["bytes"], sha256=row["sha256"], source=source,
                          actual_member_bytes_fully_hashed=True, parent_native_credit_transferred=False))
    return views





def export(plan_path, expected_plan, expected_exporter):
    started = time.monotonic()
    code_path = canonical_absolute(Path(__file__).absolute())
    code_raw = actual_small(code_path, MAX_PLAN_BYTES, expected_exporter)
    plan_raw = actual_small(canonical_absolute(plan_path), MAX_PLAN_BYTES, expected_plan)
    preliminary = json.loads(plan_raw)
    parent = verify_parent(preliminary["parent"])
    plan, mapping_raw = validate_plan(plan_raw, parent)
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
        "H4/referenced-H3-index.json": parent["actual"]["small"]["export-index.json"],
        "H4/referenced-H3-completion.json": parent["completion_raw"],
        "H4/parent-archive-verification.json": encoded(parent["report"]),
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
                        if row["representation"] == "embedded-complete-image":
                            archive.addfile(member, reader)
                        else:
                            while reader.read(BLOCK):
                                pass
                        extra = source.read(1)
                        after = metadata(os.fstat(source.fileno()))
                    require(before == after and not extra and reader.length == row["bytes"] and
                            reader.prefix == b"\x7fELF" and reader.hasher.hexdigest() == row["sha256"],
                            "actual retained ELF failed stable byte/hash binding")
                    entry = dict(row, first_read_metadata=before)
                    entries.append(entry)
                    if row["representation"] == "embedded-complete-image":
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
                index = dict(schema="hepta-H4-dependent-retained-elf-index-v1", phase=plan["phase"],
                    source_commit=plan["source_commit"], source_tree=plan["source_tree"],
                    plan_sha256=expected_plan, exporter_sha256=expected_exporter, files=entries,
                    total_actual_elf_bytes=plan["total_actual_elf_bytes"],
                    embedded_elf_bytes=plan["embedded_elf_bytes"], referenced_elf_bytes=plan["referenced_elf_bytes"],
                    parent_identity=PINNED_PARENT, standalone_archive=False,
                    selected_elf_sources_actually_read_twice=True, alias_paths_are_original_mapping_only=True,
                    embedded_metadata_files={name: expected_members[name] for name in metadata_files},
                    original_run_outcome=plan["original_run_outcome"], capture_limits=plan["capture_limits"],
                    archive_scope="H4 actual bytes and one explicitly required complete H3 byte source; no new execution, capture repair, or transferred native credit.",
                    native_reexecution=False)
                index_raw = encoded(index)
                add_bytes(archive, "export-index.json", index_raw)
                expected_members["export-index.json"] = dict(bytes=len(index_raw), sha256=digest(index_raw))
        stream.flush()
        os.fsync(stream.fileno())
    archive_hash, archive_before = actual_hash(partial, plan["max_archive_bytes"])
    verified_child = read_verified_archive(partial, archive_before["bytes"], archive_hash, digest(index_raw))
    verify_member_inventory(verified_child["members"], expected_members)
    logical_views = verify_logical_views(verified_child["index"], verified_child["members"], parent)
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
    parent_check, current_parent = open_regular(canonical_absolute(plan["parent"]["archive_path"]),
                                               plan["parent"]["archive_bytes"], plan["parent"]["archive_bytes"])
    parent_check.close()
    require(current_parent == parent["actual"]["metadata"], "referenced parent changed before publication")
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
    result = dict(schema="hepta-H4-reference-export-completion-v1", status="COMPLETE_WITH_REFERENCED_PARENT", phase=plan["phase"],
        source_commit=plan["source_commit"], source_tree=plan["source_tree"], plan_sha256=expected_plan,
        exporter_sha256=expected_exporter, archive_path=str(final_archive), archive_sha256=archive_hash,
        archive_bytes=published_metadata["bytes"], archive_index_sha256=digest(index_raw),
        unique_actual_elfs=len(entries), total_actual_elf_bytes=plan["total_actual_elf_bytes"],
        embedded_elf_bytes=plan["embedded_elf_bytes"], referenced_elf_bytes=plan["referenced_elf_bytes"],
        unique_embedded_elfs=sum(row["representation"] == "embedded-complete-image" for row in entries),
        unique_referenced_elfs=sum(row["representation"] == "referenced-complete-image" for row in entries),
        parent_identity=PINNED_PARENT, standalone_archive=False, logical_complete_views=logical_views,
        actual_parent_archive_and_all_members_verified=True,
        all_archive_members_independently_decompressed_and_hashed=True,
        selected_sources_actually_read_twice=True, unselected_aliases_reopened=False,
        all_parts_actually_reopened_and_hashed=True, actual_parts_concatenation_verified=True,
        parts=parts, native_reexecution=False, binary_rebuilt=False, capture_gaps_filled=False,
        original_run_outcome=plan["original_run_outcome"], capture_limits=plan["capture_limits"],
        release_proof_sha256=release["sha256"], elapsed_seconds=time.monotonic() - started,
        completed_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        consumer_contract="Require authoritative archive success, this COMPLETE_WITH_REFERENCED_PARENT marker, the entire pinned H3 parent and H4 child plus all parts/member hashes, and verified H4 logical views. Child alone is incomplete; no native credit transfers.")
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


def verify_transport_parts(completion, directory):
    """Require all original parts, and hash their real byte concatenation."""
    directory = canonical_absolute(directory)
    require(directory.resolve(strict=True) == directory, "canonical actual parts directory required")
    rows = completion["parts"]
    require(isinstance(rows, list) and 0 < len(rows) <= 1041, "bounded complete part list required")
    archive_name = PurePosixPath(completion["archive_path"]).name
    digest_all, offset, names = hashlib.sha256(), 0, set()
    for number, row in enumerate(rows):
        expected = archive_name + ".part-" + str(number).zfill(4)
        require(row["index"] == number and row["offset"] == offset and row["name"] == expected and
                row["name"] not in names and 0 < row["bytes"] <= PART_BYTES and SHA256.fullmatch(row["sha256"]),
                "part coverage/name differs")
        if number < len(rows) - 1:
            require(row["bytes"] == PART_BYTES, "nonfinal part must retain original extent")
        source, before = open_regular(directory / expected, PART_BYTES, row["bytes"])
        with source:
            raw = source.read(PART_BYTES + 1)
            require(metadata(os.fstat(source.fileno())) == before and len(raw) == row["bytes"] and
                    digest(raw) == row["sha256"], "actual part size/hash changed")
        digest_all.update(raw)
        offset += len(raw)
        names.add(expected)
    require(offset == completion["archive_bytes"] and digest_all.hexdigest() == completion["archive_sha256"],
            "actual part concatenation differs from complete archive")
    return dict(parts_actually_read=len(rows), complete_bytes=offset,
                concatenated_sha256=digest_all.hexdigest(), scope="Every named original part actually read; no missing-part inference.")


def consume(parent_archive, parent_completion, parent_parts, child_archive, child_completion,
            child_parts, expected_child_completion, expected_exporter):
    """Verify the full byte closure; this never awards test/capture qualification."""
    code_raw = actual_small(canonical_absolute(Path(__file__).absolute()), MAX_PLAN_BYTES, expected_exporter)
    parent_spec = dict(PINNED_PARENT, archive_path=str(canonical_absolute(parent_archive)),
                       completion_path=str(canonical_absolute(parent_completion)))
    parent_raw = actual_small(canonical_absolute(parent_completion), MAX_PLAN_BYTES, PINNED_PARENT["completion_sha256"])
    parent_doc = json.loads(parent_raw)
    parent_parts_result = verify_transport_parts(parent_doc, parent_parts)
    parent = verify_parent(parent_spec)
    child_raw = actual_small(canonical_absolute(child_completion), MAX_PLAN_BYTES, expected_child_completion)
    child_doc = json.loads(child_raw)
    require(child_doc["schema"] == "hepta-H4-reference-export-completion-v1" and
            child_doc["status"] == "COMPLETE_WITH_REFERENCED_PARENT" and child_doc["phase"] == "H4" and
            child_doc["parent_identity"] == PINNED_PARENT and child_doc["standalone_archive"] is False and
            child_doc["native_reexecution"] is False and child_doc["binary_rebuilt"] is False and
            child_doc["capture_gaps_filled"] is False and child_doc["exporter_sha256"] == expected_exporter,
            "dependent child completion identity differs")
    child_parts_result = verify_transport_parts(child_doc, child_parts)
    child = read_verified_archive(child_archive, child_doc["archive_bytes"], child_doc["archive_sha256"],
        child_doc["archive_index_sha256"], captures=("export-plan.json", "exporter.py",
            "H4/original-source-map.json", "H4/referenced-H3-index.json",
            "H4/referenced-H3-completion.json", "owned-release-proof.json"))
    index = child["index"]
    require(index["schema"] == "hepta-H4-dependent-retained-elf-index-v1" and index["phase"] == "H4" and
            index["parent_identity"] == PINNED_PARENT and index["standalone_archive"] is False and
            index["exporter_sha256"] == expected_exporter, "child index dependency differs")
    require(child["small"]["exporter.py"] == code_raw and
            digest(child["small"]["export-plan.json"]) == child_doc["plan_sha256"] == index["plan_sha256"] and
            child["small"]["H4/referenced-H3-index.json"] == parent["actual"]["small"]["export-index.json"] and
            child["small"]["H4/referenced-H3-completion.json"] == parent_raw,
            "embedded exact code/plan/parent bytes differ")
    plan, mapping_raw = validate_plan(child["small"]["export-plan.json"], parent)
    require(child["small"]["H4/original-source-map.json"] == mapping_raw and
            index["source_commit"] == child_doc["source_commit"] == plan["source_commit"] and
            index["source_tree"] == child_doc["source_tree"] == plan["source_tree"] and
            index["original_run_outcome"] == child_doc["original_run_outcome"] == plan["original_run_outcome"],
            "independent H4 source/observations/native outcome changed")
    release_raw = child["small"]["owned-release-proof.json"]
    release = json.loads(release_raw)
    require(digest(release_raw) == plan["release_prerequisite"]["sha256"] == child_doc["release_proof_sha256"] and
            release["job_id"] == plan["release_prerequisite"]["job_id"] and
            release["owned_processes_clear"] is True and release["failures"] == [] and
            release["processes_killed"] is False, "original H4 exact release differs")
    require(len(index["files"]) == len(plan["files"]), "missing logical complete image")
    for actual, planned in zip(index["files"], plan["files"], strict=True):
        require(all(actual.get(key) == value for key, value in planned.items()),
                "H4 actual path/alias/FD/case observation differs from frozen inventory")
    expected = dict(index["embedded_metadata_files"])
    for row in index["files"]:
        if row["representation"] == "embedded-complete-image":
            require(row["name"] not in expected, "payload shadows metadata")
            expected[row["name"]] = dict(bytes=row["bytes"], sha256=row["sha256"])
        else:
            require(row["name"] not in child["members"], "referenced image unexpectedly represented as local payload")
    expected["export-index.json"] = dict(bytes=len(child["small"]["export-index.json"]),
                                          sha256=child_doc["archive_index_sha256"])
    verify_member_inventory(child["members"], expected)
    views = verify_logical_views(index, child["members"], parent)
    require(views == child_doc["logical_complete_views"] and
            sum(row["bytes"] for row in views) == index["total_actual_elf_bytes"] == child_doc["total_actual_elf_bytes"],
            "final actual logical closure differs")
    for actual, path, expected_size in [(parent["actual"], parent_archive, PINNED_PARENT["archive_bytes"]),
                                       (child, child_archive, child_doc["archive_bytes"])]:
        check, current = open_regular(canonical_absolute(path), expected_size, expected_size)
        check.close()
        require(current == actual["metadata"], "archive identity changed before closure result")
    return dict(schema="H4-complete-parent-and-child-consumption-v1", status="VERIFIED_COMPLETE_BYTE_CLOSURE",
        parent_archive_sha256=PINNED_PARENT["archive_sha256"], parent_index_sha256=PINNED_PARENT["index_sha256"],
        child_archive_sha256=child_doc["archive_sha256"], child_index_sha256=child_doc["archive_index_sha256"],
        parent_parts=parent_parts_result, child_parts=child_parts_result, complete_logical_views=views,
        source_commit=plan["source_commit"], source_tree=plan["source_tree"], original_native_outcome=plan["original_run_outcome"],
        h4_original_observations_preserved=True, native_qualification_awarded=False, capture_gaps_filled=False,
        consumer_scope="Both whole packages, every original part/member and each H4 complete logical image hash verified. This checks bytes and original record equality; per-case FD/process attribution and native acceptance remain independent gates.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    exporter = sub.add_parser("export")
    exporter.add_argument("--plan", required=True)
    exporter.add_argument("--expected-plan-sha256", required=True)
    exporter.add_argument("--expected-exporter-sha256", required=True)
    consumer = sub.add_parser("consume")
    for name in ("parent-archive", "parent-completion", "parent-parts", "child-archive",
                 "child-completion", "child-parts", "expected-child-completion-sha256", "expected-exporter-sha256"):
        consumer.add_argument("--" + name, required=True)
    args = parser.parse_args()
    require(SHA256.fullmatch(args.expected_exporter_sha256), "exact exporter bytes required")
    if args.operation == "export":
        require(SHA256.fullmatch(args.expected_plan_sha256), "exact plan bytes required")
        export(args.plan, args.expected_plan_sha256, args.expected_exporter_sha256)
    else:
        require(SHA256.fullmatch(args.expected_child_completion_sha256), "exact child completion required")
        result = consume(args.parent_archive, args.parent_completion, args.parent_parts,
            args.child_archive, args.child_completion, args.child_parts,
            args.expected_child_completion_sha256, args.expected_exporter_sha256)
        print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()


