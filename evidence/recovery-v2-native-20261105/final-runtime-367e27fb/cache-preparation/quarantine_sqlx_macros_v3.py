#!/usr/bin/env python3
"""Preserve an exact inactive cache set; this never invokes Cargo or tests."""

from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import uuid


OWNED = Path("/workspace/scratch/822cc50e24f0/authority-recovery/native-20261105")
TARGET = OWNED / "target"
FILES = {
    "debug/deps/libsqlx_macros_core-67b73f8b5327a208.rlib": 2920886,
    "debug/deps/libsqlx_macros_core-67b73f8b5327a208.rmeta": 700801,
    "debug/deps/sqlx_macros_core-67b73f8b5327a208.d": 8073,
    "debug/deps/libsqlx_macros-de58ffc848cccd8c.so": 25454832,
    "debug/deps/sqlx_macros-de58ffc848cccd8c.d": 505,
}
DIRECTORIES = {
    "debug/.fingerprint/sqlx-macros-core-67b73f8b5327a208": {
        "lib-sqlx_macros_core.json": 2124,
        "invoked.timestamp": 48,
        "dep-lib-sqlx_macros_core": 14,
        "lib-sqlx_macros_core": 16,
    },
    "debug/.fingerprint/sqlx-macros-de58ffc848cccd8c": {
        "output-lib-sqlx_macros": 2806,
        "lib-sqlx_macros.json": 1290,
        "invoked.timestamp": 48,
        "dep-lib-sqlx_macros": 14,
        "lib-sqlx_macros": 0,
    },
}


def checked_stat(path, directory=False):
    value = path.lstat()
    required = stat.S_ISDIR if directory else stat.S_ISREG
    if not required(value.st_mode) or value.st_uid != os.geteuid():
        raise RuntimeError(f"unexpected type or owner: {path}")
    if not directory and value.st_nlink != 1:
        raise RuntimeError(f"shared hardlink refused: {path}")
    if path.resolve(strict=True) != path:
        raise RuntimeError(f"symlink traversal refused: {path}")
    return value


def identity(path, expected_bytes):
    before = checked_stat(path)
    if before.st_size != expected_bytes:
        raise RuntimeError(f"unexpected byte count: {path}")
    digest = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise RuntimeError(f"file replaced while opening: {path}")
        while chunk := stream.read(65536):
            digest.update(chunk)
    after = checked_stat(path)
    fields = ("st_dev", "st_ino", "st_size", "st_mode", "st_uid", "st_nlink", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, field) != getattr(after, field) for field in fields):
        raise RuntimeError(f"file changed while hashing: {path}")
    return {
        "bytes": after.st_size,
        "mode": oct(stat.S_IMODE(after.st_mode)),
        "uid": after.st_uid,
        "device": after.st_dev,
        "inode": after.st_ino,
        "links": after.st_nlink,
        "mtime_ns": after.st_mtime_ns,
        "ctime_ns": after.st_ctime_ns,
        "sha256": digest.hexdigest(),
    }


def inventory(base, relative):
    path = base / relative
    if relative in FILES:
        return {"kind": "file", "file": identity(path, FILES[relative])}
    before = checked_stat(path, directory=True)
    expected = DIRECTORIES[relative]
    if {child.name for child in path.iterdir()} != set(expected):
        raise RuntimeError(f"unexpected fingerprint entries: {path}")
    files = {name: identity(path / name, size) for name, size in expected.items()}
    after = checked_stat(path, directory=True)
    if (before.st_dev, before.st_ino, before.st_mode, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_mode, after.st_mtime_ns, after.st_ctime_ns):
        raise RuntimeError(f"fingerprint directory changed: {path}")
    return {"kind": "directory", "device": after.st_dev, "inode": after.st_ino, "mode": oct(stat.S_IMODE(after.st_mode)), "uid": after.st_uid, "files": files}


def same_retained_identity(before, after):
    # Rename may update inode ctime; every content/ownership identity stays bound.
    def normalize(value):
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items() if key != "ctime_ns"}
        return value
    return normalize(before) == normalize(after)


OBSERVED_CARGO_FRONTENDS = []
OBSERVED_FOREIGN_COMPILERS = []


def active_owned_compilers():
    found = []
    for process in Path("/proc").glob("[0-9]*"):
        try:
            name = (process / "comm").read_text().strip()
            if name not in {"cargo", "rustc", "rustdoc", "cargo-nextest"}:
                continue
            args = [item.decode(errors="replace") for item in (process / "cmdline").read_bytes().split(b"\0") if item]
            if name in {"cargo", "cargo-nextest"}:
                # Cargo cannot mutate this target while our exclusive cache
                # lock is held. No external frontend cwd is needed or read.
                explicit_owned = any(str(OWNED) in item for item in args[1:])
                OBSERVED_CARGO_FRONTENDS.append({"pid": int(process.name), "name": name, "explicit_owned_argument": explicit_owned, "cwd_read": False})
                if explicit_owned:
                    found.append({"pid": int(process.name), "name": name, "reason": "owned argument present"})
                continue
            outputs = []
            for index, item in enumerate(args):
                if item in {"--out-dir", "-o"} and index + 1 < len(args):
                    outputs.append(args[index + 1])
                elif item.startswith("--out-dir="):
                    outputs.append(item.split("=", 1)[1])
            if not outputs or any(not Path(value).is_absolute() for value in outputs):
                raise RuntimeError(f"compiler writer location is not explicit: {process.name}")
            owned = any(value == str(TARGET) or value.startswith(str(TARGET) + "/") for value in outputs)
            if owned:
                found.append({"pid": int(process.name), "name": name, "output_paths": outputs})
            else:
                OBSERVED_FOREIGN_COMPILERS.append({"pid": int(process.name), "name": name, "output_paths": outputs, "cwd_read": False})
        except (FileNotFoundError, ProcessLookupError):
            continue
    return found


def main():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    action = OWNED / "receipts" / ("cache-quarantine-367e27fb-" + stamp + "-" + uuid.uuid4().hex[:8])
    record = {
        "status": "PREFLIGHT",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "selected_runtime_commit": "367e27fb6bf30443641b9e23a063d24e49eda9f7",
        "selected_runtime_tree": "6a2465606f0270eeecec83c2b7d9dbef5dc96076",
        "target": str(TARGET),
        "quarantine": str(action / "retained-target-paths"),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cargo_or_test_invoked": False,
        "test_count": 0,
        "e0463_resolution": "UNKNOWN_REBUILD_NOT_RUN",
        "before": {},
        "after": {},
        "moved": [],
    }
    lock_fd = None
    moved = []
    receipt_parent_verified = False
    try:
        checked_stat(OWNED, directory=True)
        checked_stat(TARGET, directory=True)
        checked_stat(OWNED / "receipts", directory=True)
        receipt_parent_verified = True
        lock = TARGET / "debug/.cargo-lock"
        checked_stat(lock)
        lock_fd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        record["cargo_lock"] = "NONBLOCKING_EXCLUSIVE_ACQUIRED"
        record["active_owned_compilers"] = active_owned_compilers()
        record["observed_cargo_frontends"] = OBSERVED_CARGO_FRONTENDS
        record["observed_foreign_compilers"] = OBSERVED_FOREIGN_COMPILERS
        record["frontend_protection"] = "Exclusive target Cargo lock held throughout inventory and rename; external frontend cwd is neither accessed nor inferred."
        if record["active_owned_compilers"]:
            raise RuntimeError("active owned compiler: refuse cache mutation")
        record["before"] = {relative: inventory(TARGET, relative) for relative in [*FILES, *DIRECTORIES]}
        action.mkdir(mode=0o700)
        retained = action / "retained-target-paths"
        retained.mkdir(mode=0o700)
        if retained.stat().st_dev != TARGET.stat().st_dev:
            raise RuntimeError("quarantine is not on the same filesystem")
        (action / "manifest-before.json").write_text(json.dumps(record, indent=2) + "\n")
        for relative in record["before"]:
            source, destination = TARGET / relative, retained / relative
            if inventory(TARGET, relative) != record["before"][relative]:
                raise RuntimeError(f"identity changed before rename: {relative}")
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.path.lexists(destination):
                raise RuntimeError(f"destination exists: {destination}")
            os.rename(source, destination)
            moved.append(relative)
            record["moved"].append(relative)
        for relative, before in record["before"].items():
            after = inventory(retained, relative)
            if not same_retained_identity(before, after) or os.path.lexists(TARGET / relative):
                raise RuntimeError(f"retained identity or original-path absence failed: {relative}")
            record["after"][relative] = after
        record.update(status="CACHE_QUARANTINED_REBUILD_NOT_RUN", original_paths_absent=True, retained_identities_match=True, regular_files_preserved=14, bytes_preserved=29091457)
    except Exception as error:
        record["error"] = f"{type(error).__name__}: {error}"
        record["status"] = "CACHE_QUARANTINE_REFUSED" if not moved else "CACHE_QUARANTINE_FAILED_ROLLBACK_ATTEMPTED"
        record["rollback"] = []
        for relative in reversed(moved):
            source, destination = action / "retained-target-paths" / relative, TARGET / relative
            try:
                if os.path.lexists(destination) or not same_retained_identity(record["before"][relative], inventory(action / "retained-target-paths", relative)):
                    raise RuntimeError("rollback would overwrite a new file or use a changed retained artifact")
                os.rename(source, destination)
                if not same_retained_identity(record["before"][relative], inventory(TARGET, relative)):
                    raise RuntimeError("rollback identity mismatch")
                record["rollback"].append({"path": relative, "restored": True})
            except Exception as rollback_error:
                record["rollback"].append({"path": relative, "restored": False, "error": str(rollback_error)})
    finally:
        record["completed_at"] = datetime.now(timezone.utc).isoformat()
        record["safe_manual_rollback"] = "Only under the same exclusive target lock and with no active target user: verify every retained SHA256/mode/size against before, refuse any existing original path, rename the exact seven entries back, and verify the restored identities. Never overwrite new rebuild output."
        if receipt_parent_verified:
            action.mkdir(mode=0o700, exist_ok=True)
            (action / "receipt.json").write_text(json.dumps(record, indent=2) + "\n")
        else:
            print(json.dumps(record, indent=2))
        if lock_fd is not None:
            os.close(lock_fd)
    print(json.dumps({key: record[key] for key in ("status", "quarantine", "cargo_or_test_invoked", "test_count", "e0463_resolution")}))
    if receipt_parent_verified:
        print(str(action / "receipt.json"))
    return 0 if record["status"] == "CACHE_QUARANTINED_REBUILD_NOT_RUN" else 1


if __name__ == "__main__":
    sys.exit(main())
