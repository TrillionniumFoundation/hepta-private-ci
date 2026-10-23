"""SQLite capacity measurement, hard admission ceilings and migration signals."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .control_plane import EngineeringError, EngineeringStore, semantic_digest

_Q16 = 1 << 16


@dataclass(frozen=True)
class DatabaseCapacityPolicy:
    maximum_database_bytes: int = 4 * 1024**3
    maximum_wal_bytes: int = 512 * 1024**2
    maximum_audit_events: int = 5_000_000
    maximum_active_leases: int = 4_096
    maximum_active_claims: int = 4_096
    maximum_active_reservations: int = 4_096
    migration_trigger_q16: int = 49_152  # 75 percent

    def __post_init__(self) -> None:
        limits = (
            self.maximum_database_bytes,
            self.maximum_wal_bytes,
            self.maximum_audit_events,
            self.maximum_active_leases,
            self.maximum_active_claims,
            self.maximum_active_reservations,
        )
        if any(type(value) is not int or value < 1 for value in limits):
            raise EngineeringError("invalid_capacity_policy")
        if (
            type(self.migration_trigger_q16) is not int
            or not 1 <= self.migration_trigger_q16 < _Q16
        ):
            raise EngineeringError("invalid_capacity_policy")


@dataclass(frozen=True)
class DatabaseCapacityDecision:
    database_bytes: int
    wal_bytes: int
    audit_events: int
    active_leases: int
    active_claims: int
    active_reservations: int
    maximum_utilization_q16: int
    migration_recommended: bool
    hard_limit_exceeded: bool
    exceeded_dimensions: tuple[str, ...]
    policy_digest: str
    measurement_digest: str
    runtime_authority: bool = False
    release_authority: bool = False


def _database_path(store: EngineeringStore) -> Path | None:
    rows = store.connection.execute("PRAGMA database_list").fetchall()
    for row in rows:
        if str(row[1]) == "main" and str(row[2]):
            return Path(str(row[2]))
    return None


def _ratio(value: int, maximum: int) -> int:
    return min(2 * _Q16, (value * _Q16) // maximum)


def evaluate_database_capacity(
    store: EngineeringStore,
    policy: DatabaseCapacityPolicy = DatabaseCapacityPolicy(),
) -> DatabaseCapacityDecision:
    if not isinstance(store, EngineeringStore):
        raise EngineeringError("capacity_store_required")
    if not isinstance(policy, DatabaseCapacityPolicy):
        raise EngineeringError("invalid_capacity_policy")
    page_count = int(store.connection.execute("PRAGMA page_count").fetchone()[0])
    page_size = int(store.connection.execute("PRAGMA page_size").fetchone()[0])
    database_bytes = page_count * page_size
    path = _database_path(store)
    wal_path = None if path is None else Path(str(path) + "-wal")
    wal_bytes = wal_path.stat().st_size if wal_path is not None and wal_path.exists() else 0
    audit_events = int(store.connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])
    active_leases = int(
        store.connection.execute(
            "SELECT COUNT(*) FROM path_leases WHERE state='active'"
        ).fetchone()[0]
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
    measurements = {
        "database_bytes": database_bytes,
        "wal_bytes": wal_bytes,
        "audit_events": audit_events,
        "active_leases": active_leases,
        "active_claims": active_claims,
        "active_reservations": active_reservations,
    }
    maxima = {
        "database_bytes": policy.maximum_database_bytes,
        "wal_bytes": policy.maximum_wal_bytes,
        "audit_events": policy.maximum_audit_events,
        "active_leases": policy.maximum_active_leases,
        "active_claims": policy.maximum_active_claims,
        "active_reservations": policy.maximum_active_reservations,
    }
    ratios = {name: _ratio(measurements[name], maximum) for name, maximum in maxima.items()}
    exceeded = tuple(sorted(name for name in maxima if measurements[name] > maxima[name]))
    maximum_utilization = max(ratios.values(), default=0)
    return DatabaseCapacityDecision(
        database_bytes,
        wal_bytes,
        audit_events,
        active_leases,
        active_claims,
        active_reservations,
        maximum_utilization,
        maximum_utilization >= policy.migration_trigger_q16,
        bool(exceeded),
        exceeded,
        semantic_digest(asdict(policy)),
        semantic_digest({"measurements": measurements, "ratios": ratios}),
    )


def enforce_database_capacity(
    store: EngineeringStore,
    policy: DatabaseCapacityPolicy = DatabaseCapacityPolicy(),
) -> DatabaseCapacityDecision:
    decision = evaluate_database_capacity(store, policy)
    if decision.hard_limit_exceeded:
        raise EngineeringError(
            "database_capacity_exceeded:" + ",".join(decision.exceeded_dimensions)
        )
    return decision
