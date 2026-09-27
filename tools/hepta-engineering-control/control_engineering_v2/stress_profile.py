"""Bounded crash/reopen, contention, WAL and growth profile for SQLite v10."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from .control_plane import DENIED_AUTHORITIES, EngineeringStore, WorkEnvelope, semantic_digest

_SCHEMA = "hepta.control-engineering-stress-profile.v1"


def _envelope(index: int, expires: int) -> WorkEnvelope:
    return WorkEnvelope(
        f"stress-envelope-{index}",
        hashlib.sha1(f"commit-{index}".encode()).hexdigest(),
        hashlib.sha1(f"tree-{index}".encode()).hexdigest(),
        hashlib.sha256(f"objective-{index}".encode()).hexdigest(),
        hashlib.sha256(f"contract-{index}".encode()).hexdigest(),
        "developer-productivity",
        ("stress",),
        tuple(sorted(DENIED_AUTHORITIES)),
        1,
        expires,
    )


def _child_commit(database: Path, index: int, now_ns: int) -> int:
    with EngineeringStore(database) as store:
        store.issue_work_envelope(
            _envelope(index, now_ns + 60_000_000_000),
            now_ns=now_ns,
        )
    return 0


def build_stress_profile(
    *,
    crash_reopens: int = 5,
    concurrent_writers: int = 8,
    growth_records: int = 250,
) -> dict[str, object]:
    for value, maximum in (
        (crash_reopens, 50),
        (concurrent_writers, 32),
        (growth_records, 5_000),
    ):
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError("stress_profile_bound")
    now = time.time_ns()
    with tempfile.TemporaryDirectory(prefix="hepta-engineering-stress-") as temporary:
        root = Path(temporary)
        database = root / "engineering.sqlite3"
        with EngineeringStore(database):
            pass

        crash_started = time.perf_counter_ns()
        for index in range(crash_reopens):
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "control_engineering_v2.stress_profile",
                    "--child-database",
                    str(database),
                    "--child-index",
                    str(index),
                    "--child-now-ns",
                    str(now + index),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError("stress_child_failed")
            with EngineeringStore(database) as reopened:
                reopened.verify_audit_chain()
        crash_millis = round((time.perf_counter_ns() - crash_started) / 1_000_000, 3)

        def writer(index: int) -> str:
            envelope = _envelope(10_000 + index, now + 120_000_000_000)
            with EngineeringStore(database) as store:
                store.issue_work_envelope(
                    envelope,
                    now_ns=now + 10_000 + index,
                )
            return envelope.envelope_id

        contention_started = time.perf_counter_ns()
        with ThreadPoolExecutor(max_workers=concurrent_writers) as executor:
            contention_digests = tuple(executor.map(writer, range(concurrent_writers)))
        contention_millis = round(
            (time.perf_counter_ns() - contention_started) / 1_000_000, 3
        )
        if len(set(contention_digests)) != concurrent_writers:
            raise RuntimeError("stress_contention_identity_collision")

        reader = EngineeringStore(database)
        reader.connection.execute("BEGIN")
        reader.connection.execute("SELECT COUNT(*) FROM work_envelopes").fetchone()
        try:
            with EngineeringStore(database) as writer_store:
                for index in range(growth_records):
                    writer_store.issue_work_envelope(
                        _envelope(20_000 + index, now + 180_000_000_000),
                        now_ns=now + 20_000 + index,
                    )
            wal_path = Path(str(database) + "-wal")
            wal_bytes = wal_path.stat().st_size if wal_path.exists() else 0
        finally:
            reader.connection.rollback()
            reader.close()

        reopen_started = time.perf_counter_ns()
        for _ in range(25):
            with EngineeringStore(database) as reopened:
                reopened.audit_anchor()
        reopen_millis = round((time.perf_counter_ns() - reopen_started) / 1_000_000, 3)
        database_bytes = database.stat().st_size
        with EngineeringStore(database) as final:
            final.verify_audit_chain()
            envelope_count = int(
                final.connection.execute("SELECT COUNT(*) FROM work_envelopes").fetchone()[0]
            )
            audit_events = int(
                final.connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
            )
            final_anchor = final.audit_anchor()

    value: dict[str, object] = {
        "schema": _SCHEMA,
        "crashReopens": crash_reopens,
        "concurrentWriters": concurrent_writers,
        "growthRecords": growth_records,
        "measurements": {
            "crashReopenMillis": crash_millis,
            "contentionMillis": contention_millis,
            "reopen25Millis": reopen_millis,
            "databaseBytes": database_bytes,
            "walBytesWhileReaderPinned": wal_bytes,
            "envelopeCount": envelope_count,
            "auditEvents": audit_events,
        },
        "finalAuditAnchor": final_anchor,
        "runtimeAuthority": False,
        "mergeAuthority": False,
        "releaseAuthority": False,
    }
    value["profileDigest"] = semantic_digest(value)
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--crash-reopens", type=int, default=5)
    parser.add_argument("--concurrent-writers", type=int, default=8)
    parser.add_argument("--growth-records", type=int, default=250)
    parser.add_argument("--child-database", type=Path)
    parser.add_argument("--child-index", type=int)
    parser.add_argument("--child-now-ns", type=int)
    args = parser.parse_args(argv)
    if args.child_database is not None:
        if args.child_index is None or args.child_now_ns is None:
            return 2
        return _child_commit(args.child_database, args.child_index, args.child_now_ns)
    try:
        value = build_stress_profile(
            crash_reopens=args.crash_reopens,
            concurrent_writers=args.concurrent_writers,
            growth_records=args.growth_records,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(json.dumps({"schema": _SCHEMA, "status": "rejected", "error": str(error)}))
        return 1
    rendered = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
