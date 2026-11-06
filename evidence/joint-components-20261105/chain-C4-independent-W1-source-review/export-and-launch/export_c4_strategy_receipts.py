#!/usr/bin/env python3
"""Export completed C4 strategy receipts, streaming every original byte.

This is an archive operation only. It runs after H1 and the remaining synthetic
measurement window, never concurrently with either. It does not rebuild,
resample, rerun readers, edit source, or synthesize empty stdout/stderr files.
"""
from __future__ import annotations

import hashlib
import io
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile
import time

BASE = Path("/home/qian-qi/work/chain-joint-20261105-93bfc-w1-native-C4")
COMMIT = "8df4b21d893906570d48f5beafabb3b31e0aefbc"
TREE = "6f5aaa2af0432e27e24b6bd2ad18013ab4423d14"
PHASES = (
    ("legal-v3", "w1-legal-strategy-v3",
     "9fb57646c5cb5f1e7f7ddf393dff2e87678c105c3c8f6a32a024113172ea8243",
     "7f4a596357d7908605f13135b8e5be61ac3d7cb554887ec4d205708bbca36716"),
    ("reused-v3", "w1-actual-reuse-v3",
     "4a9dfc5816609ced333757f18e89b277084fe61ecd7996ac7ae9024fdd6eedb8",
     "001298287ac8fc831b1adbd8df85364df509bac5829fad597c02757dc30f5dba"),
    ("false-trace-full-limb", "w1-full-limb-reuse-v1",
     "1bbdf2343a4ea70e33f9d05916b8e5e6619c7140063004e909000f379ed2a592",
     "512542b54ea8d02b367e1a065b76e299761f1188226075177d64686695f9d887"),
)
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_BYTES = MAX_TOTAL_BYTES + 64 * 1024 * 1024
SMALL_JSON_BYTES = 16 * 1024 * 1024
BLOCK_BYTES = 1024 * 1024


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def metadata(value):
    return dict(device=value.st_dev, inode=value.st_ino, bytes=value.st_size,
                mtime_ns=value.st_mtime_ns, ctime_ns=value.st_ctime_ns,
                mode=stat.S_IMODE(value.st_mode), nlink=value.st_nlink)


def open_regular(path, max_bytes=MAX_FILE_BYTES):
    if path.resolve() != path:
        raise ValueError("canonical, nonsymlink source required: " + str(path))
    stream = os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb")
    info = os.fstat(stream.fileno())
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or not 0 <= info.st_size <= max_bytes):
        stream.close()
        raise ValueError("bounded single-link regular source required: " + str(path))
    return stream, metadata(info)


def hash_actual(path, max_bytes=MAX_FILE_BYTES):
    stream, before = open_regular(path, max_bytes=max_bytes)
    hasher, length = hashlib.sha256(), 0
    with stream:
        while True:
            part = stream.read(BLOCK_BYTES)
            if not part:
                break
            hasher.update(part)
            length += len(part)
        after = metadata(os.fstat(stream.fileno()))
    if before != after or length != before["bytes"]:
        raise ValueError("source changed during actual read: " + str(path))
    return hasher.hexdigest(), before


def small_actual(path, expected=None):
    stream, before = open_regular(path)
    if before["bytes"] > SMALL_JSON_BYTES:
        stream.close()
        raise ValueError("small JSON bound exceeded")
    with stream:
        raw = stream.read(SMALL_JSON_BYTES + 1)
        after = metadata(os.fstat(stream.fileno()))
    if before != after or len(raw) != before["bytes"]:
        raise ValueError("source changed during small read")
    if expected is not None and sha(raw) != expected:
        raise ValueError("previously captured manifest hash mismatch: " + str(path))
    return raw


def safe_relative(value):
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(x in ("", ".", "..") for x in path.parts):
        raise ValueError("unsafe original artifact name")
    if path.as_posix() != value:
        raise ValueError("noncanonical original artifact name")
    return path


class HashingReader:
    def __init__(self, stream):
        self.stream = stream
        self.hasher = hashlib.sha256()
        self.length = 0

    def read(self, size=-1):
        data = self.stream.read(size)
        self.hasher.update(data)
        self.length += len(data)
        return data


def archive_sources(destination, entries, document):
    """Open each source, stream/hash into tar, and reopen/hash after finalization."""
    partial = destination.with_name(destination.name + ".partial")
    if destination.exists() or partial.exists():
        raise ValueError("fresh export path required; no overwrite")
    index = []
    with partial.open("xb") as output:
        with lzma.LZMAFile(output, "w", preset=3) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as archive:
                for entry in sorted(entries, key=lambda row: row["name"]):
                    stream, before = open_regular(Path(entry["source_path"]))
                    with stream:
                        wrapped = HashingReader(stream)
                        member = tarfile.TarInfo(entry["name"])
                        member.size, member.mode, member.mtime = before["bytes"], 0o600, 0
                        archive.addfile(member, wrapped)
                        # Even a zero-byte file is actually opened and read.
                        extra = stream.read(1)
                        after = metadata(os.fstat(stream.fileno()))
                    digest = wrapped.hasher.hexdigest()
                    if (before != after or extra or wrapped.length != before["bytes"]
                            or digest != entry["expected_sha256"]
                            or (entry.get("expected_bytes") is not None
                                and wrapped.length != entry["expected_bytes"])):
                        raise ValueError("original raw failed stable-byte binding: " + entry["name"])
                    index.append(dict(name=entry["name"], source_path=entry["source_path"],
                                      sha256=digest, **before))
                index_document = dict(document, files=index,
                    all_files_actually_opened_and_read=True,
                    empty_actual_files=sum(row["bytes"] == 0 for row in index),
                    uncompressed_source_bytes=sum(row["bytes"] for row in index))
                index_raw = (json.dumps(index_document, indent=2, sort_keys=True) + "\n").encode()
                member = tarfile.TarInfo("export-index.json")
                member.size, member.mode, member.mtime = len(index_raw), 0o600, 0
                archive.addfile(member, io.BytesIO(index_raw))
    # Independent second reads reject moving receipts, including changed empty files.
    for row in index:
        digest, actual = hash_actual(Path(row["source_path"]))
        if digest != row["sha256"] or any(row[k] != v for k, v in actual.items()):
            raise ValueError("source changed after archive finalization: " + row["name"])
    # Hash the independently bounded container before publishing a final path.
    # link() fails if another file appeared at destination; it cannot overwrite it.
    digest, hashed_metadata = hash_actual(partial, max_bytes=MAX_ARCHIVE_BYTES)
    os.link(partial, destination, follow_symlinks=False)
    partial.unlink()
    archive_metadata = metadata(destination.stat(follow_symlinks=False))
    if (archive_metadata["nlink"] != 1 or any(archive_metadata[key] != hashed_metadata[key]
            for key in ("device", "inode", "bytes", "mtime_ns", "mode"))):
        raise ValueError("archive identity changed while publishing")
    return dict(archive_path=str(destination), archive_sha256=digest,
        archive_bytes=archive_metadata["bytes"], archive_metadata=archive_metadata,
        index_sha256=sha(index_raw), source_files=len(index), files=len(index) + 1,
        uncompressed_source_bytes=index_document["uncompressed_source_bytes"],
        empty_actual_files=index_document["empty_actual_files"],
        all_files_actually_opened_and_read=True, all_sources_reopened_and_rehashed=True,
        archive_fully_hashed_before_final_path=True, final_path_published_without_overwrite=True)


def main():
    started = time.monotonic()
    if BASE.resolve() != BASE:
        raise ValueError("canonical C4 evidence directory required")
    entries, seen, phases = [], set(), []
    total = 0

    def add(name, path, expected, expected_bytes=None):
        nonlocal total
        safe_relative(name)
        if name in seen or not path.is_relative_to(BASE):
            raise ValueError("duplicate or out-of-base archive source")
        if not isinstance(expected, str) or len(expected) != 64:
            raise ValueError("original SHA256 required")
        stream, info = open_regular(path)
        stream.close()
        total += info["bytes"]
        if total > MAX_TOTAL_BYTES:
            raise ValueError("fixed 2 GiB export bound exceeded; originals retained")
        seen.add(name)
        entries.append(dict(name=name, source_path=str(path),
                            expected_sha256=expected, expected_bytes=expected_bytes))

    for phase, receipt, outer_sha, inner_sha in PHASES:
        directory = BASE / phase
        outer_raw = small_actual(directory / "manifest.json", outer_sha)
        outer = json.loads(outer_raw)
        if ((outer.get("commit"), outer.get("tree"), outer.get("passed")) != (COMMIT, TREE, True)
                or not outer.get("completed_utc")
                or outer.get("source_before") is None
                or outer.get("source_before") != outer.get("source_after")):
            raise ValueError("exact completed C4 outer receipt required")
        add(phase + "/manifest.json", directory / "manifest.json", outer_sha, len(outer_raw))
        expected_outer_names = {"manifest.json"}
        for observation in outer["observations"]:
            for channel in ("stdout", "stderr"):
                row = observation[channel]
                name = row["path"]
                safe_relative(name)
                if "/" in name:
                    raise ValueError("outer capture filename must remain flat")
                add(phase + "/" + name, directory / name, row["sha256"], row["bytes"])
                expected_outer_names.add(name)
        for field in ("source_before", "source_after"):
            name = field.replace("_", "-") + ".json"
            raw = small_actual(directory / name)
            if json.loads(raw) != outer[field]:
                raise ValueError("outer source JSON differs from its real manifest")
            add(phase + "/" + name, directory / name, sha(raw), len(raw))
            expected_outer_names.add(name)
        actual_outer_names = {path.name for path in directory.iterdir() if path.is_file()}
        if actual_outer_names != expected_outer_names:
            raise ValueError("unregistered outer files: " + phase)

        original = directory / "original" / receipt
        if outer["original_receipt"]["path"] != str(original):
            raise ValueError("original receipt path changed")
        inner_raw = small_actual(original / "manifest.json", inner_sha)
        inner = json.loads(inner_raw)
        if (inner["result"] != "PASS" or inner["source_before"] != inner["source_after"]
                or (inner["source_before"]["commit"], inner["source_before"]["tree"]) != (COMMIT, TREE)
                or inner["binary_sha256_before"] != inner["binary_sha256_after"]):
            raise ValueError("exact completed original C4 receipt required")
        if outer["original_receipt"]["manifest_sha256"] != inner_sha:
            raise ValueError("outer-to-original manifest binding mismatch")
        prefix = phase + "/original/" + receipt
        add(prefix + "/manifest.json", original / "manifest.json", inner_sha, len(inner_raw))
        for name, expected in sorted(inner["artifact_sha256"].items()):
            relative = safe_relative(name)
            add(prefix + "/" + name, original.joinpath(*relative.parts), expected)
        actual_names = set()
        for path in original.rglob("*"):
            if path.is_symlink():
                raise ValueError("symlink inside original receipt")
            if path.is_file():
                actual_names.add(path.relative_to(original).as_posix())
        if actual_names != set(inner["artifact_sha256"]) | {"manifest.json"}:
            raise ValueError("unregistered original artifact")
        phases.append(dict(phase=phase, outer_manifest_sha256=outer_sha,
            original_manifest_sha256=inner_sha, original_result=inner["result"],
            binary_sha256_before=inner["binary_sha256_before"],
            binary_sha256_after=inner["binary_sha256_after"],
            source_before=inner["source_before"], source_after=inner["source_after"]))
    annotations = {
        "legal-v3-reader-summary.json": "883900f8437f801194a0dabf3a8dfb941f4142434342622ce90b20b1e9910e15",
        "C4-cost-window-release.json": "75c29fd18ec6ba30ac80a749dc5c94540285cfdd38f79b2d82eb77845df6b7ce",
    }
    for name, expected in annotations.items():
        add("annotations/" + name, BASE / name, expected)
    document = dict(schema="trnm-c4-original-strategy-raw-export-v1", commit=COMMIT, tree=TREE,
        phases=phases, native_or_reader_reexecuted=False, source_modified=False,
        compression="xz preset 3; archive operation after all scheduled measurement windows",
        export_bounds=dict(max_source_file_bytes=MAX_FILE_BYTES, max_total_source_bytes=MAX_TOTAL_BYTES,
                           max_archive_bytes=MAX_ARCHIVE_BYTES),
        scope="complete original files and retained ELF; archive checks are not new native measurements")
    result = archive_sources(BASE / "C4-strategy-receipts.tar.xz", entries, document)
    result.update(schema="trnm-c4-strategy-export-summary-v1", commit=COMMIT, tree=TREE,
        phases=phases, elapsed_seconds=time.monotonic() - started,
        completed_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        native_or_reader_reexecuted=False)
    with (BASE / "C4-strategy-raw-export.json").open("x") as output:
        json.dump(result, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()

