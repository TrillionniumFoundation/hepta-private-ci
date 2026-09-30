#!/usr/bin/env python3
"""Bounded SQLite backup and create-only staged restore for AutomationStore.

This tool does not migrate SQLx metadata, increment writer epochs, fence another
host, start Agentd or authorize a restore. The actual native owner must validate
and migrate a staged database after independent source fencing. A checkpoint's
hash binds bytes, not the physical absence of another writer.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import sqlite3
import stat
import time
import uuid
from pathlib import Path
from typing import Any, Iterator

DATABASE = "automation_1.sqlite3"
MANIFEST = "checkpoint.json"
COMMIT = "COMMITTED"
DEFAULT_MAX_BYTES = 16 * 1024**3


class CheckpointError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckpointError(message)


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                       allow_nan=False) + "\n").encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def json_object(raw: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result, f"duplicate manifest key: {key}")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique)
    require(isinstance(value, dict), "manifest must be an object")
    return value


def safe_path(path: Path, *, exists: bool = True) -> Path:
    require(os.name == "posix", "checkpoint tooling currently requires POSIX filesystem semantics")
    path = Path(os.path.abspath(path))
    for component in (path, *path.parents):
        require(not component.is_symlink(), f"symlink path is not permitted: {component}")
    if exists:
        info = path.stat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                "checkpoint/database must be a singly linked regular file")
        require(info.st_uid == os.geteuid() and info.st_mode & 0o077 == 0,
                "checkpoint/database must be privately owned by this operator")
    parent = path.parent.stat()
    require(parent.st_uid == os.geteuid() and parent.st_mode & 0o077 == 0,
            "use a private operator-owned parent directory")
    return path


def limits(max_bytes: int, timeout: float) -> None:
    require(type(max_bytes) is int and 0 < max_bytes <= 1024**4, "invalid checkpoint byte budget")
    require(0 < timeout <= 3600, "timeout must be in (0, 3600] seconds")


def check_deadline(deadline: float) -> None:
    require(time.monotonic() < deadline, "checkpoint deadline exceeded")


def hash_file(path: Path, max_bytes: int, deadline: float) -> tuple[str, int]:
    path = safe_path(path)
    total, result = 0, hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        original = os.fstat(stream.fileno())
        while chunk := stream.read(1024 * 1024):
            check_deadline(deadline)
            total += len(chunk)
            require(total <= max_bytes, "checkpoint byte budget exceeded")
            result.update(chunk)
        final = os.fstat(stream.fileno())
    current = path.stat()
    require((original.st_dev, original.st_ino, original.st_size, original.st_mtime_ns) ==
            (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns) ==
            (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns),
            "checkpoint changed while hashing")
    return result.hexdigest(), total


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def create_file(path: Path, contents: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(contents)
        stream.flush()
        os.fsync(stream.fileno())


@contextlib.contextmanager
def read_database(path: Path, deadline: float, *, sealed: bool = False) -> Iterator[sqlite3.Connection]:
    path = safe_path(path)
    original = path.stat()
    if sealed:
        require(not any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")),
                "sealed checkpoint has SQLite sidecars")
    uri = path.as_uri() + ("?mode=ro&immutable=1" if sealed else "?mode=ro")
    connection = sqlite3.connect(uri, uri=True, timeout=min(5.0, max(0.001, deadline - time.monotonic())))
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        connection.execute("BEGIN")
        yield connection
        check_deadline(deadline)
        current = path.stat()
        require((original.st_dev, original.st_ino) == (current.st_dev, current.st_ino),
                "database path was replaced during inspection")
    finally:
        connection.close()


def inspect_connection(connection: sqlite3.Connection, owner: str, schema: int) -> dict[str, Any]:
    require(str(uuid.UUID(owner)) == owner, "owner must be a canonical Agent UUID")
    require(type(schema) is int and schema > 0, "invalid expected schema")
    rows = connection.execute("SELECT schema_version, owner_agent_id FROM automation_meta").fetchmany(2)
    require(rows == [(schema, owner)], "database owner/schema does not match the expected source")
    require(connection.execute("PRAGMA integrity_check(1)").fetchone() == ("ok",), "SQLite integrity failure")
    require(connection.execute("PRAGMA foreign_key_check").fetchone() is None, "SQLite foreign-key violation")
    rows = connection.execute("SELECT writer_epoch, phase FROM automation_timer_lifecycle").fetchmany(2)
    require(len(rows) == 1 and type(rows[0][0]) is int and rows[0][0] > 0
            and rows[0][1] in ("active", "draining", "retired"), "invalid timer lifecycle")
    epoch, phase = rows[0]
    require(connection.execute("SELECT EXISTS(SELECT 1 FROM automation_tasks WHERE owner_agent_id != ?)", (owner,)).fetchone() == (0,),
            "foreign Agent task in the checkpoint")
    # Stream the migration ledger; never edit it or normalize legacy checksums.
    migrations = []
    for version, success, checksum in connection.execute("SELECT version, success, checksum FROM _sqlx_migrations ORDER BY version"):
        require(len(migrations) < 1024 and type(version) is int and version > 0 and success == 1
                and isinstance(checksum, bytes) and len(checksum) == 48, "invalid SQLx migration ledger")
        migrations.append({"version": version, "checksumSha384": checksum.hex()})
    require([row["version"] for row in migrations] == list(range(1, schema + 1)),
            "migration ledger is incomplete or does not match expected schema")
    counts = {}
    for table in ("automation_tasks", "automation_runs", "automation_occurrence_lifecycle",
                  "taskflow_runs", "taskflow_events"):
        counts[table] = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    counts["leased"] = connection.execute("SELECT COUNT(*) FROM automation_runs WHERE state='leased'").fetchone()[0]
    counts["queueUnknown"] = connection.execute("SELECT COUNT(*) FROM automation_dispatch_outcomes WHERE outcome='uncertain'").fetchone()[0]
    return {"ownerAgentId": owner, "storeSchemaVersion": schema, "writerEpoch": epoch,
            "timerPhase": phase, "counts": counts, "migrations": migrations}


def inspect(database: Path, owner: str, schema: int, *, timeout: float = 60.0) -> dict[str, Any]:
    limits(DEFAULT_MAX_BYTES, timeout)
    with read_database(database, time.monotonic() + timeout) as connection:
        state = inspect_connection(connection, owner, schema)
        state["inspectionRuntime"] = {"pythonSqliteVersion": sqlite3.sqlite_version,
                                      "sqliteSourceId": connection.execute("SELECT sqlite_source_id()").fetchone()[0]}
    state["nativeProductExecutionProved"] = False
    return state


def snapshot(database: Path, output: Path, owner: str, schema: int, *,
             max_bytes: int = DEFAULT_MAX_BYTES, timeout: float = 60.0) -> dict[str, Any]:
    limits(max_bytes, timeout)
    deadline = time.monotonic() + timeout
    database = safe_path(database)
    output = safe_path(output, exists=False)
    # A new private directory is reserved create-only. A failed operation keeps
    # its incomplete evidence; it never removes or overwrites a prior backup.
    output.mkdir(mode=0o700)
    create_file(output / "INCOMPLETE", b"This file alone never establishes a committed checkpoint; verify COMMITTED.\n")
    fsync_dir(output)
    fsync_dir(output.parent)
    target = output / DATABASE
    create_file(target, b"")
    pages_copied = 0
    with read_database(database, deadline) as source:
        before = inspect_connection(source, owner, schema)
        require(before["timerPhase"] == "draining", "quiesce the native timer before snapshot")
        page_size = source.execute("PRAGMA page_size").fetchone()[0]
        page_count = source.execute("PRAGMA page_count").fetchone()[0]
        require(page_size * page_count <= max_bytes, "checkpoint byte budget exceeded")
        with contextlib.closing(sqlite3.connect(target)) as destination:
            destination.execute("PRAGMA journal_mode=DELETE")
            destination.execute("PRAGMA synchronous=FULL")
            def progress(status: int, remaining: int, total: int) -> None:
                nonlocal pages_copied
                check_deadline(deadline)
                require(total * page_size <= max_bytes, "checkpoint byte budget exceeded")
                pages_copied = total - remaining
            source.backup(destination, pages=128, progress=progress, sleep=0.01)
            destination.commit()
        with read_database(target, deadline, sealed=True) as copied:
            require(inspect_connection(copied, owner, schema) == before, "copied owner snapshot changed")
    with target.open("rb") as stream:
        os.fsync(stream.fileno())
    checkpoint_hash, size = hash_file(target, max_bytes, deadline)
    manifest = {"schema": "hepta.automation-taskflow.checkpoint.v1", "checkpointSha256": checkpoint_hash,
                "checkpointBytes": size, "pagesCopied": pages_copied, "ownerSnapshot": before,
                "authorityGranted": False, "targetAdmitted": False,
                "nativeProductExecutionProved": False,
                "requiresNativeOwnerVerification": True, "requiresIndependentSourceFence": True}
    raw = canonical(manifest)
    create_file(output / MANIFEST, raw)
    fsync_dir(output)
    # Publishing this small marker is the only local commit point. A crash
    # beforehand leaves an unusable partial directory, never a successful receipt.
    create_file(output / COMMIT, (digest(raw) + "\n").encode())
    fsync_dir(output)
    return {"manifestSha256": digest(raw), "checkpointSha256": checkpoint_hash,
            "checkpointBytes": size, "targetAdmitted": False, "bundle": str(output)}


def verify(bundle: Path, expected_manifest_sha256: str, *, max_bytes: int = DEFAULT_MAX_BYTES,
           timeout: float = 60.0) -> dict[str, Any]:
    limits(max_bytes, timeout)
    deadline = time.monotonic() + timeout
    require(len(expected_manifest_sha256) == 64 and all(x in "0123456789abcdef" for x in expected_manifest_sha256),
            "an independently retained exact manifest SHA-256 is required")
    manifest_path = safe_path(bundle / MANIFEST)
    require(manifest_path.stat().st_size <= 1024 * 1024, "manifest size limit exceeded")
    raw = manifest_path.read_bytes()
    marker = safe_path(bundle / COMMIT)
    require(marker.stat().st_size == 65 and marker.read_bytes() == (expected_manifest_sha256 + "\n").encode(),
            "missing/mismatched checkpoint commit marker")
    require(digest(raw) == expected_manifest_sha256, "manifest does not match retained digest")
    manifest = json_object(raw)
    require(manifest.get("schema") == "hepta.automation-taskflow.checkpoint.v1", "unsupported checkpoint schema")
    require(manifest.get("nativeProductExecutionProved") is False
            and manifest.get("requiresNativeOwnerVerification") is True
            and manifest.get("requiresIndependentSourceFence") is True,
            "checkpoint cannot replace native verification or independent fencing")
    require(canonical(manifest) == raw, "checkpoint manifest is not canonical JSON")
    require(manifest.get("authorityGranted") is False and manifest.get("targetAdmitted") is False,
            "checkpoint manifest cannot grant authority")
    require(type(manifest.get("checkpointBytes")) is int and 0 < manifest["checkpointBytes"] <= max_bytes,
            "invalid checkpoint size")
    checkpoint = bundle / DATABASE
    actual_hash, size = hash_file(checkpoint, max_bytes, deadline)
    require(actual_hash == manifest.get("checkpointSha256") and size == manifest["checkpointBytes"],
            "checkpoint bytes do not match manifest")
    state = manifest["ownerSnapshot"]
    with read_database(checkpoint, deadline, sealed=True) as connection:
        require(inspect_connection(connection, state["ownerAgentId"], state["storeSchemaVersion"]) == state,
                "checkpoint owner/migration inventory mismatch")
    require(hash_file(checkpoint, max_bytes, deadline) == (actual_hash, size), "checkpoint changed during verification")
    return manifest


def restore_stage(bundle: Path, output: Path, expected_manifest_sha256: str, *,
                  max_bytes: int = DEFAULT_MAX_BYTES, timeout: float = 60.0) -> dict[str, Any]:
    limits(max_bytes, timeout)
    deadline = time.monotonic() + timeout
    manifest = verify(bundle, expected_manifest_sha256, max_bytes=max_bytes, timeout=timeout)
    output = safe_path(output, exists=False)
    output.mkdir(mode=0o700)
    fsync_dir(output.parent)
    create_file(output / "INCOMPLETE", b"Staged database; never start an owner from this marker.\n")
    source = safe_path(bundle / DATABASE)
    with contextlib.ExitStack() as stack:
        source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        src = stack.enter_context(os.fdopen(source_fd, "rb"))
        fd = os.open(output / DATABASE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        dst = stack.enter_context(os.fdopen(fd, "wb"))
        total = 0
        while chunk := src.read(1024 * 1024):
            check_deadline(deadline)
            total += len(chunk)
            require(total <= max_bytes, "staged restore byte budget exceeded")
            dst.write(chunk)
        dst.flush()
        os.fsync(dst.fileno())
    require(hash_file(output / DATABASE, max_bytes, deadline) == (manifest["checkpointSha256"], manifest["checkpointBytes"]),
            "staged database differs from verified checkpoint")
    receipt = {"schema": "hepta.automation-taskflow.staged-restore.v1",
               "sourceManifestSha256": expected_manifest_sha256, "checkpointSha256": manifest["checkpointSha256"],
               "ownerAgentId": manifest["ownerSnapshot"]["ownerAgentId"],
               "writerEpoch": manifest["ownerSnapshot"]["writerEpoch"],
               "storeSchemaVersion": manifest["ownerSnapshot"]["storeSchemaVersion"],
               "targetAdmitted": False, "sourceFenced": False, "epochAdvanced": False,
               "nativeOwnerVerificationRequired": True, "independentSourceFenceRequired": True}
    create_file(output / "STAGED.json", canonical(receipt))
    fsync_dir(output)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "snapshot", "verify", "restore-stage"):
        command = sub.add_parser(name)
        command.add_argument("--timeout", type=float, default=60.0)
        if name in ("inspect", "snapshot"):
            command.add_argument("--database", type=Path, required=True)
            command.add_argument("--owner", required=True)
            command.add_argument("--schema", type=int, required=True)
        else:
            command.add_argument("--bundle", type=Path, required=True)
            command.add_argument("--manifest-sha256", required=True)
        if name in ("snapshot", "restore-stage"):
            command.add_argument("--output", type=Path, required=True)
        if name != "inspect":
            command.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    args = vars(parser.parse_args())
    name = args.pop("command")
    if "manifest_sha256" in args:
        args["expected_manifest_sha256"] = args.pop("manifest_sha256")
    try:
        result = {"inspect": inspect, "snapshot": snapshot, "verify": verify,
                  "restore-stage": restore_stage}[name](**args)
        print(canonical(result).decode(), end="")
        return 0
    except (CheckpointError, OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        raise SystemExit(f"automation checkpoint rejected: {error}") from error


if __name__ == "__main__":
    raise SystemExit(main())
