#!/usr/bin/env python3
"""Bounded concurrency, WAL, crash/reopen, disk-full, and growth qualification."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

from control_engineering_v2.control_plane import DENIED_AUTHORITIES, EngineeringStore, WorkEnvelope
from control_engineering_v2.qualification_profile import _measure_disk_full_rollback


def _envelope(index: int, expires: int) -> WorkEnvelope:
    return WorkEnvelope(
        f"stress-{index}",
        "a" * 40,
        "b" * 40,
        hashlib.sha256(f"objective-{index}".encode()).hexdigest(),
        hashlib.sha256(b"control.engineering.operational-stress.v1").hexdigest(),
        "developer-productivity",
        ("src",),
        tuple(sorted(DENIED_AUTHORITIES)),
        1,
        expires,
    )


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * percentile))
    return round(ordered[index], 3)


def _child(database: Path, index: int, now: int) -> int:
    store = EngineeringStore(database)
    store.issue_work_envelope(_envelope(index, now + 10_000_000_000), now_ns=now)
    # Simulate a process disappearing after the owner transaction committed but
    # before ordinary context-manager shutdown/acknowledgement.
    os._exit(0)


def build_stress_profile(
    *,
    iterations: int,
    workers: int,
    crash_cycles: int,
) -> dict[str, object]:
    if not 1 <= iterations <= 10_000 or not 1 <= workers <= 32 or not 1 <= crash_cycles <= 100:
        raise ValueError("operational_stress_bounds")
    now = 1_000_000
    with tempfile.TemporaryDirectory(prefix="hepta-engineering-stress-") as temporary:
        root = Path(temporary)
        database = root / "engineering.sqlite3"
        with EngineeringStore(database):
            pass

        durations: list[float] = []

        def write(index: int) -> None:
            started = time.perf_counter_ns()
            with EngineeringStore(database) as store:
                store.issue_work_envelope(
                    _envelope(index, now + 10_000_000_000),
                    now_ns=now + index,
                )
            durations.append((time.perf_counter_ns() - started) / 1_000_000)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            list(executor.map(write, range(iterations)))

        for offset in range(crash_cycles):
            index = iterations + offset
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--child",
                    "--database",
                    str(database),
                    "--index",
                    str(index),
                    "--now",
                    str(now + index),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError("operational_stress_child_failed")
            with EngineeringStore(database) as reopened:
                reopened.verify_audit_chain()

        with EngineeringStore(database) as store:
            store.verify_audit_chain()
            audit_events = int(
                store.connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
            )
            envelopes = int(
                store.connection.execute("SELECT COUNT(*) FROM work_envelopes").fetchone()[0]
            )
            checkpoint = store.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            disk_full = _measure_disk_full_rollback(
                database,
                root / "disk-full.sqlite3",
                _envelope(iterations + crash_cycles + 1, now + 10_000_000_000),
            )
        wal = Path(str(database) + "-wal")
        result: dict[str, object] = {
            "schema": "hepta.control-engineering-operational-stress.v1",
            "iterations": iterations,
            "workers": workers,
            "crashCycles": crash_cycles,
            "envelopes": envelopes,
            "auditEvents": audit_events,
            "databaseBytes": database.stat().st_size,
            "walBytesAfterCheckpoint": wal.stat().st_size if wal.exists() else 0,
            "writeMillis": {
                "minimum": round(min(durations), 3),
                "median": round(statistics.median(durations), 3),
                "p95": _percentile(durations, 0.95),
                "maximum": round(max(durations), 3),
            },
            "walCheckpoint": tuple(int(value) for value in checkpoint),
            "diskFullRollback": disk_full,
            "authorityGranted": False,
        }
        if envelopes != iterations + crash_cycles or audit_events < envelopes:
            raise RuntimeError("operational_stress_durable_count_mismatch")
        if disk_full.get("observed") is not True:
            raise RuntimeError("operational_stress_disk_full_not_observed")
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--crash-cycles", type=int, default=5)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--index", type=int)
    parser.add_argument("--now", type=int)
    args = parser.parse_args()
    if args.child:
        if args.database is None or args.index is None or args.now is None:
            parser.error("child mode requires database, index, and now")
        return _child(args.database, args.index, args.now)
    result = build_stress_profile(
        iterations=args.iterations,
        workers=args.workers,
        crash_cycles=args.crash_cycles,
    )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
