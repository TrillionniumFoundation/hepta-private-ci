"""Target-host SQLite capacity and migration-threshold projection."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .control_plane import EngineeringError, EngineeringStore, semantic_digest


@dataclass(frozen=True)
class StoreCapacityPolicy:
    maximum_database_bytes: int = 4 * 1024**3
    maximum_wal_bytes: int = 1024**3
    maximum_audit_events: int = 10_000_000
    maximum_active_claims: int = 100_000
    migration_database_bytes: int = 2 * 1024**3
    migration_audit_events: int = 5_000_000

    def __post_init__(self) -> None:
        values = asdict(self)
        if any(type(value) is not int or value < 1 for value in values.values()):
            raise EngineeringError("invalid_store_capacity_policy")
        if self.migration_database_bytes > self.maximum_database_bytes:
            raise EngineeringError("invalid_store_migration_database_threshold")
        if self.migration_audit_events > self.maximum_audit_events:
            raise EngineeringError("invalid_store_migration_audit_threshold")


def evaluate_store_capacity(
    store: EngineeringStore,
    policy: StoreCapacityPolicy = StoreCapacityPolicy(),
) -> dict[str, object]:
    if not isinstance(store, EngineeringStore) or not isinstance(
        policy, StoreCapacityPolicy
    ):
        raise EngineeringError("store_capacity_input")
    page_count = int(store.connection.execute("PRAGMA page_count").fetchone()[0])
    page_size = int(store.connection.execute("PRAGMA page_size").fetchone()[0])
    database_bytes = page_count * page_size
    wal_path = Path(str(store.database) + "-wal")
    wal_bytes = wal_path.stat().st_size if wal_path.exists() else 0
    audit_events = int(
        store.connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    )
    active_claims = int(
        store.connection.execute(
            "SELECT COUNT(*) FROM worker_claims "
            "WHERE state IN ('claimed','running')"
        ).fetchone()[0]
    )
    hard_failures = []
    if database_bytes > policy.maximum_database_bytes:
        hard_failures.append("database_bytes")
    if wal_bytes > policy.maximum_wal_bytes:
        hard_failures.append("wal_bytes")
    if audit_events > policy.maximum_audit_events:
        hard_failures.append("audit_events")
    if active_claims > policy.maximum_active_claims:
        hard_failures.append("active_claims")
    migration_recommended = (
        database_bytes >= policy.migration_database_bytes
        or audit_events >= policy.migration_audit_events
    )
    observation = {
        "databaseBytes": database_bytes,
        "walBytes": wal_bytes,
        "auditEvents": audit_events,
        "activeClaims": active_claims,
        "hardFailures": tuple(hard_failures),
        "migrationRecommended": migration_recommended,
        "policy": asdict(policy),
        "productionAccepted": False,
        "releaseAuthority": False,
    }
    return {**observation, "observationDigest": semantic_digest(observation)}
