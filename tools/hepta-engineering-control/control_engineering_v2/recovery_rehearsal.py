"""Crash-safe SQLite backup/restore rehearsal for control.engineering.

The rehearsal writes a new backup path, fsyncs it, reopens it through the exact
``EngineeringStore`` constructor, and compares both audit head and durable owner
snapshot.  It never switches a production caller and never emits operator
acceptance or release authority.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time

from .control_plane import (
    EngineeringError,
    EngineeringStore,
    checked_sha256,
    semantic_digest,
)
from .external_controls import store_snapshot_digest

_GIT_OID = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class RecoveryRehearsalReport:
    schema: str
    source_commit: str
    source_tree: str
    predecessor_artifact_digest: str
    backup_digest: str
    source_snapshot_digest: str
    restored_snapshot_digest: str
    source_audit_sequence: int
    source_audit_event_digest: str
    restored_audit_sequence: int
    restored_audit_event_digest: str
    backup_bytes: int
    observed_unix_ns: int
    passed: bool
    runtime_authority: bool = False
    merge_authority: bool = False
    release_authority: bool = False
    deployment_accepted: bool = False


def _git_oid(value: str, label: str) -> str:
    if not isinstance(value, str) or _GIT_OID.fullmatch(value) is None:
        raise EngineeringError(label)
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_file_and_parent(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if hasattr(os, "O_DIRECTORY"):
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)


def run_recovery_rehearsal(
    database: str | Path,
    backup: str | Path,
    *,
    source_commit: str,
    source_tree: str,
    predecessor_artifact_digest: str,
    now_ns: int | None = None,
) -> RecoveryRehearsalReport:
    source = Path(database).resolve()
    target = Path(backup).resolve()
    _git_oid(source_commit, "recovery_source_commit")
    _git_oid(source_tree, "recovery_source_tree")
    checked_sha256(predecessor_artifact_digest, "predecessor_artifact_digest")
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise EngineeringError("invalid_time")
    if not source.is_file() or source == target:
        raise EngineeringError("recovery_rehearsal_database")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise EngineeringError("recovery_rehearsal_backup_exists")

    with EngineeringStore(source) as owner:
        owner.verify_audit_chain()
        source_anchor = owner.audit_anchor()
        source_snapshot = store_snapshot_digest(owner)
        temporary = target.with_name(target.name + ".partial")
        if temporary.exists():
            temporary.unlink()
        try:
            with sqlite3.connect(temporary) as destination:
                owner.connection.backup(destination)
                integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
                foreign = destination.execute("PRAGMA foreign_key_check").fetchall()
                if integrity != "ok" or foreign:
                    raise EngineeringError("recovery_rehearsal_backup_integrity")
            _fsync_file_and_parent(temporary)
            os.replace(temporary, target)
            os.chmod(target, 0o600)
            _fsync_file_and_parent(target)
        finally:
            if temporary.exists():
                temporary.unlink()

    backup_digest = _sha256_file(target)
    with EngineeringStore(target) as restored:
        restored.verify_audit_chain()
        restored_anchor = restored.audit_anchor()
        restored_snapshot = store_snapshot_digest(restored)
    passed = (
        source_snapshot == restored_snapshot
        and source_anchor == restored_anchor
        and target.stat().st_size > 0
    )
    if not passed:
        raise EngineeringError("recovery_rehearsal_mismatch")
    return RecoveryRehearsalReport(
        schema="hepta.control-engineering-recovery-rehearsal.v1",
        source_commit=source_commit,
        source_tree=source_tree,
        predecessor_artifact_digest=predecessor_artifact_digest,
        backup_digest=backup_digest,
        source_snapshot_digest=source_snapshot,
        restored_snapshot_digest=restored_snapshot,
        source_audit_sequence=int(source_anchor["sequence"]),
        source_audit_event_digest=str(source_anchor["eventDigest"]),
        restored_audit_sequence=int(restored_anchor["sequence"]),
        restored_audit_event_digest=str(restored_anchor["eventDigest"]),
        backup_bytes=target.stat().st_size,
        observed_unix_ns=now,
        passed=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--predecessor-artifact-digest", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = run_recovery_rehearsal(
            args.database,
            args.backup,
            source_commit=args.source_commit,
            source_tree=args.source_tree,
            predecessor_artifact_digest=args.predecessor_artifact_digest,
        )
    except (EngineeringError, OSError, sqlite3.DatabaseError) as error:
        print(
            json.dumps(
                {
                    "schema": "hepta.control-engineering-recovery-rehearsal.v1",
                    "status": "rejected",
                    "error": str(error),
                    "authorityGranted": False,
                },
                sort_keys=True,
            ),
            file=os.sys.stderr,
        )
        return 1
    value = asdict(report)
    value["reportDigest"] = semantic_digest(value)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
