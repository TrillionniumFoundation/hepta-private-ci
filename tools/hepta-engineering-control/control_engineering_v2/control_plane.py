"""Durable, bounded engineering-control owner state for Lane G.

This module owns only engineering coordination facts. It deliberately cannot
merge, activate, promote, release, deploy, or grant runtime authority.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Any

from .path_policy import (
    canonical_repo_path as canonical_repo_path,
    canonical_paths as canonical_paths,
    paths_overlap as paths_overlap,
    path_sets_overlap as path_sets_overlap,
    path_is_within as path_is_within,
)

STORE_SCHEMA_VERSION = 10
STORE_TABLES = frozenset(
    {
        "work_envelopes",
        "path_leases",
        "assignment_generations",
        "orchestration_generations",
        "worker_registrations",
        "worker_claims",
        "worker_capacity_reservations",
        "worker_heartbeat_observations",
        "worker_result_observations",
        "worker_completion_observations",
        "integration_queue_generations",
        "integration_queue_items",
        "distributed_cluster_frontiers",
        "distributed_fence_frontiers",
        "integration_decisions",
        "audit_events",
        "engineering_schema_meta",
        "assignment_generation_frontiers",
        "integration_decision_bindings",
        "integration_decision_seals",
    }
)

MAX_ID_BYTES = 128
MAX_PATH_BYTES = 1024
MAX_PATHS = 256
MAX_PACKAGES = 4096
MAX_ACTIVE_LEASES = 4096
MAX_COMPLETED = 4096
MAX_PREDECESSORS = 256
MAX_ASSIGNMENTS = 128
MAX_REASONS = 128
MAX_AUDIT_ROWS = 512
ZERO_DIGEST = "0" * 64
DENIED_AUTHORITIES = frozenset(
    {
        "runtime_authority",
        "merge_authority",
        "activation_authority",
        "promotion_authority",
        "release_authority",
        "external_effect_authority",
    }
)

_CAPACITY_HOLDING_STATES = frozenset({"claimed", "running"})


def _schema_sql_path() -> Path:
    return Path(__file__).with_name("SCHEMA.sql")


def _normalize_schema_sql(value: str | None) -> str | None:
    if value is None:
        return None
    # SQL keywords are case-insensitive; quoted literals are not. Normalizing
    # their case/whitespace would accept a different CHECK or DEFAULT contract.
    parts = re.split(
        r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[[^\]]*\])",
        value,
    )
    for index in range(0, len(parts), 2):
        unquoted = re.sub(
            r"\bIF\s+NOT\s+EXISTS\b", "", parts[index], flags=re.IGNORECASE
        )
        parts[index] = re.sub(r"\s+", " ", unquoted).lower()
    return "".join(parts).strip()


def _schema_manifest(connection: sqlite3.Connection) -> dict[tuple[str, str], tuple[str, str | None]]:
    result: dict[tuple[str, str], tuple[str, str | None]] = {}
    for row in connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE type IN ('table','index','view','trigger') ORDER BY type,name"
    ):
        kind, name, table, sql = (str(row[0]), str(row[1]), str(row[2]), row[3])
        if name.startswith("sqlite_"):
            continue
        result[(kind, name)] = (table, _normalize_schema_sql(None if sql is None else str(sql)))
    return result


def _expected_schema_manifest() -> dict[tuple[str, str], tuple[str, str | None]]:
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(_schema_sql_path().read_text(encoding="utf-8"))
        return _schema_manifest(connection)
    finally:
        connection.close()


class EngineeringError(ValueError):
    """Fail-closed Lane G validation or state error."""

    def __init__(self, code: str):
        if not isinstance(code, str) or not code or len(code.encode("utf-8")) > 256:
            code = "invalid_engineering_error_code"
        super().__init__(code)
        self.code = code


def _error(code: str) -> None:
    raise EngineeringError(code)


def bounded_tuple(values: Iterable[Any], limit: int, code: str) -> tuple[Any, ...]:
    """Materialize at most *limit* values without exhausting an unbounded input."""
    if type(limit) is not int or limit < 0:
        _error("invalid_bound")
    iterator = iter(values)
    result: list[Any] = []
    for _ in range(limit + 1):
        try:
            result.append(next(iterator))
        except StopIteration:
            return tuple(result)
    _error(code)


def checked_id(value: str, label: str = "id") -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or len(value.encode("utf-8")) > MAX_ID_BYTES
    ):
        _error("invalid_" + label)
    return value


def checked_sha256(value: str, label: str = "digest") -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _error("invalid_" + label)
    return value


def _checked_git_sha1(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _error("invalid_" + label)
    return value


def _canonical_value(value: Any) -> Any:
    if is_dataclass(value):
        return _canonical_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_canonical_value(item) for item in value]
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    _error("noncanonical_value")


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            _canonical_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        _error("noncanonical_value")


def semantic_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


@dataclass(frozen=True)
class WorkEnvelope:
    envelope_id: str
    source_commit: str
    source_tree: str
    objective_digest: str
    contract_digest: str
    owner: str
    allowed_paths: tuple[str, ...]
    denied_authorities: tuple[str, ...]
    maximum_assignments: int
    expires_unix_ns: int
    revision: int = 1


@dataclass(frozen=True, order=True)
class WorkPackage:
    priority: int
    package_id: str
    predecessors: tuple[str, ...]
    write_paths: tuple[str, ...]


@dataclass(frozen=True)
class LeaseReceipt:
    lease_id: str
    envelope_id: str
    holder: str
    paths: tuple[str, ...]
    state: str
    epoch: int
    fencing_token: int
    revision: int
    issued_unix_ns: int
    expires_unix_ns: int
    runtime_authority: bool = False
    merge_authority: bool = False
    activation_authority: bool = False
    promotion_authority: bool = False
    release_authority: bool = False


@dataclass(frozen=True)
class ScheduleReceipt:
    generation_id: str
    envelope_id: str
    assigned: tuple[str, ...]
    blocked: tuple[tuple[str, str], ...]
    created_unix_ns: int
    runtime_authority: bool = False
    merge_authority: bool = False
    activation_authority: bool = False
    promotion_authority: bool = False
    release_authority: bool = False


def _validate_envelope(value: WorkEnvelope) -> WorkEnvelope:
    if not isinstance(value, WorkEnvelope):
        _error("invalid_envelope")
    checked_id(value.envelope_id, "envelope_id")
    _checked_git_sha1(value.source_commit, "source_commit")
    _checked_git_sha1(value.source_tree, "source_tree")
    checked_sha256(value.objective_digest, "objective_digest")
    checked_sha256(value.contract_digest, "contract_digest")
    checked_id(value.owner, "owner")
    allowed = canonical_paths(value.allowed_paths)
    denied = bounded_tuple(
        value.denied_authorities,
        len(DENIED_AUTHORITIES),
        "authority_ceiling_incomplete",
    )
    if set(denied) != DENIED_AUTHORITIES or len(denied) != len(DENIED_AUTHORITIES):
        _error("authority_ceiling_incomplete")
    if (
        type(value.maximum_assignments) is not int
        or not 1 <= value.maximum_assignments <= MAX_ASSIGNMENTS
    ):
        _error("invalid_assignment_limit")
    if type(value.expires_unix_ns) is not int or value.expires_unix_ns <= 0:
        _error("invalid_envelope_expiry")
    if type(value.revision) is not int or value.revision < 1:
        _error("invalid_envelope_revision")
    return WorkEnvelope(
        value.envelope_id,
        value.source_commit,
        value.source_tree,
        value.objective_digest,
        value.contract_digest,
        value.owner,
        allowed,
        tuple(sorted(denied)),
        value.maximum_assignments,
        value.expires_unix_ns,
        value.revision,
    )


def _validate_package(value: WorkPackage) -> WorkPackage:
    if not isinstance(value, WorkPackage):
        _error("invalid_package")
    if type(value.priority) is not int:
        _error("invalid_package_priority")
    checked_id(value.package_id, "package_id")
    predecessors = bounded_tuple(
        value.predecessors,
        MAX_PREDECESSORS,
        "predecessor_limit_exceeded",
    )
    if any(not isinstance(item, str) for item in predecessors):
        _error("invalid_predecessor")
    normalized_predecessors = tuple(
        sorted({checked_id(item, "predecessor") for item in predecessors})
    )
    paths = canonical_paths(value.write_paths)
    return WorkPackage(
        value.priority,
        value.package_id,
        normalized_predecessors,
        paths,
    )


class EngineeringStore:
    """Single-writer SQLite owner for Lane G coordination projections."""

    def __init__(self, database: str | Path):
        self.database = Path(database)
        self.connection = sqlite3.connect(str(self.database), timeout=30.0)
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute("PRAGMA foreign_keys=ON")
            version, metadata_version, tables = self._schema_version_state()
            if version > STORE_SCHEMA_VERSION or (
                metadata_version is not None and metadata_version > STORE_SCHEMA_VERSION
            ):
                _error("unsupported_future_store_schema")
            if version == STORE_SCHEMA_VERSION:
                if metadata_version != STORE_SCHEMA_VERSION:
                    _error("store_schema_version_mismatch")
                self._validate_schema_objects()
                self._configure_durability()
                # All owner invariants must describe one snapshot. A concurrent
                # claim/release must not split reservation and claim observations.
                with self._transaction():
                    locked_version, locked_metadata, _ = self._schema_version_state()
                    if (locked_version, locked_metadata) != (STORE_SCHEMA_VERSION, STORE_SCHEMA_VERSION):
                        _error("store_schema_version_mismatch")
                    self._validate_schema_objects()
                    self._validate_store_integrity()
                    self._verify_capacity_reservations()
                    self.verify_audit_chain()
            else:
                if version == 0:
                    if tables:
                        _error("store_schema_version_mismatch")
                elif metadata_version != version:
                    _error("store_schema_version_mismatch")
                self._configure_durability()
                # Schema creation/backfill, version publication and every startup
                # validation belong to one outer transaction.  A malformed or
                # unrecoverable predecessor must remain the same predecessor after
                # rejection instead of being stamped as the current schema.
                with self._transaction():
                    self._create_schema(version)
                    self._validate_schema_objects()
                    self._validate_store_integrity()
                    self._verify_capacity_reservations()
                    self.verify_audit_chain()
        except Exception:
            self.connection.close()
            raise

    def _schema_version_state(self) -> tuple[int, int | None, frozenset[str]]:
        version = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        tables = frozenset(
            str(row[0])
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        )
        metadata_version: int | None = None
        if "engineering_schema_meta" in tables:
            try:
                rows = self.connection.execute(
                    "SELECT singleton,schema_version FROM engineering_schema_meta"
                ).fetchall()
            except sqlite3.DatabaseError:
                _error("store_schema_incomplete")
            if len(rows) != 1 or int(rows[0]["singleton"]) != 1:
                _error("store_schema_incomplete")
            metadata_version = int(rows[0]["schema_version"])
        return version, metadata_version, tables

    def _configure_durability(self) -> None:
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")

    def _validate_schema_objects(self) -> None:
        expected = _expected_schema_manifest()
        actual = _schema_manifest(self.connection)
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        if missing:
            _error("store_schema_incomplete")
        if unexpected:
            _error("store_schema_unexpected_object")
        for key, expected_value in expected.items():
            if actual.get(key) != expected_value:
                _error("store_schema_definition_mismatch")

    def _validate_store_integrity(self) -> None:
        quick = tuple(str(row[0]) for row in self.connection.execute("PRAGMA quick_check"))
        if quick != ("ok",):
            _error("store_integrity_check_failed")
        if self.connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            _error("store_foreign_key_check_failed")

    def __enter__(self) -> "EngineeringStore":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if exc_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        self.connection.close()

    def close(self) -> None:
        """Durably flush successful owner writes before releasing the database."""
        try:
            self.connection.commit()
        finally:
            self.connection.close()

    @contextmanager
    def _transaction(self):
        """Own one immediate transaction across state, frontier and audit writes."""
        outermost = not self.connection.in_transaction
        if outermost:
            self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            if outermost:
                self.connection.commit()
        except BaseException:
            if outermost:
                self.connection.rollback()
            raise

    def _create_schema(self, source_version: int) -> None:
        schema = _schema_sql_path().read_text(encoding="utf-8")
        with self._transaction():
            statement = ""
            for line in schema.splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    self.connection.execute(statement)
                    statement = ""
            if statement.strip():
                _error("invalid_store_schema")
            self._backfill_capacity_reservations(source_version)
            metadata = self.connection.execute(
                "SELECT schema_version FROM engineering_schema_meta WHERE singleton=1"
            ).fetchone()
            if metadata is None or int(metadata[0]) <= STORE_SCHEMA_VERSION:
                self.connection.execute(
                    "INSERT INTO engineering_schema_meta VALUES(1,?,?) "
                    "ON CONFLICT(singleton) DO UPDATE SET schema_version=excluded.schema_version,"
                    "updated_unix_ns=excluded.updated_unix_ns",
                    (STORE_SCHEMA_VERSION, time.time_ns()),
                )
            self.connection.execute(f"PRAGMA user_version={STORE_SCHEMA_VERSION}")

    def _claim_capacity_units(self, claim) -> int:
        plan_row = self.connection.execute(
            "SELECT semantic_digest,plan_json FROM orchestration_generations "
            "WHERE generation_id=?",
            (claim["generation_id"],),
        ).fetchone()
        if plan_row is None:
            _error("worker_capacity_plan_missing")
        try:
            raw = plan_row["plan_json"]
            plan = json.loads(raw if isinstance(raw, str) else bytes(raw).decode("utf-8"))
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
            _error("worker_capacity_plan_invalid")
        if not isinstance(plan, dict) or semantic_digest(plan) != str(plan_row["semantic_digest"]):
            _error("worker_capacity_plan_invalid")
        packages = plan.get("packages")
        assignments = plan.get("assignments")
        if not isinstance(packages, list) or not isinstance(assignments, list):
            _error("worker_capacity_plan_invalid")
        package = next(
            (
                row for row in packages
                if isinstance(row, dict) and row.get("package_id") == claim["package_id"]
            ),
            None,
        )
        assignment = next(
            (
                row for row in assignments
                if isinstance(row, dict) and row.get("package_id") == claim["package_id"]
            ),
            None,
        )
        if (
            package is None
            or assignment is None
            or assignment.get("worker_id") != claim["worker_id"]
            or type(package.get("capacity_units")) is not int
            or not 1 <= int(package["capacity_units"]) <= 1_000_000
        ):
            _error("worker_capacity_plan_invalid")
        return int(package["capacity_units"])

    def _backfill_capacity_reservations(self, source_version: int) -> None:
        if source_version >= STORE_SCHEMA_VERSION:
            return
        rows = self.connection.execute(
            "SELECT * FROM worker_claims WHERE state IN ('claimed','running') "
            "ORDER BY claim_fence"
        ).fetchall()
        for claim in rows:
            existing = self.connection.execute(
                "SELECT 1 FROM worker_capacity_reservations WHERE claim_id=?",
                (claim["claim_id"],),
            ).fetchone()
            if existing is not None:
                continue
            units = self._claim_capacity_units(claim)
            reserved = int(claim["claimed_unix_ns"])
            digest = semantic_digest(
                {
                    "claimId": str(claim["claim_id"]),
                    "workerId": str(claim["worker_id"]),
                    "capacityUnits": units,
                    "reservedUnixNs": reserved,
                }
            )
            self.connection.execute(
                "INSERT INTO worker_capacity_reservations VALUES(?,?,?,?,?,?,?,?)",
                (
                    claim["claim_id"],
                    claim["worker_id"],
                    units,
                    "active",
                    reserved,
                    None,
                    None,
                    digest,
                ),
            )

    def _verify_capacity_reservations(self) -> None:
        reservations = self.connection.execute(
            "SELECT r.*,c.state AS claim_state,c.worker_id AS claim_worker,"
            "c.generation_id,c.package_id,c.claimed_unix_ns "
            "FROM worker_capacity_reservations r "
            "JOIN worker_claims c ON c.claim_id=r.claim_id ORDER BY c.claim_fence"
        ).fetchall()
        for row in reservations:
            if str(row["worker_id"]) != str(row["claim_worker"]):
                _error("worker_capacity_reservation_mismatch")
            units = self._claim_capacity_units(row)
            if units != int(row["capacity_units"]):
                _error("worker_capacity_reservation_mismatch")
            expected_digest = semantic_digest(
                {
                    "claimId": str(row["claim_id"]),
                    "workerId": str(row["worker_id"]),
                    "capacityUnits": units,
                    "reservedUnixNs": int(row["reserved_unix_ns"]),
                }
            )
            if expected_digest != str(row["semantic_digest"]):
                _error("worker_capacity_reservation_mismatch")
            holding = str(row["claim_state"]) in _CAPACITY_HOLDING_STATES
            if holding != (str(row["state"]) == "active"):
                _error("worker_capacity_reservation_state_mismatch")
        missing = self.connection.execute(
            "SELECT 1 FROM worker_claims c LEFT JOIN worker_capacity_reservations r "
            "ON r.claim_id=c.claim_id WHERE c.state IN ('claimed','running') "
            "AND (r.claim_id IS NULL OR r.state!='active') LIMIT 1"
        ).fetchone()
        if missing is not None:
            _error("worker_capacity_reservation_missing")
        totals = self.connection.execute(
            "SELECT r.worker_id,SUM(r.capacity_units) AS used,w.capacity_units AS available "
            "FROM worker_capacity_reservations r JOIN worker_registrations w "
            "ON w.worker_id=r.worker_id WHERE r.state='active' GROUP BY r.worker_id"
        ).fetchall()
        if any(int(row["used"]) > int(row["available"]) for row in totals):
            _error("worker_capacity_state_oversubscribed")

    def assignment_frontier(self, generation_id: str):
        from .hardening import assignment_frontier

        return assignment_frontier(self, generation_id)

    def integration_decision_binding(self, decision_id: str):
        from .closure import integration_decision_binding

        return integration_decision_binding(self, decision_id)

    def integration_decision_seal(self, decision_id: str):
        from .seal import integration_decision_seal

        return integration_decision_seal(self, decision_id)

    def _now(self, now_ns: int | None) -> int:
        value = time.time_ns() if now_ns is None else now_ns
        if type(value) is not int or value < 0:
            _error("invalid_time")
        return value

    def _append_audit(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        created: int,
    ) -> None:
        previous = self.connection.execute(
            "SELECT event_digest FROM audit_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_digest = ZERO_DIGEST if previous is None else str(previous[0])
        body = {
            "previousDigest": previous_digest,
            "eventType": event_type,
            "payload": dict(payload),
            "createdUnixNs": created,
        }
        digest = semantic_digest(body)
        event_id = digest[:32]
        self.connection.execute(
            "INSERT INTO audit_events("
            "event_id,previous_digest,event_digest,event_type,payload_json,created_unix_ns"
            ") VALUES(?,?,?,?,?,?)",
            (
                event_id,
                previous_digest,
                digest,
                event_type,
                canonical_json(dict(payload)),
                created,
            ),
        )

    def _expire_leases(self, now: int) -> None:
        rows = self.connection.execute(
            "SELECT lease_id,revision,authority_epoch FROM path_leases "
            "WHERE state='active' AND expires_unix_ns<=? ORDER BY fencing_token",
            (now,),
        ).fetchall()
        for row in rows:
            new_revision = int(row["revision"]) + 1
            self.connection.execute(
                "UPDATE path_leases SET state='expired',revision=? "
                "WHERE lease_id=? AND state='active'",
                (new_revision, row["lease_id"]),
            )
            self._append_audit(
                "path_lease_expired",
                {
                    "leaseId": row["lease_id"],
                    "revision": new_revision,
                    "epoch": int(row["authority_epoch"]),
                },
                now,
            )

    def _get_envelope(self, envelope_id: str, now: int) -> sqlite3.Row:
        checked_id(envelope_id, "envelope_id")
        row = self.connection.execute(
            "SELECT * FROM work_envelopes WHERE envelope_id=?",
            (envelope_id,),
        ).fetchone()
        if row is None:
            _error("unknown_envelope")
        if int(row["expires_unix_ns"]) <= now:
            _error("expired_envelope")
        return row

    def issue_work_envelope(
        self,
        envelope: WorkEnvelope,
        *,
        now_ns: int | None = None,
    ) -> WorkEnvelope:
        value = _validate_envelope(envelope)
        now = self._now(now_ns)
        if value.expires_unix_ns <= now:
            _error("expired_envelope")
        digest = semantic_digest(asdict(value))
        with self._transaction():
            existing = self.connection.execute(
                "SELECT semantic_digest FROM work_envelopes WHERE envelope_id=?",
                (value.envelope_id,),
            ).fetchone()
            if existing is not None:
                if existing[0] != digest:
                    _error("envelope_identity_conflict")
                return value
            self.connection.execute(
                "INSERT INTO work_envelopes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    value.envelope_id,
                    digest,
                    value.source_commit,
                    value.source_tree,
                    value.objective_digest,
                    value.contract_digest,
                    value.owner,
                    canonical_json(value.allowed_paths),
                    canonical_json(value.denied_authorities),
                    value.maximum_assignments,
                    value.expires_unix_ns,
                    value.revision,
                    now,
                ),
            )
            self._append_audit(
                "work_envelope_issued",
                {
                    "envelopeId": value.envelope_id,
                    "semanticDigest": digest,
                },
                now,
            )
        return value

    def _lease_receipt(self, row: sqlite3.Row) -> LeaseReceipt:
        return LeaseReceipt(
            str(row["lease_id"]),
            str(row["envelope_id"]),
            str(row["holder"]),
            tuple(json.loads(bytes(row["paths_json"]).decode("utf-8"))),
            str(row["state"]),
            int(row["authority_epoch"]),
            int(row["fencing_token"]),
            int(row["revision"]),
            int(row["issued_unix_ns"]),
            int(row["expires_unix_ns"]),
        )

    def _active_lease_rows(self, now_ns: int) -> list[sqlite3.Row]:
        rows = self.connection.execute(
            "SELECT * FROM path_leases WHERE state='active' AND expires_unix_ns>? "
            "ORDER BY fencing_token,lease_id LIMIT ?",
            (now_ns, MAX_ACTIVE_LEASES + 1),
        ).fetchall()
        if len(rows) > MAX_ACTIVE_LEASES:
            _error("active_lease_limit_exceeded")
        return rows

    def acquire_path_lease(
        self,
        lease_id: str,
        envelope_id: str,
        holder: str,
        paths: Iterable[str],
        *,
        authority_epoch: int,
        expires_unix_ns: int,
        now_ns: int | None = None,
    ) -> LeaseReceipt:
        checked_id(lease_id, "lease_id")
        checked_id(holder, "holder")
        now = self._now(now_ns)
        if type(authority_epoch) is not int or authority_epoch < 1:
            _error("invalid_authority_epoch")
        if type(expires_unix_ns) is not int or expires_unix_ns <= now:
            _error("invalid_lease_expiry")
        normalized = canonical_paths(paths)
        with self._transaction():
            envelope = self._get_envelope(envelope_id, now)
            allowed = tuple(
                json.loads(bytes(envelope["allowed_paths_json"]).decode("utf-8"))
            )
            if any(not path_is_within(path, allowed) for path in normalized):
                _error("lease_path_outside_envelope")
            self._expire_leases(now)
            semantic = semantic_digest(
                {
                    "leaseId": lease_id,
                    "envelopeId": envelope_id,
                    "holder": holder,
                    "paths": normalized,
                    "authorityEpoch": authority_epoch,
                    "expiresUnixNs": expires_unix_ns,
                }
            )
            existing = self.connection.execute(
                "SELECT * FROM path_leases WHERE lease_id=?",
                (lease_id,),
            ).fetchone()
            if existing is not None:
                if existing["semantic_digest"] != semantic:
                    _error("lease_identity_conflict")
                return self._lease_receipt(existing)
            active = self._active_lease_rows(now)
            if len(active) >= MAX_ACTIVE_LEASES:
                _error("active_lease_limit_exceeded")
            for row in active:
                current = tuple(json.loads(bytes(row["paths_json"]).decode("utf-8")))
                if path_sets_overlap(normalized, current):
                    _error("active_path_conflict")
            token = int(
                self.connection.execute(
                    "SELECT COALESCE(MAX(fencing_token),0)+1 FROM path_leases"
                ).fetchone()[0]
            )
            self.connection.execute(
                "INSERT INTO path_leases VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    lease_id,
                    envelope_id,
                    holder,
                    canonical_json(normalized),
                    "active",
                    authority_epoch,
                    token,
                    1,
                    now,
                    expires_unix_ns,
                    semantic,
                ),
            )
            self._append_audit(
                "path_lease_acquired",
                {
                    "leaseId": lease_id,
                    "envelopeId": envelope_id,
                    "fencingToken": token,
                    "revision": 1,
                },
                now,
            )
            row = self.connection.execute(
                "SELECT * FROM path_leases WHERE lease_id=?",
                (lease_id,),
            ).fetchone()
        return self._lease_receipt(row)

    def transition_path_lease(
        self,
        lease_id: str,
        *,
        expected_revision: int,
        authority_epoch: int,
        disposition: str,
        new_expiry_unix_ns: int | None = None,
        now_ns: int | None = None,
    ) -> LeaseReceipt:
        checked_id(lease_id, "lease_id")
        now = self._now(now_ns)
        if disposition not in {"renew", "release", "revoke"}:
            _error("invalid_lease_transition")
        with self._transaction():
            self._expire_leases(now)
            row = self.connection.execute(
                "SELECT * FROM path_leases WHERE lease_id=?",
                (lease_id,),
            ).fetchone()
            if row is None:
                _error("unknown_lease")
            if int(row["revision"]) != expected_revision:
                _error("stale_lease_revision")
            if int(row["authority_epoch"]) != authority_epoch:
                _error("stale_authority_epoch")
            if row["state"] != "active":
                _error("lease_not_active")
            revision = expected_revision + 1
            expiry = int(row["expires_unix_ns"])
            state = "active"
            if disposition == "renew":
                if type(new_expiry_unix_ns) is not int or new_expiry_unix_ns <= max(
                    now, expiry
                ):
                    _error("invalid_lease_expiry")
                expiry = new_expiry_unix_ns
            elif disposition == "release":
                state = "released"
            else:
                state = "revoked"
            cursor = self.connection.execute(
                "UPDATE path_leases SET state=?,revision=?,expires_unix_ns=? "
                "WHERE lease_id=? AND revision=? AND state='active'",
                (state, revision, expiry, lease_id, expected_revision),
            )
            if cursor.rowcount != 1:
                _error("stale_lease_revision")
            self._append_audit(
                "path_lease_" + disposition,
                {
                    "leaseId": lease_id,
                    "revision": revision,
                    "state": state,
                    "expiresUnixNs": expiry,
                },
                now,
            )
            updated = self.connection.execute(
                "SELECT * FROM path_leases WHERE lease_id=?",
                (lease_id,),
            ).fetchone()
        return self._lease_receipt(updated)

    def _verify_package_graph(
        self,
        packages: tuple[WorkPackage, ...],
        completed: frozenset[str],
    ) -> None:
        package_ids = {package.package_id for package in packages}
        for package in packages:
            for predecessor in package.predecessors:
                if predecessor not in package_ids and predecessor not in completed:
                    _error("unknown_predecessor")
        # A valid graph may be deeper than Python's call-stack limit. Kahn's
        # traversal bounds work by the admitted package and predecessor counts.
        pending = {package.package_id: 0 for package in packages}
        successors: dict[str, list[str]] = {identity: [] for identity in package_ids}
        for package in packages:
            for predecessor in package.predecessors:
                if predecessor in package_ids:
                    pending[package.package_id] += 1
                    successors[predecessor].append(package.package_id)
        ready = [identity for identity, count in pending.items() if count == 0]
        visited = 0
        while ready:
            identity = ready.pop()
            visited += 1
            for successor in successors[identity]:
                pending[successor] -= 1
                if pending[successor] == 0:
                    ready.append(successor)
        if visited != len(packages):
            _error("dependency_cycle")

    def schedule_ready_packages(
        self,
        envelope_id: str,
        packages: Iterable[WorkPackage],
        completed: Iterable[str],
        *,
        generation_id: str,
        now_ns: int | None = None,
    ) -> ScheduleReceipt:
        checked_id(generation_id, "generation_id")
        now = self._now(now_ns)
        raw_packages = bounded_tuple(
            packages,
            MAX_PACKAGES,
            "package_limit_exceeded",
        )
        package_values = tuple(_validate_package(value) for value in raw_packages)
        ids = [value.package_id for value in package_values]
        if len(ids) != len(set(ids)):
            _error("duplicate_package_identity")
        completed_raw = bounded_tuple(
            completed,
            MAX_COMPLETED,
            "completed_limit_exceeded",
        )
        completed_set = frozenset(
            checked_id(value, "completed_id") for value in completed_raw
        )
        self._verify_package_graph(package_values, completed_set)
        with self._transaction():
            envelope = self._get_envelope(envelope_id, now)
            allowed = tuple(
                json.loads(bytes(envelope["allowed_paths_json"]).decode("utf-8"))
            )
            if any(
                not path_is_within(path, allowed)
                for package in package_values
                for path in package.write_paths
            ):
                _error("package_path_outside_envelope")
            self._expire_leases(now)
            from .hardening import bind_assignment_frontier

            bind_assignment_frontier(self, envelope, generation_id, now)
            active_rows = self._active_lease_rows(now)
            active_paths = tuple(
                path
                for row in active_rows
                for path in json.loads(bytes(row["paths_json"]).decode("utf-8"))
            )
            assigned: list[str] = []
            blocked: list[tuple[str, str]] = []
            selected_paths: list[str] = []
            limit = min(int(envelope["maximum_assignments"]), MAX_ASSIGNMENTS)
            for package in sorted(package_values):
                missing = tuple(sorted(set(package.predecessors) - completed_set))
                if missing:
                    blocked.append(
                        (package.package_id, "missing_predecessor:" + missing[0])
                    )
                    continue
                if path_sets_overlap(package.write_paths, active_paths):
                    blocked.append((package.package_id, "active_path_lease"))
                    continue
                if path_sets_overlap(package.write_paths, tuple(selected_paths)):
                    blocked.append((package.package_id, "batch_path_conflict"))
                    continue
                if len(assigned) >= limit:
                    blocked.append((package.package_id, "assignment_limit"))
                    continue
                assigned.append(package.package_id)
                selected_paths.extend(package.write_paths)
            receipt = ScheduleReceipt(
                generation_id,
                envelope_id,
                tuple(assigned),
                tuple(blocked),
                now,
            )
            digest = semantic_digest(
                {
                    "envelopeId": envelope_id,
                    "packages": [asdict(value) for value in sorted(package_values)],
                    "completed": sorted(completed_set),
                    "assigned": receipt.assigned,
                    "blocked": receipt.blocked,
                }
            )
            existing = self.connection.execute(
                "SELECT * FROM assignment_generations WHERE generation_id=?",
                (generation_id,),
            ).fetchone()
            if existing is not None:
                if existing["semantic_digest"] != digest:
                    _error("generation_identity_conflict")
                return ScheduleReceipt(
                    generation_id,
                    str(existing["envelope_id"]),
                    tuple(json.loads(bytes(existing["assigned_json"]).decode("utf-8"))),
                    tuple(
                        tuple(item)
                        for item in json.loads(
                            bytes(existing["blocked_json"]).decode("utf-8")
                        )
                    ),
                    int(existing["created_unix_ns"]),
                )
            self.connection.execute(
                "INSERT INTO assignment_generations VALUES(?,?,?,?,?,?)",
                (
                    generation_id,
                    envelope_id,
                    digest,
                    canonical_json(receipt.assigned),
                    canonical_json(receipt.blocked),
                    now,
                ),
            )
            self._append_audit(
                "assignment_generation_published",
                {
                    "generationId": generation_id,
                    "envelopeId": envelope_id,
                    "semanticDigest": digest,
                },
                now,
            )
        return receipt

    def record_integration_decision(
        self,
        decision_id: str,
        evidence_digest: str,
        eligible: bool,
        reasons: Iterable[str],
        *,
        now_ns: int | None = None,
    ) -> None:
        checked_id(decision_id, "decision_id")
        checked_sha256(evidence_digest, "evidence_digest")
        if type(eligible) is not bool:
            _error("invalid_eligibility")
        reason_values = bounded_tuple(
            reasons,
            MAX_REASONS,
            "reason_limit_exceeded",
        )
        if any(not isinstance(value, str) or not value for value in reason_values):
            _error("invalid_reason")
        if eligible and reason_values:
            _error("eligible_decision_has_reasons")
        if eligible:
            sealed = self.connection.execute(
                "SELECT s.sealed_evidence_digest FROM integration_decision_seals s "
                "JOIN integration_decision_bindings b USING(decision_id) WHERE decision_id=?",
                (decision_id,),
            ).fetchone()
            if sealed is None or sealed[0] != evidence_digest:
                _error("sealed_evidence_required")

        now = self._now(now_ns)
        digest = semantic_digest(
            {
                "decisionId": decision_id,
                "evidenceDigest": evidence_digest,
                "eligible": eligible,
                "reasons": reason_values,
            }
        )
        with self._transaction():
            existing = self.connection.execute(
                "SELECT evidence_digest,eligible,reasons_json "
                "FROM integration_decisions WHERE decision_id=?",
                (decision_id,),
            ).fetchone()
            if existing is not None:
                existing_digest = semantic_digest(
                    {
                        "decisionId": decision_id,
                        "evidenceDigest": existing["evidence_digest"],
                        "eligible": bool(existing["eligible"]),
                        "reasons": tuple(
                            json.loads(bytes(existing["reasons_json"]).decode("utf-8"))
                        ),
                    }
                )
                if existing_digest != digest:
                    _error("decision_identity_conflict")
                return
            self.connection.execute(
                "INSERT INTO integration_decisions VALUES(?,?,?,?,?)",
                (
                    decision_id,
                    evidence_digest,
                    int(eligible),
                    canonical_json(reason_values),
                    now,
                ),
            )
            self._append_audit(
                "integration_decision_recorded",
                {
                    "decisionId": decision_id,
                    "evidenceDigest": evidence_digest,
                    "eligible": eligible,
                },
                now,
            )

    def audit_anchor(self) -> dict[str, object]:
        """Return the current append-only audit head for external immutable anchoring."""
        row = self.connection.execute(
            "SELECT sequence,event_id,event_digest,created_unix_ns "
            "FROM audit_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return {
                "sequence": 0,
                "eventId": "",
                "eventDigest": ZERO_DIGEST,
                "createdUnixNs": 0,
            }
        return {
            "sequence": int(row["sequence"]),
            "eventId": str(row["event_id"]),
            "eventDigest": str(row["event_digest"]),
            "createdUnixNs": int(row["created_unix_ns"]),
        }

    def audit_projection(
        self,
        *,
        after_sequence: int = 0,
        limit: int = MAX_AUDIT_ROWS,
    ) -> tuple[dict[str, object], ...]:
        if type(after_sequence) is not int or after_sequence < 0:
            _error("invalid_audit_query")
        if type(limit) is not int or not 1 <= limit <= MAX_AUDIT_ROWS:
            _error("invalid_audit_query")
        rows = self.connection.execute(
            "SELECT * FROM audit_events WHERE sequence>? ORDER BY sequence LIMIT ?",
            (after_sequence, limit),
        ).fetchall()
        return tuple(
            {
                "sequence": int(row["sequence"]),
                "eventId": str(row["event_id"]),
                "previousDigest": str(row["previous_digest"]),
                "eventDigest": str(row["event_digest"]),
                "eventType": str(row["event_type"]),
                "payload": json.loads(bytes(row["payload_json"]).decode("utf-8")),
                "createdUnixNs": int(row["created_unix_ns"]),
            }
            for row in rows
        )

    def verify_audit_chain(self) -> None:
        previous = ZERO_DIGEST
        rows = self.connection.execute(
            "SELECT * FROM audit_events ORDER BY sequence"
        ).fetchall()
        for row in rows:
            payload = json.loads(bytes(row["payload_json"]).decode("utf-8"))
            body = {
                "previousDigest": previous,
                "eventType": str(row["event_type"]),
                "payload": payload,
                "createdUnixNs": int(row["created_unix_ns"]),
            }
            digest = semantic_digest(body)
            if (
                row["previous_digest"] != previous
                or row["event_digest"] != digest
                or row["event_id"] != digest[:32]
            ):
                _error("audit_chain_broken")
            previous = digest
