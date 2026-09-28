"""SQLite capacity observation and explicit migration thresholds."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .control_plane import EngineeringError, EngineeringStore, semantic_digest


@dataclass(frozen=True)
class EngineeringCapacityPolicy:
    maximum_database_bytes: int = 4 * 1024**3
    maximum_wal_bytes: int = 1024**3
    maximum_audit_events: int = 10_000_000
    maximum_active_claims: int = 100_000
    maximum_active_reservations: int = 100_000
    migration_trigger_ratio_q16: int = 52_429

    def __post_init__(self) -> None:
        values = (
            self.maximum_database_bytes,
            self.maximum_wal_bytes,
            self.maximum_audit_events,
            self.maximum_active_claims,
            self.maximum_active_reservations,
        )
        if any(type(value) is not int or value < 1 for value in values):
            raise EngineeringError("invalid_capacity_policy")
        if (
            type(self.migration_trigger_ratio_q16) is not int
            or not 1 <= self.migration_trigger_ratio_q16 <= 65_536
        ):
            raise EngineeringError("invalid_capacity_policy")


@dataclass(frozen=True)
class EngineeringCapacitySnapshot:
    database_bytes: int
    wal_bytes: int
    audit_events: int
    active_claims: int
    active_reservations: int
    page_count: int
    page_size: int
    measured_unix_ns: int


@dataclass(frozen=True)
class EngineeringCapacityDecision:
    state: str
    migration_required: bool
    warnings: tuple[str, ...]
    blockers: tuple[str, ...]
    snapshot_digest: str
    runtime_authority: bool = False
    deployment_authority: bool = False


def measure_engineering_capacity(
    store: EngineeringStore,
    *,
    now_ns: int | None = None,
) -> EngineeringCapacitySnapshot:
    if not isinstance(store, EngineeringStore):
        raise EngineeringError("capacity_store_required")
    now = store._now(now_ns)
    database = Path(store.database)
    wal = Path(str(database) + "-wal")
    page_count = int(store.connection.execute("PRAGMA page_count").fetchone()[0])
    page_size = int(store.connection.execute("PRAGMA page_size").fetchone()[0])
    audit_events = int(
        store.connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    )
    active_claims = int(
        store.connection.execute(
            "SELECT COUNT(*) FROM worker_claims WHERE state IN ('claimed','running')"
        ).fetchone()[0]
    )
    active_reservations = int(
        store.connection.execute(
            "SELECT COUNT(*) FROM worker_capacity_reservations WHERE state='active'"
        ).fetchone()[0]
    )
    return EngineeringCapacitySnapshot(
        database.stat().st_size if database.exists() else page_count * page_size,
        wal.stat().st_size if wal.exists() else 0,
        audit_events,
        active_claims,
        active_reservations,
        page_count,
        page_size,
        now,
    )


def evaluate_engineering_capacity(
    snapshot: EngineeringCapacitySnapshot,
    policy: EngineeringCapacityPolicy = EngineeringCapacityPolicy(),
) -> EngineeringCapacityDecision:
    if not isinstance(snapshot, EngineeringCapacitySnapshot):
        raise EngineeringError("capacity_snapshot_required")
    if not isinstance(policy, EngineeringCapacityPolicy):
        raise EngineeringError("capacity_policy_required")
    metrics = {
        "database_bytes": (snapshot.database_bytes, policy.maximum_database_bytes),
        "wal_bytes": (snapshot.wal_bytes, policy.maximum_wal_bytes),
        "audit_events": (snapshot.audit_events, policy.maximum_audit_events),
        "active_claims": (snapshot.active_claims, policy.maximum_active_claims),
        "active_reservations": (
            snapshot.active_reservations,
            policy.maximum_active_reservations,
        ),
    }
    warnings: list[str] = []
    blockers: list[str] = []
    for name, (value, maximum) in metrics.items():
        if type(value) is not int or value < 0:
            raise EngineeringError("capacity_snapshot_invalid")
        if value > maximum:
            blockers.append(name + "_limit_exceeded")
        elif value * 65_536 >= maximum * policy.migration_trigger_ratio_q16:
            warnings.append(name + "_migration_threshold")
    return EngineeringCapacityDecision(
        "blocked" if blockers else ("migration_required" if warnings else "nominal"),
        bool(blockers or warnings),
        tuple(sorted(warnings)),
        tuple(sorted(blockers)),
        semantic_digest(asdict(snapshot)),
    )
