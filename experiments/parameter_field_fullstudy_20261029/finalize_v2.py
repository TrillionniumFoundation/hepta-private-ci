"""CAS evidence inventory and streaming literal verification; no efficacy reads.

This creates a local evidence container manifest, not a promised tar backup or
permanent external upload. Every logical artifact keeps its original path/bytes.
"""

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time

from .resource_v2 import (MiB, RAW_OPEN, StorageBudget, file_hash, load_registration,
                         memory_admission, pending_growth, whole_phase_lock)

ROOT = Path(__file__).resolve().parents[2]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def snapshot(storage, excluded):
    """Content inventory only; never interpret scores, checkpoints or media."""
    result = {}
    with storage.writer_lock():
        for path in sorted(storage.root.rglob("*")):
            if path == excluded or excluded in path.parents:
                continue
            require(not path.is_symlink(), "Unexpected symbolic link in raw evidence")
            if path.is_dir():
                continue
            mode = path.lstat().st_mode
            require(stat.S_ISREG(mode), "Unexpected nonregular raw artifact")
            before = path.stat()
            digest = file_hash(path)
            after = path.stat()
            require((before.st_size, before.st_mtime_ns, before.st_ino) ==
                    (after.st_size, after.st_mtime_ns, after.st_ino), "Raw artifact changed while hashing")
            canonical = storage.cas_root / digest
            shared = canonical.is_file() and canonical.stat().st_ino == after.st_ino
            result[path.relative_to(storage.root).as_posix()] = {
                "bytes": after.st_size, "sha256": digest,
                "storage": "cas" if shared else "direct",
                "blob": digest if shared else None,
            }
    return result


def _temporary_check(storage, additional):
    """A verification duplicate is physical work, not another scientific sample."""
    storage.check()
    space = os.statvfs(storage.root)
    allocation = ((additional + space.f_frsize - 1) // space.f_frsize) * space.f_frsize
    require(space.f_bavail * space.f_frsize >= storage.reserve + allocation,
            "Literal verification would consume the registered physical reserve")
    require(memory_admission(allocation, storage.margin, pending_growth(storage.root))["allowed"],
            "Literal verification would consume the registered RAM margin")


@contextmanager
def controller_quiescence(root):
    """Acquire controller then worker-phase locks in one fixed order."""
    with RAW_OPEN(root / ".ops-controller.lock", "a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Finalization requires a stopped controller") from error
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def verification_residue(storage):
    """List retained verification copies separately from scientific logical raw."""
    result = []
    for directory in sorted(storage.cas_root.glob("literal-verify-*")):
        require(directory.is_dir() and not directory.is_symlink(), "Unexpected verification residue")
        files = []
        for path in sorted(directory.rglob("*")):
            require(not path.is_symlink(), "Unexpected verification-residue symlink")
            if path.is_file():
                info = path.stat()
                files.append({"path": str(path), "bytes": info.st_size,
                              "allocated_bytes": info.st_blocks * 512, "sha256": file_hash(path)})
        result.append({"directory": str(directory), "files": files,
                       "physical_allocated_bytes": sum(row["allocated_bytes"] for row in files)})
    return result


def verify_logical_paths(storage, entries):
    """Write and read each logical artifact independently; retain failed copies."""
    temporary = Path(tempfile.mkdtemp(prefix="literal-verify-", dir=storage.cas_root))
    verified, physical_written, peak_temporary = [], 0, 0
    current_relative, destination, written = None, None, 0
    try:
        for index, (relative, expected) in enumerate(sorted(entries.items())):
            current_relative, destination, written = relative, None, 0
            path = Path(relative)
            require(not path.is_absolute() and ".." not in path.parts, "Unsafe logical artifact path")
            source = storage.cas_root / expected["blob"] if expected["storage"] == "cas" else storage.root / path
            require(source.is_file() and not source.is_symlink(), "Missing canonical/direct artifact")
            destination = temporary / f"{index:08}.literal"
            with RAW_OPEN(source, "rb") as original, RAW_OPEN(destination, "xb", buffering=0) as restored:
                while True:
                    chunk = original.read(MiB)
                    if not chunk:
                        break
                    with storage.writer_lock():
                        _temporary_check(storage, len(chunk))
                        count = restored.write(chunk)
                        written += count
                        physical_written += count
                        peak_temporary = max(peak_temporary, written)
                        require(count == len(chunk), "Partial literal-verification write")
                        restored.flush()
                        os.fsync(restored.fileno())
            require(written == expected["bytes"] and file_hash(destination) == expected["sha256"],
                    "Literal artifact bytes differ from the manifest")
            require((storage.root / path).stat().st_size == expected["bytes"]
                    and file_hash(storage.root / path) == expected["sha256"],
                    "Original logical path changed during literal verification")
            verified.append(relative)
            destination.unlink()  # Verified temporary duplicate only; originals/CAS stay.
        temporary.rmdir()
    except BaseException as error:
        partial_bytes = destination.stat().st_size if destination is not None and destination.exists() else 0
        physical_written += max(0, partial_bytes - written)
        error.verification_progress = {
            "temporary_failure_directory": str(temporary), "logical_paths_verified": verified,
            "logical_files_verified": len(verified),
            "logical_bytes_verified": sum(entries[name]["bytes"] for name in verified),
            "physical_verification_bytes_written": physical_written,
            "peak_single_temporary_file_bytes": max(peak_temporary, partial_bytes),
            "current_logical_path": current_relative,
            "current_partial_path": str(destination) if destination is not None else None,
            "current_partial_bytes": partial_bytes,
            "temporary_directory_removed_after_success": False,
            "residue_counts_toward_physical_storage": True,
        }
        raise  # Preserve partial copy, progress and the original failure type.
    return {"logical_paths_verified": verified,
            "logical_files_restored": len(verified),
            "logical_bytes_restored": sum(row["bytes"] for row in entries.values()),
            "physical_verification_bytes_written": physical_written,
            "peak_single_temporary_file_bytes": peak_temporary,
            "temporary_failure_directory": str(temporary),
            "temporary_directory_removed_after_success": True}


def failure_progress(error):
    progress = dict(getattr(error, "verification_progress", {}))
    if not progress:
        return progress
    names = progress.pop("logical_paths_verified")
    encoded = json.dumps(names, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    progress["verified_manifest_prefix"] = {
        "order": "lexicographically sorted manifest.logical_paths", "count": len(names),
        "paths_json_sha256": hashlib.sha256(encoded).hexdigest(),
        "encoding": "UTF-8 JSON; ensure_ascii=False; separators=(',', ':')"}
    if len(encoded) <= 16384:
        progress["logical_paths_verified"] = names
    else:
        progress["logical_paths_reconstructable_from_manifest_prefix"] = True
    return progress


def verify_source_freeze(path, registration):
    with RAW_OPEN(path) as stream:
        freeze = json.load(stream)
    require(freeze.get("execution_kind") == "evidence_finalization"
            and freeze.get("attempt_id") == registration["attempt_id"]
            and freeze.get("operational_amendment_sha256") == registration["_sha256"],
            "Finalizer source freeze does not bind this operational attempt")
    require(isinstance(freeze.get("registered_commit"), str)
            and re.fullmatch(r"[0-9a-fA-F]{40}", freeze["registered_commit"]) is not None,
            "Finalizer registered commit must be a complete 40-hex SHA")
    source_files = freeze.get("source_files", {})
    required_sources = {str(Path(__file__).resolve().relative_to(ROOT)),
                        str(Path(__file__).resolve().with_name("resource_v2.py").relative_to(ROOT))}
    require(required_sources <= set(source_files), "Finalizer/resource source closure is incomplete")
    for relative, digest in source_files.items():
        target = (ROOT / relative).resolve()
        require(target.is_relative_to(ROOT) and file_hash(target) == digest, "Finalizer source closure differs")
    artifacts = freeze.get("artifacts", {})
    seals = freeze.get("required_scientific_seals")
    require(isinstance(seals, dict) and bool(seals), "Required scientific seals must be an explicit nonempty artifact map")
    require(all(name in artifacts and artifacts[name] == digest for name, digest in seals.items()),
            "Required scientific seals are missing or differ from frozen artifacts")
    for name, digest in artifacts.items():
        require(file_hash(name) == digest, "Finalizer input artifact differs")
    return freeze


def finalize(storage, binding, evidence_id="verification01"):
    require(evidence_id and evidence_id.isalnum(), "Evidence id must be a simple new identifier")
    destination = storage.root / "evidence_v2" / evidence_id
    started_wall, started_cpu = time.monotonic(), time.process_time()
    with controller_quiescence(storage.root), whole_phase_lock(storage.root):
        active = storage.root / "ACTIVE_WORKERS.json"
        if active.exists():
            with RAW_OPEN(active) as stream:
                workers = json.load(stream).get("workers", [])
            require(not any(Path(f"/proc/{int(row['pid'])}").exists() for row in workers),
                    "Finalization requires stopped workers and a quiescent controller")
        destination.mkdir(parents=True, exist_ok=False)
        storage.write_json(destination / "START.json", {"binding": binding, "scientific_outcomes_read": False})
        manifest_artifact = None
        try:
            # Append logs are immutable only now. No original file or alias is removed.
            for path in sorted(storage.root.rglob("*")):
                if path.is_file() and destination not in path.parents:
                    storage.deduplicate_closed(path)
            entries = snapshot(storage, destination)
            manifest = {"schema": "hepta.fullstudy.cas-container-manifest.1", "attempt_id": storage.registration["attempt_id"],
                        "binding": binding, "root": str(storage.root), "cas_root": str(storage.cas_root),
                        "logical_paths": entries, "logical_artifact_count": len(entries),
                        "logical_artifact_bytes": sum(row["bytes"] for row in entries.values()),
                        "unique_content_count": len({row["sha256"] for row in entries.values()}),
                        "all_raw_root_artifacts_and_failures_included": True,
                        "verification_residue_outside_logical_raw": verification_residue(storage),
                        "verification_residue_charged_to_physical_storage": True,
                        "excluded_current_verification_metadata": str(destination.relative_to(storage.root)),
                        "scientific_completion_inferred": False, "external_uploads": 0}
            manifest_file = destination / "MANIFEST.json"
            manifest_artifact = storage.write_json(manifest_file, manifest)
            restored = verify_logical_paths(storage, entries)
            require(snapshot(storage, destination) == entries, "Raw evidence changed before verification finished")
            record = {"schema": "hepta.fullstudy.cas-literal-verification.1", "archive_verification_complete": True,
                      "manifest": manifest_artifact, "binding": binding, **restored,
                      "final_storage": storage.inventory(), "scientific_completion_inferred": False,
                      "external_uploads": 0, "tar_archive_produced": False,
                      "wall_seconds": time.monotonic() - started_wall,
                      "cpu_seconds": time.process_time() - started_cpu}
            storage.write_json(destination / "VERIFIED.json", record)
            storage.deduplicate_closed(manifest_file)
            storage.deduplicate_closed(destination / "VERIFIED.json")
            return record
        except BaseException as error:
            failure = {"archive_verification_complete": False, "error_type": type(error).__name__,
                       "message": str(error), "binding": binding, "originals_preserved": True,
                       "manifest": manifest_artifact, "verification_progress": failure_progress(error),
                       "wall_seconds": time.monotonic() - started_wall,
                       "cpu_seconds": time.process_time() - started_cpu}
            try:
                storage.write_json(destination / "FAILED.json", failure, failure_record=True)
            except (OSError, RuntimeError, MemoryError):
                print(json.dumps(failure), flush=True)
            raise


def main():
    parser = argparse.ArgumentParser()
    for name in ("root", "amendment", "amendment-sha256", "freeze"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--evidence-id", default="verification01")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    require(args.execute, "Explicit registered finalization execution is required")
    registration = load_registration(args.amendment, args.amendment_sha256)
    freeze = verify_source_freeze(args.freeze, registration)
    storage = StorageBudget(args.root, registration)
    record = finalize(storage, {"attempt_id": registration["attempt_id"],
                      "operational_amendment_sha256": registration["_sha256"],
                      "source_freeze_sha256": file_hash(args.freeze),
                      "registered_commit": freeze["registered_commit"]}, args.evidence_id)
    print(json.dumps({"archive_verification_complete": record["archive_verification_complete"],
                      "manifest_sha256": record["manifest"]["sha256"],
                      "logical_files_restored": record["logical_files_restored"],
                      "logical_bytes_restored": record["logical_bytes_restored"]}), flush=True)


if __name__ == "__main__":
    main()
