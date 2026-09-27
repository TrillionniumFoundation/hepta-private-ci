"""Explicit target-host capacity and SQLite migration thresholds.

The module intentionally does not publish one universal threshold.  A production
composition supplies a reviewed profile for its host and workload; this code makes
the resulting decision deterministic and machine-verifiable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .control_plane import EngineeringError, checked_id, semantic_digest


@dataclass(frozen=True)
class SQLiteCapacityPolicy:
    profile_id: str
    maximum_database_bytes: int
    maximum_wal_bytes: int
    maximum_audit_events: int
    maximum_active_workers: int
    maximum_active_claims: int
    maximum_write_p95_millis: int
    maximum_recovery_p95_millis: int
    migrate_at_utilization_percent: int = 80

    def __post_init__(self) -> None:
        checked_id(self.profile_id, "capacity_profile_id")
        for value in (
            self.maximum_database_bytes,
            self.maximum_wal_bytes,
            self.maximum_audit_events,
            self.maximum_active_workers,
            self.maximum_active_claims,
            self.maximum_write_p95_millis,
            self.maximum_recovery_p95_millis,
        ):
            if type(value) is not int or value < 1:
                raise EngineeringError("invalid_capacity_policy")
        if (
            type(self.migrate_at_utilization_percent) is not int
            or not 1 <= self.migrate_at_utilization_percent <= 100
        ):
            raise EngineeringError("invalid_capacity_policy")


@dataclass(frozen=True)
class SQLiteCapacityObservation:
    database_bytes: int
    wal_bytes: int
    audit_events: int
    active_workers: int
    active_claims: int
    write_p95_millis: int
    recovery_p95_millis: int

    def __post_init__(self) -> None:
        if any(type(value) is not int or value < 0 for value in asdict(self).values()):
            raise EngineeringError("invalid_capacity_observation")


@dataclass(frozen=True)
class SQLiteCapacityDecision:
    profile_id: str
    within_hard_limits: bool
    migration_required: bool
    reasons: tuple[str, ...]
    policy_digest: str
    observation_digest: str
    runtime_authority: bool = False
    deployment_authority: bool = False
    release_authority: bool = False


def evaluate_sqlite_capacity(
    policy: SQLiteCapacityPolicy,
    observation: SQLiteCapacityObservation,
) -> SQLiteCapacityDecision:
    if not isinstance(policy, SQLiteCapacityPolicy):
        raise EngineeringError("capacity_policy_required")
    if not isinstance(observation, SQLiteCapacityObservation):
        raise EngineeringError("capacity_observation_required")
    dimensions = (
        ("database_bytes", observation.database_bytes, policy.maximum_database_bytes),
        ("wal_bytes", observation.wal_bytes, policy.maximum_wal_bytes),
        ("audit_events", observation.audit_events, policy.maximum_audit_events),
        ("active_workers", observation.active_workers, policy.maximum_active_workers),
        ("active_claims", observation.active_claims, policy.maximum_active_claims),
        (
            "write_p95_millis",
            observation.write_p95_millis,
            policy.maximum_write_p95_millis,
        ),
        (
            "recovery_p95_millis",
            observation.recovery_p95_millis,
            policy.maximum_recovery_p95_millis,
        ),
    )
    hard = tuple(name for name, actual, maximum in dimensions if actual > maximum)
    warning = tuple(
        name
        for name, actual, maximum in dimensions
        if actual <= maximum
        and actual * 100 >= maximum * policy.migrate_at_utilization_percent
    )
    reasons = tuple(f"hard_limit:{name}" for name in hard) + tuple(
        f"migration_threshold:{name}" for name in warning
    )
    return SQLiteCapacityDecision(
        profile_id=policy.profile_id,
        within_hard_limits=not hard,
        migration_required=bool(hard or warning),
        reasons=reasons,
        policy_digest=semantic_digest(asdict(policy)),
        observation_digest=semantic_digest(asdict(observation)),
    )
