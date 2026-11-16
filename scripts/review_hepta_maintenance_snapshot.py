#!/usr/bin/env python3
"""Review an exact read-only copy, omitting only two explicitly empty WAL files.

The source tree is opened read-only and never chmodded, checkpointed or opened
by SQLite. Stop its writers before use. The new snapshot and report must be
outside it. Only file bytes and stable metadata are compared; access times may
advance on filesystems that cannot suppress them. This is postprocessing, not
part of the frozen worker, and proves no actual runtime transport.
"""

import argparse
from datetime import datetime, timezone
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import time

EMPTY_WAL = {"memory/owner.sqlite-wal", "predictor/owner.sqlite-wal"}
VERIFIER_SHA256 = "899723e758d8e89cb59c8fd25f7c734a1e39a829e49029f216a371a4d3527bd5"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def metadata(info):
    return dict(
        device=info.st_dev,
        inode=info.st_ino,
        mode=stat.S_IMODE(info.st_mode),
        bytes=info.st_size,
        links=info.st_nlink,
        mtime_ns=info.st_mtime_ns,
        ctime_ns=info.st_ctime_ns,
    )


def checked_path(value):
    path = Path(os.path.abspath(value))
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode), "symlink path refused: " + str(part))
    return path


def open_readonly(name, *, dir_fd=None, directory=False):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    if directory:
        flags |= os.O_DIRECTORY
    noatime = getattr(os, "O_NOATIME", 0)
    try:
        return os.open(name, flags | noatime, dir_fd=dir_fd)
    except OSError as error:
        if not noatime or error.errno not in (errno.EPERM, errno.EACCES):
            raise
        return os.open(name, flags, dir_fd=dir_fd)


def inventory(root, *, copy_to=None):
    """Hash every regular file via no-follow descriptors; optionally copy bytes."""
    files, directories = {}, {}

    def walk(descriptor, relative):
        before = os.fstat(descriptor)
        require(stat.S_ISDIR(before.st_mode), "source entry is not a directory")
        directories[relative or "."] = metadata(before)
        with os.scandir(descriptor) as iterator:
            entries = sorted(
                (entry.name, entry.stat(follow_symlinks=False)) for entry in iterator
            )
        for basename, info in entries:
            name = basename if not relative else relative + "/" + basename
            require(not stat.S_ISLNK(info.st_mode), "symlink refused: " + name)
            if stat.S_ISDIR(info.st_mode):
                child = open_readonly(basename, dir_fd=descriptor, directory=True)
                try:
                    require(
                        metadata(os.fstat(child)) == metadata(info),
                        "directory changed: " + name,
                    )
                    if copy_to is not None:
                        (copy_to / name).mkdir(mode=0o700)
                    walk(child, name)
                finally:
                    os.close(child)
                continue
            require(stat.S_ISREG(info.st_mode), "nonregular file refused: " + name)
            source = open_readonly(basename, dir_fd=descriptor)
            target = None
            try:
                opened = os.fstat(source)
                require(
                    stat.S_ISREG(opened.st_mode) and metadata(opened) == metadata(info),
                    "file changed before capture: " + name,
                )
                if copy_to is not None:
                    require(
                        not name.endswith("-wal") or opened.st_size == 0,
                        "nonempty WAL refused: " + name,
                    )
                    if name not in EMPTY_WAL:
                        target = os.open(
                            copy_to / name,
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                            0o600,
                        )
                hasher, count = hashlib.sha256(), 0
                while block := os.read(source, 1024 * 1024):
                    hasher.update(block)
                    count += len(block)
                    if target is not None:
                        offset = 0
                        while offset < len(block):
                            written = os.write(target, block[offset:])
                            require(written > 0, "snapshot write did not progress")
                            offset += written
                require(
                    metadata(os.fstat(source)) == metadata(opened)
                    and count == opened.st_size,
                    "file changed during capture: " + name,
                )
                files[name] = {**metadata(opened), "sha256": hasher.hexdigest()}
                if target is not None:
                    os.fchmod(target, (stat.S_IMODE(opened.st_mode) & 0o555) | 0o400)
                    os.fsync(target)
            finally:
                if target is not None:
                    os.close(target)
                os.close(source)
        require(
            metadata(os.fstat(descriptor)) == metadata(before),
            "directory changed during capture: " + (relative or "."),
        )

    descriptor = open_readonly(root, directory=True)
    try:
        walk(descriptor, "")
    finally:
        os.close(descriptor)
    return dict(files=files, directories=directories)


def byte_records(manifest):
    return {
        name: {key: item[key] for key in ("bytes", "sha256")}
        for name, item in manifest["files"].items()
    }


def review_snapshot(source_directory, snapshot_dir, output):
    source, snapshot, output = map(
        checked_path, (source_directory, snapshot_dir, output)
    )
    require(source.is_dir(), "source directory is missing")
    require(
        snapshot.parent.is_dir() and output.parent.is_dir(),
        "snapshot and report parents must exist",
    )
    require(
        not snapshot.exists() and not output.exists(),
        "snapshot and report must both be new",
    )
    require(
        not snapshot.is_relative_to(source) and not output.is_relative_to(source),
        "snapshot/report cannot write inside source",
    )
    require(
        not source.is_relative_to(snapshot) and not output.is_relative_to(snapshot),
        "report and source must be outside snapshot",
    )
    verifier = (
        Path(__file__)
        .with_name("verify_hepta_maintenance_cycle.py")
        .resolve(strict=True)
    )
    started = time.perf_counter()
    report = dict(
        schema="hepta.maintenance-readonly-snapshot-review.v1",
        status="FAIL",
        created_utc=datetime.now(timezone.utc).isoformat(),
        source_directory=str(source),
        snapshot_directory=str(snapshot),
        postprocessor_sha256=sha(Path(__file__).read_bytes()),
        original_verifier_path=str(verifier),
        original_verifier_expected_sha256=VERIFIER_SHA256,
        source_unchanged_verified=None,
        snapshot_unchanged_during_review=None,
        source_access="read-only descriptors; no source writes, chmod, SQLite open or checkpoint",
        metadata_scope="file/directory identity, mode, size, links, mtime/ctime; access time excluded",
        snapshot_mode_policy="retain read/execute bits, add owner read/traverse, remove all write bits",
        actual_runtime_transport_verified=False,
        training_or_inference_executed=False,
        fixture_compile_executed=False,
        scope="copied retained-original consistency only; no producer authenticity, transport or task-benefit claim",
    )
    before = None
    stage = "source_inventory"
    try:
        before = inventory(source)
        report["source_before"] = before
        stage = "wal_admission"
        for name, record in before["files"].items():
            require(
                not name.endswith("-wal") or record["bytes"] == 0,
                "nonempty WAL refused: " + name,
            )
        omitted = sorted(EMPTY_WAL & before["files"].keys())
        report["omitted_files"] = [
            {
                "path": name,
                **before["files"][name],
                "reason": "explicitly permitted zero-byte WAL; no database frame discarded",
            }
            for name in omitted
        ]
        stage = "verifier_identity"
        report["original_verifier_sha256"] = sha(verifier.read_bytes())
        require(
            report["original_verifier_sha256"] == VERIFIER_SHA256,
            "frozen verifier source differs",
        )
        stage = "exact_copy"
        snapshot.mkdir(mode=0o700)
        during = inventory(source, copy_to=snapshot)
        report["source_during_copy"] = during
        after_copy = inventory(source)
        report["source_after_copy"] = after_copy
        require(
            before == during == after_copy, "source changed before/during/after copy"
        )
        for name, info in sorted(
            before["directories"].items(),
            key=lambda item: item[0].count("/"),
            reverse=True,
        ):
            (snapshot / name).chmod((info["mode"] & 0o555) | 0o500)
        copied = inventory(snapshot)
        report["snapshot_before_review"] = copied
        expected = {
            name: record
            for name, record in byte_records(before).items()
            if name not in omitted
        }
        require(
            byte_records(copied) == expected
            and copied["directories"].keys() == before["directories"].keys(),
            "snapshot differs beyond permitted empty WAL omission",
        )
        require(
            all(
                info["mode"] & 0o222 == 0
                for group in copied.values()
                for info in group.values()
            ),
            "snapshot is not read-only",
        )
        stage = "original_readonly_review"
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location(
            "frozen_maintenance_readonly_verifier", verifier
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        report["review"] = module.review(snapshot)
        require(
            report["review"]["status"] == "READ_ONLY_CONSISTENCY_PASS",
            "original verifier did not pass",
        )
        require(
            report["review"]["verifier_sha256"]
            == VERIFIER_SHA256
            == sha(verifier.read_bytes()),
            "verifier changed during review",
        )
        stage = "post_review_invariance"
        after_review = inventory(source)
        snapshot_after = inventory(snapshot)
        report["source_after_review"] = after_review
        report["snapshot_after_review"] = snapshot_after
        report["source_unchanged_verified"] = before == after_review
        report["snapshot_unchanged_during_review"] = copied == snapshot_after
        require(
            report["source_unchanged_verified"]
            and report["snapshot_unchanged_during_review"],
            "source or snapshot changed during review",
        )
        require(
            sha(Path(__file__).read_bytes()) == report["postprocessor_sha256"],
            "postprocessor source changed",
        )
        report.update(
            status="READ_ONLY_SNAPSHOT_CONSISTENCY_PASS",
            copied_files=len(copied["files"]),
            omitted_files_count=len(omitted),
            preserved_shm_files=sorted(
                name for name in copied["files"] if name.endswith("-shm")
            ),
        )
    except Exception as error:
        report["failure_stage"] = stage
        report["error"] = type(error).__name__ + ": " + str(error)
        try:
            report["source_after_failure"] = inventory(source)
            report["source_unchanged_verified"] = (
                None if before is None else before == report["source_after_failure"]
            )
        except Exception as final_error:
            report["source_after_failure_error"] = (
                type(final_error).__name__ + ": " + str(final_error)
            )
    report["wall_seconds"] = time.perf_counter() - started
    with output.open("xb") as stream:
        stream.write(encoded(report))
        stream.flush()
        os.fsync(stream.fileno())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_directory", type=Path)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = review_snapshot(args.source_directory, args.snapshot_dir, args.output)
    print(
        json.dumps(
            {
                key: report.get(key)
                for key in (
                    "status",
                    "error",
                    "source_unchanged_verified",
                    "snapshot_unchanged_during_review",
                    "copied_files",
                    "omitted_files_count",
                    "actual_runtime_transport_verified",
                )
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "READ_ONLY_SNAPSHOT_CONSISTENCY_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
