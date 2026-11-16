"""Deterministic streaming archive writer with explicit output/disk budgets."""

import gzip
import hashlib
import os
from pathlib import Path
import tarfile
import tempfile

from archive_plan_v8 import (BLOCK, canonical, checked_open, digest, fingerprint,
    guard_output, hash_file, require, unchanged, validate_plan, write_new)
from archive_verify_v8 import verify_archive


def capacity(directory):
    value = os.statvfs(directory)
    uid = os.geteuid()
    free, available = value.f_bfree * value.f_frsize, value.f_bavail * value.f_frsize
    return {"effective_uid": uid, "f_bfree_bytes": free, "f_bavail_bytes": available,
            "effective_free_bytes": free if uid == 0 else available}


def capacity_probe(directory, reserve):
    before = capacity(directory)
    require(before["effective_free_bytes"] >= reserve + 65536, "insufficient effective free space and reserve")
    with tempfile.TemporaryFile(dir=directory) as stream:
        require(stream.write(b"\0" * 65536) == 65536, "capacity write probe incomplete")
        stream.flush()
        os.fsync(stream.fileno())
    return {"before": before, "after": capacity(directory), "actual_write_probe_bytes": 65536,
            "actual_write_probe_fsync_passed": True, "reserve_bytes": reserve}


def sync_directory(directory):
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class BoundedSink:
    def __init__(self, stream=None, directory=None, maximum=None, reserve=0):
        self.stream, self.directory, self.maximum, self.reserve = stream, directory, maximum, reserve
        self.bytes, self.hasher = 0, hashlib.sha256()

    def write(self, data):
        require(self.maximum is None or self.bytes + len(data) <= self.maximum, "explicit compressed output budget exceeded")
        if self.stream is not None:
            require(capacity(self.directory)["effective_free_bytes"] >= self.reserve + len(data),
                    "effective disk reserve would be consumed")
            require(self.stream.write(data) == len(data), "short compressed write")
        self.hasher.update(data)
        self.bytes += len(data)
        return len(data)

    def flush(self):
        if self.stream is not None:
            self.stream.flush()


class CheckedSource:
    def __init__(self, stream):
        self.stream, self.hasher, self.bytes = stream, hashlib.sha256(), 0

    def read(self, length):
        require(0 <= length <= BLOCK, "bounded archive source read required")
        data = self.stream.read(length)
        self.hasher.update(data)
        self.bytes += len(data)
        return data


def tar_info(name, size, mode, target=None):
    info = tarfile.TarInfo(name)
    info.mode, info.mtime, info.uid, info.gid = mode, 0, 0, 0
    info.uname = info.gname = ""
    if target is None:
        info.type, info.size = tarfile.REGTYPE, size
    else:
        info.type, info.linkname, info.size = tarfile.LNKTYPE, target, 0
    return info


def write_stream(plan, manifest, sink):
    import io
    roots = {row["label"]: Path(row["path"]) for row in plan["configuration"]["roots"]}
    with gzip.GzipFile(filename="", mode="wb", fileobj=sink, compresslevel=6, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT,
                          encoding="utf-8", errors="strict") as archive:
            archive.addfile(tar_info("MANIFEST.json", len(manifest), 0o644), io.BytesIO(manifest))
            for row in plan["members"]:
                path = roots[row["root"]] / row["relative_path"]
                if row["link_to"] is not None:
                    actual, _ = hash_file(path, row["source_stat"])
                    require(actual == row["sha256"], "hardlink source content changed")
                    archive.addfile(tar_info(row["member"], 0, row["archive_mode"], row["link_to"]))
                    continue
                stream, before = checked_open(path, row["source_stat"])
                with stream:
                    source = CheckedSource(stream)
                    archive.addfile(tar_info(row["member"], row["bytes"], row["archive_mode"]), source)
                    require(source.bytes == row["bytes"] and source.hasher.hexdigest() == row["sha256"]
                            and fingerprint(os.fstat(stream.fileno())) == before, "source changed during archive write")


def measure(plan_file, plan_sha256):
    plan, manifest = validate_plan(plan_file, plan_sha256, check_tools=True)
    unchanged(plan)
    sink = BoundedSink()
    write_stream(plan, manifest, sink)
    unchanged(plan)
    final_plan, final_manifest = validate_plan(plan_file, plan_sha256, check_tools=True)
    require(final_plan == plan and final_manifest == manifest, "approved plan changed during measurement")
    return {"schema": "hepta.evidence-archive-measurement.v8", "manifest_sha256": digest(manifest),
            "compressed_bytes": sink.bytes, "predicted_archive_sha256": sink.hasher.hexdigest(),
            "archive_file_created": False, "source_bytes_fully_rechecked": True}


def pack(plan_file, plan_sha256, output, maximum, reserve=64 << 20):
    require(type(maximum) is int and maximum > 0 and type(reserve) is int and reserve >= 0, "explicit output budget required")
    plan, manifest = validate_plan(plan_file, plan_sha256, check_tools=True)
    output = guard_output(plan["configuration"], output, (plan_file,))
    partial = output.with_name(output.name + ".partial")
    receipt_path = output.with_name(output.name + ".receipt.json")
    receipt_partial = output.with_name(output.name + ".receipt.json.partial")
    failure_path = output.with_name(output.name + ".failure.json")
    require(not any(p.exists() or p.is_symlink() for p in (output, partial, receipt_path, receipt_partial, failure_path)), "archive paths must be new")
    unchanged(plan)
    probe = capacity_probe(output.parent, reserve)
    try:
        with partial.open("xb") as stream:
            sink = BoundedSink(stream, output.parent, maximum, reserve)
            write_stream(plan, manifest, sink)
            stream.flush()
            os.fsync(stream.fileno())
        unchanged(plan)
        verification = verify_archive(partial, plan_file, plan_sha256, sink.hasher.hexdigest())
        require(verification["archive_bytes"] == sink.bytes, "independent compressed byte census differs")
        final_plan, final_manifest = validate_plan(plan_file, plan_sha256, check_tools=True)
        require(final_plan == plan and final_manifest == manifest, "approved plan changed before publication")
        unchanged(final_plan)
        os.link(partial, output)
        partial.unlink()
        sync_directory(output.parent)
        receipt = {"schema": "hepta.evidence-archive-publication.v8", "status": "PASS",
                   "output": str(output), "capacity_probe": probe, "capacity_after": capacity(output.parent),
                   "maximum_output_bytes": maximum, "verification": verification,
                   "writer_sources": plan["tool_sources"], "partial_archives_do_not_indicate_success": True,
                   "publication_commit_marker": str(receipt_path), "archive_alone_is_not_publication_success": True,
                   "scientific_verdict_from_archive": False}
        write_new(receipt_partial, canonical(receipt))
        os.link(receipt_partial, receipt_path)
        receipt_partial.unlink()
        sync_directory(output.parent)
        return receipt
    except BaseException as error:
        failure = {"schema": "hepta.evidence-archive-failure.v8", "status": "FAILED",
                   "error_type": type(error).__name__, "error": str(error), "manifest_sha256": plan_sha256,
                   "partial_retained": partial.exists(), "final_archive_exists": output.exists(),
                   "capacity": capacity(output.parent), "scientific_verdict_from_archive": False}
        try:
            write_new(failure_path, canonical(failure))
        except OSError:
            pass
        raise
