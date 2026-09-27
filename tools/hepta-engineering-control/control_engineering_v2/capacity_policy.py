"""Measured SQLite capacity and migration policy for control.engineering.

The policy separates an early migration signal from a hard admission ceiling.
Crossing the migration threshold does not abort heartbeats, completion, recovery,
or terminal reconciliation; it only prevents the condition from being hidden.
Crossing a hard threshold rejects admission of *new* work at the product boundary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import time

from .control_plane import EngineeringError, EngineeringStore, semantic_digest


@dataclass(frozen=True)
class ControlCapacityPolicy:
    migration_database_bytes: int
    hard_database_bytes: int
    migration_wal_bytes: int
    hard_wal_bytes: int
    migration_audit_events: int
    hard_audit_events: int
    migration_active_claims: int
    hard_active_claims: int
    migration_active_leases: int
    hard_active_leases: int

    def __post_init__(self) -> None:
        pairs = (
            (self.migration_database_bytes, self.hard_database_bytes, "database_bytes"),
            (self.migration_wal_bytes, self.hard_wal_bytes, "wal_bytes"),
            (self.migration_audit_events, self.hard_audit_events, "audit_events"),
            (self.migration_active_claims, self.hard_active_claims, "active_claims"),
            (self.migration_active_leases, self.hard_active_leases, "active_leases"),
        )
        for migration, hard, label in pairs:
            if (
                type(migration) is not int
                or type(hard) is not int
                or migration < 1
                or hard < migration
            ):
                raise ValueError(f"invalid_capacity_policy_{label}")


# Repository/CI reference ceiling.  It is deliberately generous and is not an
# operational SLO.  A selected host must provide a measured policy no wider than
# this before production acceptance.
REFERENCE_CONTROL_CAPACITY_POLICY = ControlCapacityPolicy(
    migration_database_bytes=4 * 1024**3,
    hard_database_bytes=8 * 1024**3,
    migration_wal_bytes=512 * 1024**2,
    hard_wal_bytes=2 * 1024**3,
    migration_audit_events=5_000_000,
    hard_audit_events=10_000_000,
    migration_active_claims=50_000,
    hard_active_claims=100_000,
    migration_active_leases=50_000,
    hard_active_leases=100_000,
)


@dataclass(frozen=True)
class ControlCapacityMeasurement:
    observed_unix_ns: int
    database_bytes: int
    wal_bytes: int
    audit_events: int
    active_claims: int
    awaiting_completion_claims: int
    active_leases: int
    active_workers: int
    open_integration_items: int


@dataclass(frozen=True)
class ControlCapacityDecision:
    state: str
    write_admitted: bool
    migration_recommended: bool
    migration_reasons: tuple[str, ...]
    hard_limit_reasons: tuple[str, ...]
    measurement: ControlCapacityMeasurement
    measurement_digest: str
    runtime_authority: bool = False
    merge_authority: bool = False
    release_authority: bool = False


def _count(store: EngineeringStore, query: str, parameters: tuple[object, ...] = ()) -> int:
    return int(store.connection.execute(query, parameters).fetchone()[0])


def _database_path(store: EngineeringStore) -> Path | None:
    for row in store.connection.execute("PRAGMA database_list").fetchall():
        if str(row[1]) == "main":
            raw = str(row[2])
            return Path(raw) if raw else None
    raise EngineeringError("control_capacity_database_unknown")


def measure_control_capacity(
    store: EngineeringStore,
    *,
    now_ns: int | None = None,
) -> ControlCapacityMeasurement:
    if not isinstance(store, EngineeringStore):
        raise EngineeringError("control_capacity_store_required")
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise EngineeringError("invalid_time")
    path = _database_path(store)
    database_bytes = 0
    wal_bytes = 0
    if path is not None:
        try:
            database_bytes = path.stat().st_size
        except FileNotFoundError:
            database_bytes = 0
        wal = Path(str(path) + "-wal")
        try:
            wal_bytes = wal.stat().st_size
        except FileNotFoundError:
            wal_bytes = 0
    return ControlCapacityMeasurement(
        observed_unix_ns=now,
        database_bytes=database_bytes,
        wal_bytes=wal_bytes,
        audit_events=_count(store, "SELECT COUNT(*) FROM audit_events"),
        active_claims=_count(
            store,
            "SELECT COUNT(*) FROM worker_claims "
            "WHERE state IN ('claimed','running')",
        ),
        awaiting_completion_claims=_count(
            store,
            "SELECT COUNT(*) FROM worker_claims WHERE state='result_submitted'",
        ),
        active_leases=_count(
            store,
            "SELECT COUNT(*) FROM path_leases WHERE state='active' AND expires_unix_ns>?",
            (now,),
        ),
        active_workers=_count(
            store,
            "SELECT COUNT(*) FROM worker_registrations "
            "WHERE state='active' AND expires_unix_ns>?",
            (now,),
        ),
        open_integration_items=_count(
            store,
            "SELECT COUNT(*) FROM integration_queue_items "
            "WHERE state NOT IN ('terminal_merged','terminal_failed','invalidated')",
        ),
    )


def evaluate_control_capacity(
    store: EngineeringStore,
    policy: ControlCapacityPolicy = REFERENCE_CONTROL_CAPACITY_POLICY,
    *,
    now_ns: int | None = None,
) -> ControlCapacityDecision:
    if not isinstance(policy, ControlCapacityPolicy):
        raise EngineeringError("control_capacity_policy_required")
    measurement = measure_control_capacity(store, now_ns=now_ns)
    metrics = (
        (
            "database_bytes",
            measurement.database_bytes,
            policy.migration_database_bytes,
            policy.hard_database_bytes,
        ),
        (
            "wal_bytes",
            measurement.wal_bytes,
            policy.migration_wal_bytes,
            policy.hard_wal_bytes,
        ),
        (
            "audit_events",
            measurement.audit_events,
            policy.migration_audit_events,
            policy.hard_audit_events,
        ),
        (
            "active_claims",
            measurement.active_claims,
            policy.migration_active_claims,
            policy.hard_active_claims,
        ),
        (
            "active_leases",
            measurement.active_leases,
            policy.migration_active_leases,
            policy.hard_active_leases,
        ),
    )
    migration = tuple(label for label, value, threshold, _hard in metrics if value >= threshold)
    hard = tuple(label for label, value, _migration, threshold in metrics if value >= threshold)
    state = "hard_limit" if hard else ("migration_due" if migration else "healthy")
    digest = semantic_digest(
        {
            "measurement": asdict(measurement),
            "policy": asdict(policy),
        }
    )
    return ControlCapacityDecision(
        state=state,
        write_admitted=not hard,
        migration_recommended=bool(migration),
        migration_reasons=migration,
        hard_limit_reasons=hard,
        measurement=measurement,
        measurement_digest=digest,
    )


def require_new_work_capacity(
    store: EngineeringStore,
    policy: ControlCapacityPolicy = REFERENCE_CONTROL_CAPACITY_POLICY,
    *,
    now_ns: int | None = None,
) -> ControlCapacityDecision:
    decision = evaluate_control_capacity(store, policy, now_ns=now_ns)
    if not decision.write_admitted:
        raise EngineeringError(
            "control_capacity_hard_limit:" + ",".join(decision.hard_limit_reasons)
        )
    return decision
