"""Create a local, complete inventory of the three explicitly authorized roots.

The production CLI has no configurable scan roots and performs no upload,
compression, extraction, or copying of evidence. All regular files are included,
including failures, raw media, weights, and checkpoints. Every symlink and special
file is rejected; directory-descriptor-relative opens cannot follow a swapped
symlink. Producers must be quiescent: this is a verified metadata census, not an
atomic filesystem snapshot. Initial/final census and per-read metadata changes
cause failure instead of publication of a successful inventory.

Example, only after all experiment timing has finished::

    python -m experiments.multimodal_output_portfolio.abc_recovery.evidence_inventory \
        --output /workspace/scratch/2b3c256bef7d/evidence-inventory-001.json

The output must be a new direct child of the task workspace, outside scan roots.
"""

import argparse
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time
import uuid


TASK_WORKSPACE = Path("/workspace/scratch/2b3c256bef7d")
TASK_DIRECTORY_NAMES = ("abc2-runs", "abc2-assets", "runtime-receipts")
CHUNK_BYTES = 1024 * 1024


class InventoryError(RuntimeError):
    """The requested complete, stable, bounded inventory could not be established."""


def _signature(info):
    return {"device": info.st_dev, "inode": info.st_ino, "mode": info.st_mode,
            "links": info.st_nlink, "size_bytes": info.st_size,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}


def _directory_flags():
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise InventoryError("This inventory requires POSIX no-follow directory opens")
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


@contextmanager
def _workspace_descriptor():
    """Open each absolute path component without traversing a symbolic link."""
    if not TASK_WORKSPACE.is_absolute() or ".." in TASK_WORKSPACE.parts:
        raise InventoryError("The task workspace must be an absolute canonical path")
    with ExitStack() as stack:
        descriptor = os.open("/", _directory_flags())
        stack.callback(os.close, descriptor)
        for component in TASK_WORKSPACE.parts[1:]:
            descriptor = os.open(component, _directory_flags(), dir_fd=descriptor)
            stack.callback(os.close, descriptor)
        yield descriptor


def _snapshot(workspace_descriptor):
    """Include empty directories and every entry, with no filename exclusions."""
    result = {}

    def visit(descriptor, relative):
        before = _signature(os.fstat(descriptor))
        result[relative] = before
        for name in sorted(os.listdir(descriptor)):
            child = f"{relative}/{name}"
            info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                raise InventoryError(f"Symbolic link refused: {child}")
            if stat.S_ISDIR(info.st_mode):
                child_descriptor = os.open(name, _directory_flags(), dir_fd=descriptor)
                try:
                    if _signature(os.fstat(child_descriptor)) != _signature(info):
                        raise InventoryError(f"Directory changed while opening: {child}")
                    visit(child_descriptor, child)
                finally:
                    os.close(child_descriptor)
            elif stat.S_ISREG(info.st_mode):
                result[child] = _signature(info)
            else:
                raise InventoryError(f"Non-regular evidence entry refused: {child}")
        if _signature(os.fstat(descriptor)) != before:
            raise InventoryError(f"Directory changed during census: {relative}")

    for name in TASK_DIRECTORY_NAMES:
        descriptor = os.open(name, _directory_flags(), dir_fd=workspace_descriptor)
        try:
            visit(descriptor, name)
        finally:
            os.close(descriptor)
    return result


def _hash_file(workspace_descriptor, relative, expected):
    """Stream only the initially observed regular inode, with bounded memory."""
    with ExitStack() as stack:
        descriptor, current = workspace_descriptor, []
        components = relative.split("/")
        for component in components[:-1]:
            current.append(component)
            descriptor = os.open(component, _directory_flags(), dir_fd=descriptor)
            stack.callback(os.close, descriptor)
            if _signature(os.fstat(descriptor)) != expected["/".join(current)]:
                raise InventoryError(f"Directory changed before hashing: {'/'.join(current)}")
        file_descriptor = os.open(components[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                                  dir_fd=descriptor)
        stack.callback(os.close, file_descriptor)
        before = _signature(os.fstat(file_descriptor))
        if before != expected[relative] or not stat.S_ISREG(before["mode"]):
            raise InventoryError(f"File changed before hashing: {relative}")
        checksum, read_bytes = hashlib.sha256(), 0
        while block := os.read(file_descriptor, CHUNK_BYTES):
            checksum.update(block)
            read_bytes += len(block)
        if _signature(os.fstat(file_descriptor)) != before or read_bytes != before["size_bytes"]:
            raise InventoryError(f"File changed while hashing: {relative}")
        return checksum.hexdigest()


def _require_same_census(expected, actual):
    if actual != expected:
        changed = sorted(name for name in expected.keys() | actual.keys() if expected.get(name) != actual.get(name))
        raise InventoryError("Evidence changed during inventory: " + ", ".join(changed[:5]))


def _report(entries, census, started_wall, started_cpu):
    roots = {name: {"file_count": 0, "total_bytes": 0} for name in TASK_DIRECTORY_NAMES}
    runs = {name: {"file_count": 0, "total_bytes": 0} for name, value in census.items()
            if name.startswith("abc2-runs/") and name.count("/") == 1 and stat.S_ISDIR(value["mode"])}
    for entry in entries:
        parts = entry["relative_path"].split("/")
        roots[parts[0]]["file_count"] += 1
        roots[parts[0]]["total_bytes"] += entry["size_bytes"]
        if parts[0] == "abc2-runs":
            run = "/".join(parts[:2]) if len(parts) > 2 else "abc2-runs/(root-files)"
            row = runs.setdefault(run, {"file_count": 0, "total_bytes": 0})
            row["file_count"] += 1
            row["total_bytes"] += entry["size_bytes"]
    return {"schema": "hepta.abc.local-evidence-inventory.v1", "status": "complete",
            "workspace": str(TASK_WORKSPACE), "scan_roots": list(TASK_DIRECTORY_NAMES),
            "files": entries, "directories": sorted(name for name, info in census.items() if stat.S_ISDIR(info["mode"])),
            "by_root": roots, "by_run": dict(sorted(runs.items())), "file_count": len(entries),
            "total_bytes": sum(row["size_bytes"] for row in entries),
            "size_semantics": "Logical bytes per listed path; hard links are not deduplicated",
            "census_sha256": hashlib.sha256(json.dumps(census, sort_keys=True).encode()).hexdigest(),
            "scope": "All regular files; no filename exclusions; no evidence copied, packed, or uploaded",
            "consistency": "Quiescent producers required; all metadata census and per-read checks must match; not an atomic filesystem snapshot",
            "completed_unix_ns": time.time_ns(),
            "scan_cost": {"wall_ns": time.perf_counter_ns() - started_wall,
                          "cpu_ns": time.process_time_ns() - started_cpu,
                          "scope": "Initial census, streamed hashes, and first final census; publication cost is in CLI receipt"}}


def write_inventory(output):
    """Publish a new local manifest for exactly the three hard-coded task roots.

    Failure never overwrites an existing manifest or evidence. A failed write
    can retain a small ``.partial-*`` manifest, which is not a complete inventory.
    """
    output = Path(output)
    if not output.is_absolute() or output.parent != TASK_WORKSPACE or output.name in TASK_DIRECTORY_NAMES:
        raise InventoryError("Output must be a new file directly in the task workspace, outside the three scan roots")
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    source = Path(__file__).read_bytes()
    with _workspace_descriptor() as workspace:
        try:
            os.stat(output.name, dir_fd=workspace, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise InventoryError("Output already exists; no overwrite is permitted")
        original_workspace = os.fstat(workspace)
        census = _snapshot(workspace)
        entries = [{"relative_path": name, "size_bytes": info["size_bytes"],
                    "sha256": _hash_file(workspace, name, census)}
                   for name, info in sorted(census.items()) if stat.S_ISREG(info["mode"])]
        _require_same_census(census, _snapshot(workspace))
        report = _report(entries, census, started_wall, started_cpu)
        report["inventory_script_sha256"] = hashlib.sha256(source).hexdigest()
        payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
        temporary = f".{output.name}.partial-{uuid.uuid4().hex}"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600, dir_fd=workspace)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        _require_same_census(census, _snapshot(workspace))
        if Path(__file__).read_bytes() != source:
            raise InventoryError("Inventory script changed during execution")
        with _workspace_descriptor() as reopened:
            current = os.fstat(reopened)
            if (current.st_dev, current.st_ino) != (original_workspace.st_dev, original_workspace.st_ino):
                raise InventoryError("Workspace path changed during inventory")
        os.link(temporary, output.name, src_dir_fd=workspace, dst_dir_fd=workspace, follow_symlinks=False)
        os.unlink(temporary, dir_fd=workspace)
        os.fsync(workspace)
    return {"status": "complete", "output": str(output), "sha256": hashlib.sha256(payload).hexdigest(),
            "file_count": report["file_count"], "total_bytes": report["total_bytes"],
            "inventory_call_wall_ns": time.perf_counter_ns() - started_wall,
            "inventory_call_cpu_ns": time.process_time_ns() - started_cpu}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="New manifest directly inside the fixed task workspace")
    args = parser.parse_args()
    try:
        receipt = write_inventory(args.output)
    except (InventoryError, OSError) as error:
        print(json.dumps({"status": "failed", "error": f"{type(error).__name__}: {error}"}), file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
