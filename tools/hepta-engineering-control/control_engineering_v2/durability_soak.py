"""Bounded repeated-open and WAL/database growth qualification."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import statistics
import time

from .control_plane import EngineeringError, EngineeringStore, semantic_digest


@dataclass(frozen=True)
class DurabilitySoakReport:
    iterations: int
    minimum_open_millis: float
    median_open_millis: float
    p95_open_millis: float
    maximum_open_millis: float
    initial_database_bytes: int
    final_database_bytes: int
    maximum_wal_bytes: int
    audit_sequence: int
    audit_event_digest: str
    quick_check_passed: bool
    foreign_key_check_passed: bool
    report_digest: str
    runtime_authority: bool = False
    deployment_authority: bool = False


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * 0.95))
    return ordered[index]


def run_durability_soak(
    database: str | Path,
    *,
    iterations: int = 50,
) -> DurabilitySoakReport:
    if type(iterations) is not int or not 1 <= iterations <= 1_000:
        raise EngineeringError("durability_soak_iterations")
    path = Path(database)
    initial = path.stat().st_size if path.exists() else 0
    samples: list[float] = []
    maximum_wal = 0
    anchor: dict[str, object] | None = None
    quick = False
    foreign = False
    for _ in range(iterations):
        started = time.perf_counter_ns()
        with EngineeringStore(path) as store:
            store.verify_audit_chain()
            quick = tuple(
                str(row[0]) for row in store.connection.execute("PRAGMA quick_check")
            ) == ("ok",)
            foreign = store.connection.execute("PRAGMA foreign_key_check").fetchone() is None
            anchor = store.audit_anchor()
            store.connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        samples.append(round((time.perf_counter_ns() - started) / 1_000_000, 3))
        wal = Path(str(path) + "-wal")
        maximum_wal = max(maximum_wal, wal.stat().st_size if wal.exists() else 0)
    assert anchor is not None
    provisional = DurabilitySoakReport(
        iterations,
        min(samples),
        round(statistics.median(samples), 3),
        _p95(samples),
        max(samples),
        initial,
        path.stat().st_size if path.exists() else 0,
        maximum_wal,
        int(anchor["sequence"]),
        str(anchor["eventDigest"]),
        quick,
        foreign,
        "0" * 64,
    )
    body = asdict(provisional)
    body.pop("report_digest")
    return DurabilitySoakReport(
        **{**asdict(provisional), "report_digest": semantic_digest(body)}
    )
