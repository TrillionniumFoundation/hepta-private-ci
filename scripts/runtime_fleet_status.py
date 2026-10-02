#!/usr/bin/env python3
"""Non-mutating diagnostics for a checkpointed, quiescent fleet database snapshot.

This tool never opens a source database using SQLite. It reads the file into an
in-memory database and refuses live WAL/journal state. Live diagnosis must use the
existing owner's telemetry channel, not silently initialize a second writer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

SCHEMA_VERSION = 2
LINEAGE = "hepta.runtime.fleet.supervisor-owner.v1"
AXES = ("cpu_millis", "memory_bytes", "accelerator_millis", "concurrent_turns", "tool_processes", "turn_queue_slots")
MAX_DATABASE_BYTES = 256 * 1024 * 1024


def nonnegative(value: Any, name: str) -> int:
    if type(value) is not int or not 0 <= value <= (1 << 63) - 1:
        raise ValueError(f"{name} must be a nonnegative signed-64-bit integer")
    return value


def no_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        if Path(str(path) + suffix).exists():
            raise ValueError("live or recovery SQLite sidecars present; obtain a checkpointed snapshot from the owner")


def snapshot(path: Path) -> tuple[sqlite3.Connection, str]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("database must be an existing regular snapshot, not a symlink")
    no_sidecars(path)
    before = path.stat()
    if not 100 <= before.st_size <= MAX_DATABASE_BYTES:
        raise ValueError("database snapshot size is invalid or exceeds the diagnostic limit")
    with path.open("rb") as source:
        image = source.read(MAX_DATABASE_BYTES + 1)
    after = path.stat()
    no_sidecars(path)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ) or len(image) != before.st_size:
        raise ValueError("database changed during snapshot read")
    if image[:16] != b"SQLite format 3\0":
        raise ValueError("not a SQLite database")
    # SQLite deserialize requires rollback-journal header bytes. Only the private
    # in-memory copy is changed; WAL/SHM/journal source files are never ignored.
    private_image = bytearray(image)
    private_image[18:20] = b"\x01\x01"
    connection = sqlite3.connect(":memory:")
    try:
        connection.deserialize(private_image)
        connection.execute("PRAGMA query_only = ON")
        if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError("snapshot integrity check failed")
        schema = connection.execute("SELECT schema_version, lineage FROM fleet_schema WHERE singleton = 1").fetchall()
        if schema != [(SCHEMA_VERSION, LINEAGE)]:
            raise ValueError("unsupported or missing fleet schema/lineage")
        return connection, hashlib.sha256(image).hexdigest()
    except BaseException:
        connection.close()
        raise


def status(path: Path, now_ms: int) -> dict[str, Any]:
    now_ms = nonnegative(now_ms, "now_ms")
    connection, digest = snapshot(path)
    try:
        frontier = connection.execute("SELECT last_now_ms FROM fleet_clock WHERE singleton = 1").fetchone()
        if frontier is None or now_ms < nonnegative(frontier[0], "clock frontier"):
            raise ValueError("diagnostic time is behind the durable clock frontier")
        active, expired = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(expires_at_ms <= ?), 0) FROM fleet_grants", (now_ms,)
        ).fetchone()
        pending = connection.execute("SELECT COUNT(*) FROM fleet_execution_holds WHERE state != 'stopped'").fetchone()[0]
        hosts = []
        columns = ", ".join("h." + axis for axis in AXES) + ", " + ", ".join("r." + axis for axis in AXES)
        for row in connection.execute(
            "SELECT h.host_id, h.valid_until_ms, " + columns +
            " FROM fleet_hosts h LEFT JOIN fleet_resource_totals r USING(host_id) ORDER BY h.host_id"
        ):
            observed = dict(zip(AXES, row[2:8]))
            reserved = dict(zip(AXES, row[8:14]))
            for name, value in observed.items():
                nonnegative(value, name)
            for name, value in reserved.items():
                nonnegative(value, "reserved " + name)
            valid_until = nonnegative(row[1], "valid_until_ms")
            hosts.append({"host_id": row[0], "observed": observed, "reserved": reserved,
                          "stale": now_ms >= valid_until,
                          "overcommitted": any(reserved[axis] > observed[axis] for axis in AXES)})
        return {"schema_version": 1, "read_only": True, "authorizes_execution": False,
                "snapshot_sha256": digest, "diagnostic_now_ms": now_ms,
                "active_grants": nonnegative(active, "active_grants"),
                "expired_uncollected_grants": nonnegative(expired, "expired_grants"),
                "pending_executions": nonnegative(pending, "pending_executions"),
                "host_resources": hosts,
                "revocation_lag_ms": None, "selected_host_verified": False}
    finally:
        connection.close()


def read_request(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 64 * 1024:
        raise ValueError("request/profile exceeds 64 KiB")
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    if not isinstance(value, dict) or set(value) != {"host_id", "resources"}:
        raise ValueError("request/profile requires exactly host_id and resources")
    if not isinstance(value["host_id"], str) or not value["host_id"] or len(value["host_id"]) > 256:
        raise ValueError("invalid host_id")
    if not isinstance(value["resources"], dict) or set(value["resources"]) != set(AXES):
        raise ValueError("all six resource axes are required, without unknown fields")
    for axis in AXES:
        nonnegative(value["resources"][axis], axis)
    if not any(value["resources"].values()):
        raise ValueError("resource demand cannot be all zero")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "preflight", "dry-run"):
        part = sub.add_parser(command, allow_abbrev=False)
        location = part.add_mutually_exclusive_group(required=True)
        location.add_argument("--database", type=Path)
        location.add_argument("--state-dir", type=Path)
        part.add_argument("--now-ms", type=int, required=True, help="explicit diagnostic clock; never persisted")
        part.add_argument("--format", choices=("json",), default="json")
        if command != "status":
            part.add_argument("--profile" if command == "preflight" else "--request", type=Path, required=True)
    args = parser.parse_args(argv)
    database = args.database or args.state_dir / "supervisor.sqlite3"
    try:
        result = status(database, args.now_ms)
        if args.command != "status":
            request = read_request(args.profile if args.command == "preflight" else args.request)
            host = next((host for host in result["host_resources"] if host["host_id"] == request["host_id"]), None)
            fits = host is not None and not host["stale"] and not host["overcommitted"]
            if host is not None:
                fits = fits and all(host["reserved"][axis] + request["resources"][axis] <= host["observed"][axis] for axis in AXES)
            result["admissible_in_snapshot"] = bool(fits)
            result["profile_validated"] = True
        print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, sqlite3.Error) as error:
        print(json.dumps({"read_only": True, "authorizes_execution": False,
                          "scrape_success": False, "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
