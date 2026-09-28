"""Owner-database capacity observations; never execution authorization.

The optional monitor is a connection-local TEMP projection. The persistent
EngineeringStore remains the sole fact owner. Its ordinary writes update the
projection in the same SQLite transaction; another connection's commit causes
rebuild, not reuse of a stale observation. Initial rebuild and calibration scan
history explicitly and are not advertised as constant-time operations.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import sqlite3
import time

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


@dataclass(frozen=True)
class StoreCapacityCounts:
    audit_events: int
    active_claims: int


def _actual_counts(connection: sqlite3.Connection) -> StoreCapacityCounts:
    row = connection.execute(
        "SELECT (SELECT COUNT(*) FROM main.audit_events),"
        "(SELECT COUNT(*) FROM main.worker_claims WHERE state IN ('claimed','running'))"
    ).fetchone()
    return StoreCapacityCounts(int(row[0]), int(row[1]))


class StoreCapacityMonitor:
    """One derived counter projection for one owner connection lifetime.

    Only counts are reused: no policy result, grant, revocation decision or
    authorization is cached. Nested caller transactions bypass caching. A
    detected calibration mismatch quarantines this monitor until owner reopen.
    """

    def __init__(self, store: EngineeringStore, *, calibration_interval_ns: int = 60_000_000_000):
        if not isinstance(store, EngineeringStore):
            raise EngineeringError("store_capacity_input")
        if type(calibration_interval_ns) is not int or calibration_interval_ns < 1:
            raise EngineeringError("invalid_capacity_calibration_interval")
        self._store = store
        self._interval = calibration_interval_ns
        self._version: int | None = None
        self._last_calibration = 0
        self._quarantined = False
        connection = store.connection
        if connection.in_transaction:
            raise EngineeringError("capacity_monitor_requires_idle_owner")
        if connection.execute(
            "SELECT 1 FROM sqlite_temp_master WHERE name='_ce_capacity_counts'"
        ).fetchone() is not None:
            raise EngineeringError("capacity_monitor_already_exists")
        before = self._data_version()
        connection.execute("BEGIN")
        try:
            connection.execute(
                "CREATE TEMP TABLE _ce_capacity_counts ("
                "singleton INTEGER PRIMARY KEY CHECK(singleton=1),"
                "audit_events INTEGER NOT NULL CHECK(audit_events>=0),"
                "active_claims INTEGER NOT NULL CHECK(active_claims>=0))"
            )
            counts = _actual_counts(connection)
            connection.execute(
                "INSERT INTO _ce_capacity_counts VALUES(1,?,?)",
                (counts.audit_events, counts.active_claims),
            )
            for name, clause, body in (
                ("audit_insert", "AFTER INSERT ON main.audit_events",
                 "audit_events=audit_events+1"),
                ("audit_delete", "AFTER DELETE ON main.audit_events",
                 "audit_events=audit_events-1"),
                ("claim_insert", "AFTER INSERT ON main.worker_claims",
                 "active_claims=active_claims+(NEW.state IN ('claimed','running'))"),
                ("claim_delete", "AFTER DELETE ON main.worker_claims",
                 "active_claims=active_claims-(OLD.state IN ('claimed','running'))"),
                ("claim_update", "AFTER UPDATE OF state ON main.worker_claims",
                 "active_claims=active_claims+(NEW.state IN ('claimed','running'))"
                 "-(OLD.state IN ('claimed','running'))"),
            ):
                # All identifiers and SQL fragments above are fixed literals.
                connection.execute(
                    f"CREATE TEMP TRIGGER _ce_capacity_{name} {clause} BEGIN "
                    f"UPDATE _ce_capacity_counts SET {body} WHERE singleton=1; END"
                )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        after = self._data_version()
        self._version = after if before == after else None
        self._last_calibration = time.monotonic_ns()

    def _data_version(self) -> int:
        return int(self._store.connection.execute("PRAGMA main.data_version").fetchone()[0])

    def _cached_counts(self) -> StoreCapacityCounts:
        row = self._store.connection.execute(
            "SELECT audit_events,active_claims FROM _ce_capacity_counts WHERE singleton=1"
        ).fetchone()
        if row is None:
            raise EngineeringError("capacity_projection_missing")
        return StoreCapacityCounts(int(row[0]), int(row[1]))

    def _observe(self, *, calibrate: bool) -> StoreCapacityCounts:
        if self._quarantined:
            raise EngineeringError("capacity_projection_quarantined")
        connection = self._store.connection
        if connection.in_transaction:
            # The caller may later roll back. Never publish a Python cache
            # generation from such a transaction or finish its transaction.
            self._version = None
            return _actual_counts(connection)
        for _ in range(3):
            before = self._data_version()
            connection.execute("BEGIN")
            now = time.monotonic_ns()
            refreshed = False
            try:
                # Pin a main-database read snapshot even on a TEMP-cache hit.
                connection.execute("SELECT sequence FROM main.audit_events LIMIT 1").fetchone()
                cached = self._cached_counts()
                if self._version != before:
                    counts = _actual_counts(connection)
                    connection.execute(
                        "UPDATE _ce_capacity_counts SET audit_events=?,active_claims=? WHERE singleton=1",
                        (counts.audit_events, counts.active_claims),
                    )
                    refreshed = True
                elif calibrate or now - self._last_calibration >= self._interval:
                    counts = _actual_counts(connection)
                    if counts != cached:
                        self._quarantined = True
                        raise EngineeringError("capacity_projection_drift")
                    refreshed = True
                else:
                    counts = cached
                connection.commit()
            except BaseException:
                connection.rollback()
                self._version = None
                raise
            after = self._data_version()
            if before != after:
                # Includes a writer committing between the initial version read
                # and snapshot acquisition. Retry boundedly; do not relabel old
                # counts with a newer data_version.
                self._version = None
                continue
            self._version = after
            if refreshed:
                self._last_calibration = now
            return counts
        raise EngineeringError("capacity_observation_changed")

    def observe(self) -> StoreCapacityCounts:
        return self._observe(calibrate=False)

    def reconcile(self) -> StoreCapacityCounts:
        """Compare derived counts with owner facts, rejecting unexplained drift."""
        return self._observe(calibrate=True)

    def counts_for(self, store: EngineeringStore) -> StoreCapacityCounts:
        if store is not self._store or store.connection is not self._store.connection:
            raise EngineeringError("capacity_monitor_owner_mismatch")
        return self.observe()


def evaluate_store_capacity(
    store: EngineeringStore,
    policy: StoreCapacityPolicy = StoreCapacityPolicy(),
    *,
    monitor: StoreCapacityMonitor | None = None,
) -> dict[str, object]:
    if not isinstance(store, EngineeringStore) or not isinstance(policy, StoreCapacityPolicy):
        raise EngineeringError("store_capacity_input")
    if monitor is not None and not isinstance(monitor, StoreCapacityMonitor):
        raise EngineeringError("store_capacity_monitor_required")
    counts = _actual_counts(store.connection) if monitor is None else monitor.counts_for(store)
    page_count = int(store.connection.execute("PRAGMA page_count").fetchone()[0])
    page_size = int(store.connection.execute("PRAGMA page_size").fetchone()[0])
    database_bytes = page_count * page_size
    wal_path = Path(str(store.database) + "-wal")
    try:
        wal_bytes = wal_path.stat().st_size
    except FileNotFoundError:
        wal_bytes = 0
    hard_failures: list[str] = []
    if database_bytes > policy.maximum_database_bytes:
        hard_failures.append("database_bytes")
    if wal_bytes > policy.maximum_wal_bytes:
        hard_failures.append("wal_bytes")
    if counts.audit_events > policy.maximum_audit_events:
        hard_failures.append("audit_events")
    if counts.active_claims > policy.maximum_active_claims:
        hard_failures.append("active_claims")
    migration_recommended = (
        database_bytes >= policy.migration_database_bytes
        or counts.audit_events >= policy.migration_audit_events
    )
    observation = {
        "databaseBytes": database_bytes,
        "walBytes": wal_bytes,
        "auditEvents": counts.audit_events,
        "activeClaims": counts.active_claims,
        "capacityScope": "owner_database",
        "physicalSamplesAtomicWithCounts": False,
        "hardFailures": tuple(hard_failures),
        "migrationRecommended": migration_recommended,
        "policy": asdict(policy),
        "productionAccepted": False,
        "releaseAuthority": False,
    }
    return {**observation, "observationDigest": semantic_digest(observation)}
