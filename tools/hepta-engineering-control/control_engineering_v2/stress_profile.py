"""Bounded contention, growth, WAL and reopen profile for target hosts."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import statistics
import tempfile
import time

from .capacity_policy import StoreCapacityPolicy, evaluate_store_capacity
from .control_plane import DENIED_AUTHORITIES, EngineeringStore, WorkEnvelope

_SCHEMA = "hepta.control-engineering-stress-profile.v1"


def _millis(start: int) -> float:
    return round((time.perf_counter_ns() - start) / 1_000_000, 3)


def build_stress_profile(
    *,
    records: int = 256,
    writers: int = 4,
    reopen_cycles: int = 16,
) -> dict[str, object]:
    if type(records) is not int or not 1 <= records <= 100_000:
        raise ValueError("stress_records")
    if type(writers) is not int or not 1 <= writers <= 32:
        raise ValueError("stress_writers")
    if type(reopen_cycles) is not int or not 1 <= reopen_cycles <= 1000:
        raise ValueError("stress_reopen_cycles")
    now = 1_000_000
    with tempfile.TemporaryDirectory(prefix="hepta-control-stress-") as temporary:
        database = Path(temporary) / "engineering.sqlite3"
        with EngineeringStore(database):
            pass

        def write_one(index: int) -> float:
            started = time.perf_counter_ns()
            value = str(index).encode("ascii")
            envelope = WorkEnvelope(
                f"stress-envelope-{index}",
                hashlib.sha1(b"source-" + value).hexdigest(),
                hashlib.sha1(b"tree-" + value).hexdigest(),
                hashlib.sha256(b"objective-" + value).hexdigest(),
                hashlib.sha256(b"contract-" + value).hexdigest(),
                "stress-profile",
                (f"stress/{index}",),
                tuple(sorted(DENIED_AUTHORITIES)),
                1,
                now + 10_000_000_000,
            )
            with EngineeringStore(database) as store:
                store.issue_work_envelope(envelope, now_ns=now + index)
            return _millis(started)

        write_started = time.perf_counter_ns()
        with ThreadPoolExecutor(max_workers=writers) as executor:
            latencies = list(executor.map(write_one, range(records)))
        total_write_millis = _millis(write_started)

        reopen_samples = []
        for _ in range(reopen_cycles):
            started = time.perf_counter_ns()
            with EngineeringStore(database) as store:
                store.verify_audit_chain()
            reopen_samples.append(_millis(started))

        with EngineeringStore(database) as store:
            event_count = int(
                store.connection.execute(
                    "SELECT COUNT(*) FROM audit_events"
                ).fetchone()[0]
            )
            envelope_count = int(
                store.connection.execute(
                    "SELECT COUNT(*) FROM work_envelopes"
                ).fetchone()[0]
            )
            if event_count != records or envelope_count != records:
                raise RuntimeError("stress_write_count_mismatch")
            checkpoint = tuple(
                int(value)
                for value in store.connection.execute(
                    "PRAGMA wal_checkpoint(PASSIVE)"
                ).fetchone()
            )
            capacity = evaluate_store_capacity(store, StoreCapacityPolicy())
            store.verify_audit_chain()
            anchor = store.audit_anchor()

        ordered = sorted(latencies)
        p95 = ordered[min(len(ordered) - 1, int((len(ordered) - 1) * 0.95))]
        result = {
            "schema": _SCHEMA,
            "records": records,
            "writers": writers,
            "reopenCycles": reopen_cycles,
            "write": {
                "totalMillis": total_write_millis,
                "medianMillis": round(statistics.median(latencies), 3),
                "p95Millis": round(p95, 3),
                "maximumMillis": round(max(latencies), 3),
            },
            "reopen": {
                "medianMillis": round(statistics.median(reopen_samples), 3),
                "maximumMillis": round(max(reopen_samples), 3),
            },
            "walCheckpoint": checkpoint,
            "capacity": capacity,
            "auditAnchor": anchor,
            "runtimeAuthority": False,
            "mergeAuthority": False,
            "releaseAuthority": False,
            "deploymentAccepted": False,
        }
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=int, default=256)
    parser.add_argument("--writers", type=int, default=4)
    parser.add_argument("--reopen-cycles", type=int, default=16)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = build_stress_profile(
            records=args.records,
            writers=args.writers,
            reopen_cycles=args.reopen_cycles,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(json.dumps({"schema": _SCHEMA, "error": str(error)}))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
