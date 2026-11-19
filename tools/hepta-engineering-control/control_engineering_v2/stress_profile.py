"""Bounded concurrency, WAL, crash/reopen, and growth stress profile.

The default is suitable for a focused CI lane.  A scheduled qualification may
raise duration and record counts, but the profile remains measurement evidence
only and grants no production authority.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from .control_plane import (
    DENIED_AUTHORITIES,
    EngineeringStore,
    WorkEnvelope,
    semantic_digest,
)
from .external_controls import store_snapshot_digest


@dataclass(frozen=True)
class EngineeringStressReport:
    schema: str
    source_commit: str
    source_tree: str
    workers: int
    requested_records: int
    committed_records: int
    elapsed_millis: float
    database_bytes: int
    wal_bytes: int
    reopen_cycles: int
    crash_exit_code: int
    crash_transaction_rolled_back: bool
    audit_chain_verified: bool
    snapshot_digest: str
    runtime_authority: bool = False
    merge_authority: bool = False
    release_authority: bool = False
    deployment_accepted: bool = False


def _envelope(index: int, source_commit: str, source_tree: str, now: int) -> WorkEnvelope:
    return WorkEnvelope(
        f"stress-envelope-{index}",
        source_commit,
        source_tree,
        hashlib.sha256(f"stress-objective-{index}".encode()).hexdigest(),
        hashlib.sha256(b"hepta.control-engineering.stress.v1").hexdigest(),
        "developer-productivity",
        (f"stress/{index}",),
        tuple(sorted(DENIED_AUTHORITIES)),
        1,
        now + 60_000_000_000,
    )


def _crash_uncommitted(database: Path) -> int:
    code = (
        "import os,sqlite3,sys; "
        "c=sqlite3.connect(sys.argv[1]); "
        "c.execute('PRAGMA foreign_keys=ON'); "
        "c.execute('BEGIN IMMEDIATE'); "
        "c.execute(\"UPDATE work_envelopes SET revision=revision+1000 "
        "WHERE envelope_id=(SELECT envelope_id FROM work_envelopes LIMIT 1)\"); "
        "os._exit(77)"
    )
    return subprocess.run(
        [sys.executable, "-I", "-c", code, str(database)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=20,
    ).returncode


def run_engineering_stress(
    database: str | Path,
    *,
    source_commit: str,
    source_tree: str,
    workers: int = 4,
    records: int = 400,
    reopen_cycles: int = 25,
) -> EngineeringStressReport:
    if (
        type(workers) is not int
        or not 1 <= workers <= 32
        or type(records) is not int
        or not 1 <= records <= 100_000
        or type(reopen_cycles) is not int
        or not 1 <= reopen_cycles <= 10_000
    ):
        raise ValueError("stress_profile_bounds")
    path = Path(database).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    now = 1_000_000_000
    with EngineeringStore(path):
        pass

    def write_partition(indices: tuple[int, ...]) -> int:
        committed = 0
        with EngineeringStore(path) as store:
            for index in indices:
                store.issue_work_envelope(
                    _envelope(index, source_commit, source_tree, now),
                    now_ns=now,
                )
                committed += 1
        return committed

    partitions = tuple(tuple(range(offset, records, workers)) for offset in range(workers))
    started = time.perf_counter_ns()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        committed = sum(executor.map(write_partition, partitions))
    elapsed = round((time.perf_counter_ns() - started) / 1_000_000, 3)

    before_crash: dict[str, int]
    with EngineeringStore(path) as store:
        before_crash = {
            str(row["envelope_id"]): int(row["revision"])
            for row in store.connection.execute(
                "SELECT envelope_id,revision FROM work_envelopes"
            ).fetchall()
        }
    crash_exit = _crash_uncommitted(path)
    if crash_exit != 77:
        raise RuntimeError("stress_crash_probe_failed")
    with EngineeringStore(path) as store:
        after_crash = {
            str(row["envelope_id"]): int(row["revision"])
            for row in store.connection.execute(
                "SELECT envelope_id,revision FROM work_envelopes"
            ).fetchall()
        }
        if after_crash != before_crash:
            raise RuntimeError("stress_crash_transaction_visible")

    snapshot = ""
    for _ in range(reopen_cycles):
        with EngineeringStore(path) as store:
            store.verify_audit_chain()
            snapshot = store_snapshot_digest(store)
            observed = int(
                store.connection.execute("SELECT COUNT(*) FROM work_envelopes").fetchone()[0]
            )
            if observed != records:
                raise RuntimeError("stress_record_count_mismatch")
    wal = Path(str(path) + "-wal")
    return EngineeringStressReport(
        schema="hepta.control-engineering-stress-profile.v1",
        source_commit=source_commit,
        source_tree=source_tree,
        workers=workers,
        requested_records=records,
        committed_records=committed,
        elapsed_millis=elapsed,
        database_bytes=path.stat().st_size,
        wal_bytes=wal.stat().st_size if wal.exists() else 0,
        reopen_cycles=reopen_cycles,
        crash_exit_code=crash_exit,
        crash_transaction_rolled_back=(after_crash == before_crash),
        audit_chain_verified=True,
        snapshot_digest=snapshot,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--records", type=int, default=400)
    parser.add_argument("--reopen-cycles", type=int, default=25)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = run_engineering_stress(
            args.database,
            source_commit=args.source_commit,
            source_tree=args.source_tree,
            workers=args.workers,
            records=args.records,
            reopen_cycles=args.reopen_cycles,
        )
    except (OSError, RuntimeError, ValueError, sqlite3.DatabaseError) as error:
        print(
            json.dumps(
                {
                    "status": "rejected",
                    "error": str(error),
                    "authorityGranted": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
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
