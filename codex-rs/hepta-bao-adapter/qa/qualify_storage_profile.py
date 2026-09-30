#!/usr/bin/env python3
"""Qualify the exact filesystem that will hold the secrets.heptabao SQLite owner.

The receipt is fail-closed: local SQLite/WAL checks alone never prove power-loss
or snapshot rollback safety. Those require immutable external evidence files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from typing import Any

UNSAFE_FILESYSTEMS = {
    "9p", "afs", "cifs", "ceph", "fuse", "fuseblk", "gcsfuse", "glusterfs",
    "nfs", "nfs4", "overlay", "s3fs", "smb3", "sshfs", "virtiofs",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mount_profile(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    best: dict[str, Any] | None = None
    mountinfo = Path("/proc/self/mountinfo")
    if not mountinfo.is_file():
        return {"available": False, "reason": "mountinfo unavailable"}
    for raw in mountinfo.read_text(encoding="utf-8").splitlines():
        before, separator, after = raw.partition(" - ")
        if not separator:
            continue
        fields = before.split()
        tail = after.split()
        if len(fields) < 6 or len(tail) < 3:
            continue
        mount_point = Path(fields[4].replace("\\040", " "))
        try:
            resolved.relative_to(mount_point)
        except ValueError:
            continue
        candidate = {
            "available": True,
            "mountPoint": str(mount_point),
            "mountOptions": fields[5].split(","),
            "filesystem": tail[0],
            "source": tail[1],
            "superOptions": tail[2].split(","),
        }
        if best is None or len(candidate["mountPoint"]) > len(best["mountPoint"]):
            best = candidate
    return best or {"available": False, "reason": "no covering mount"}


def run_sqlite_checks(root: Path) -> dict[str, Any]:
    database = root / "owner.sqlite3"
    connection = sqlite3.connect(database, timeout=0.2, isolation_level=None)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("CREATE TABLE evidence(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute("BEGIN IMMEDIATE")
    connection.execute("INSERT INTO evidence(value) VALUES ('durable')")
    connection.execute("COMMIT")
    connection.execute("PRAGMA wal_checkpoint(FULL)")
    journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    synchronous = int(connection.execute("PRAGMA synchronous").fetchone()[0])

    lock_probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sqlite3,sys; "
                "c=sqlite3.connect(sys.argv[1],timeout=0.05,isolation_level=None); "
                "c.execute('BEGIN IMMEDIATE')"
            ),
            str(database),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    connection.execute("BEGIN IMMEDIATE")
    # The first probe happened before the lock. Repeat while the lock is held.
    held_probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sqlite3,sys; "
                "c=sqlite3.connect(sys.argv[1],timeout=0.05,isolation_level=None); "
                "c.execute('BEGIN IMMEDIATE')"
            ),
            str(database),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    connection.execute("ROLLBACK")
    connection.close()

    with database.open("rb") as stream:
        os.fsync(stream.fileno())
    directory_fd = os.open(root, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)

    reopened = sqlite3.connect(database, timeout=0.2)
    integrity = reopened.execute("PRAGMA integrity_check").fetchone()[0]
    row = reopened.execute("SELECT value FROM evidence WHERE id=1").fetchone()
    reopened.close()

    corrupted = root / "corrupted.sqlite3"
    shutil.copy2(database, corrupted)
    with corrupted.open("r+b") as stream:
        stream.seek(0)
        stream.write(b"NOT-A-SQLITE-DB!")
        stream.flush()
        os.fsync(stream.fileno())
    corruption_detected = False
    try:
        broken = sqlite3.connect(corrupted)
        broken.execute("PRAGMA quick_check").fetchone()
        broken.close()
    except sqlite3.DatabaseError:
        corruption_detected = True

    return {
        "database": str(database),
        "databaseSha256": sha256_file(database),
        "journalMode": journal_mode,
        "synchronous": synchronous,
        "walEnabled": str(journal_mode).lower() == "wal",
        "fullSynchronous": synchronous >= 2,
        "byteRangeLockingObserved": held_probe.returncode != 0
        and "locked" in (held_probe.stderr + held_probe.stdout).lower(),
        "uncontendedBeginWorks": lock_probe.returncode == 0,
        "directoryFsyncWorks": True,
        "restartReopenWorks": integrity == "ok" and row == ("durable",),
        "integrityCheck": integrity,
        "corruptionDetected": corruption_detected,
    }


def evidence(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"present": False}
    resolved = path.resolve()
    return {
        "present": resolved.is_file(),
        "path": str(resolved),
        "sha256": sha256_file(resolved) if resolved.is_file() else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--power-loss-evidence", type=Path)
    parser.add_argument("--snapshot-rollback-evidence", type=Path)
    args = parser.parse_args()

    root = args.path.resolve()
    root.mkdir(parents=True, exist_ok=True)
    profile = mount_profile(root)
    sqlite = run_sqlite_checks(root)
    stats = os.statvfs(root)
    power_loss = evidence(args.power_loss_evidence)
    snapshot = evidence(args.snapshot_rollback_evidence)
    filesystem = str(profile.get("filesystem", "unknown")).lower()
    local_locking_filesystem = bool(profile.get("available")) and filesystem not in UNSAFE_FILESYSTEMS
    checks = {
        "localLockingFilesystem": local_locking_filesystem,
        "walEnabled": sqlite["walEnabled"],
        "fullSynchronous": sqlite["fullSynchronous"],
        "byteRangeLockingObserved": sqlite["byteRangeLockingObserved"],
        "directoryFsyncWorks": sqlite["directoryFsyncWorks"],
        "restartReopenWorks": sqlite["restartReopenWorks"],
        "corruptionDetected": sqlite["corruptionDetected"],
        "powerLossEvidencePresent": power_loss["present"],
        "snapshotRollbackEvidencePresent": snapshot["present"],
    }
    receipt = {
        "schema": "hepta.secrets-storage-profile-receipt.v1",
        "targetId": args.target_id,
        "observedAtUnixMs": int(time.time() * 1000),
        "path": str(root),
        "mount": profile,
        "capacity": {
            "freeBytes": stats.f_bavail * stats.f_frsize,
            "freeInodes": stats.f_favail,
        },
        "sqlite": sqlite,
        "powerLossEvidence": power_loss,
        "snapshotRollbackEvidence": snapshot,
        "checks": checks,
        "qualified": all(checks.values()),
        "nonClaims": [
            "A runner-local receipt does not qualify a production target volume.",
            "Power-loss and writable-snapshot rollback require external evidence.",
            "Node migration remains unqualified unless exercised on the target platform.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
