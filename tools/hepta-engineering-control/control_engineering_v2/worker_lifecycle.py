"""Durable worker assignment lifecycle for the Engineering Control Plane.

Assignments are proposals until an authenticated worker is registered, a matching
fenced path lease exists, and a durable claim is committed. Worker-reported success
is never predecessor completion; only a separately signed CI completion receipt can
advance a claim to completed_observed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import time

from .control_plane import (
    EngineeringError,
    EngineeringStore,
    WorkEnvelope,
    canonical_json,
    canonical_paths,
    checked_id,
    checked_sha256,
    path_is_within,
    semantic_digest,
)
from .evidence import SignatureTrustStore
from .orchestration import CompletionReceipt, _verify_completion

MAX_CLAIM_ATTEMPTS = 3
MAX_HEARTBEAT_TTL_NS = 300 * 1_000_000_000
WORKER_IDENTITY_ISSUER = "engineering_worker_identity"


@dataclass(frozen=True)
class WorkerRegistrationReceipt:
    worker_id: str
    worker_signing_identity: str
    skills: tuple[str, ...]
    capacity_units: int
    allowed_paths: tuple[str, ...]
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class WorkerHeartbeatReceipt:
    worker_id: str
    worker_signing_identity: str
    claim_id: str
    claim_fence: int
    expected_revision: int
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class WorkerResultReceipt:
    worker_id: str
    worker_signing_identity: str
    claim_id: str
    claim_fence: int
    expected_revision: int
    result_digest: str
    outcome: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class WorkerClaim:
    claim_id: str
    generation_id: str
    package_id: str
    worker_id: str
    lease_id: str
    attempt: int
    state: str
    claim_fence: int
    revision: int
    claimed_unix_ns: int
    last_heartbeat_unix_ns: int
    heartbeat_deadline_unix_ns: int
    result_digest: str | None
    failure_class: str | None


def _now(value: int | None) -> int:
    result = time.time_ns() if value is None else value
    if type(result) is not int or result < 0:
        raise EngineeringError("invalid_time")
    return result


def _decode_json(value: object, code: str):
    try:
        raw = value if isinstance(value, str) else bytes(value).decode("utf-8")
        return json.loads(raw)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise EngineeringError(code) from None


def _claim(row) -> WorkerClaim:
    return WorkerClaim(
        str(row["claim_id"]),
        str(row["generation_id"]),
        str(row["package_id"]),
        str(row["worker_id"]),
        str(row["lease_id"]),
        int(row["attempt"]),
        str(row["state"]),
        int(row["claim_fence"]),
        int(row["revision"]),
        int(row["claimed_unix_ns"]),
        int(row["last_heartbeat_unix_ns"]),
        int(row["heartbeat_deadline_unix_ns"]),
        None if row["result_digest"] is None else str(row["result_digest"]),
        None if row["failure_class"] is None else str(row["failure_class"]),
    )


def register_worker(
    store: EngineeringStore,
    receipt: WorkerRegistrationReceipt,
    trust_store: SignatureTrustStore,
    *,
    now_ns: int | None = None,
) -> str:
    now = _now(now_ns)
    if not isinstance(receipt, WorkerRegistrationReceipt):
        raise EngineeringError("worker_registration_required")
    checked_id(receipt.worker_id, "worker_id")
    checked_id(receipt.worker_signing_identity, "worker_signing_identity")
    if receipt.issuer != WORKER_IDENTITY_ISSUER:
        raise EngineeringError("worker_registration_issuer_role")
    if (
        type(receipt.capacity_units) is not int
        or not 1 <= receipt.capacity_units <= 1_000_000
        or not isinstance(receipt.skills, tuple)
        or len(receipt.skills) > 64
        or len(set(receipt.skills)) != len(receipt.skills)
    ):
        raise EngineeringError("invalid_worker_profile")
    for skill in receipt.skills:
        checked_id(skill, "worker_skill")
    paths = canonical_paths(receipt.allowed_paths)
    if not (
        type(receipt.observed_unix_ns) is int
        and type(receipt.expires_unix_ns) is int
        and receipt.observed_unix_ns <= now < receipt.expires_unix_ns
    ):
        raise EngineeringError("worker_registration_stale")
    if not trust_store.verify(
        receipt, receipt.issuer, receipt.signing_identity, receipt.signature
    ):
        raise EngineeringError("worker_registration_signature")
    profile = {
        "workerId": receipt.worker_id,
        "workerSigningIdentity": receipt.worker_signing_identity,
        "skills": tuple(sorted(receipt.skills)),
        "capacityUnits": receipt.capacity_units,
        "allowedPaths": paths,
    }
    digest = semantic_digest(profile)
    with store._transaction():
        current = store.connection.execute(
            "SELECT * FROM worker_registrations WHERE worker_id=?",
            (receipt.worker_id,),
        ).fetchone()
        if current is not None:
            if (
                str(current["profile_digest"]) != digest
                or str(current["worker_signing_identity"])
                != receipt.worker_signing_identity
                or int(current["expires_unix_ns"]) != receipt.expires_unix_ns
                or str(current["state"]) != "active"
            ):
                raise EngineeringError("worker_registration_conflict")
            return digest
        store.connection.execute(
            "INSERT INTO worker_registrations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                receipt.worker_id,
                digest,
                receipt.worker_signing_identity,
                canonical_json(tuple(sorted(receipt.skills))),
                canonical_json(paths),
                receipt.capacity_units,
                receipt.issuer,
                receipt.signing_identity,
                receipt.observed_unix_ns,
                receipt.expires_unix_ns,
                "active",
                1,
                None,
                now,
            ),
        )
        store._append_audit(
            "worker_registered",
            {"workerId": receipt.worker_id, "profileDigest": digest},
            now,
        )
    return digest


def revoke_worker(
    store: EngineeringStore,
    worker_id: str,
    *,
    expected_revision: int,
    now_ns: int | None = None,
) -> None:
    now = _now(now_ns)
    checked_id(worker_id, "worker_id")
    with store._transaction():
        row = store.connection.execute(
            "SELECT state,revision FROM worker_registrations WHERE worker_id=?",
            (worker_id,),
        ).fetchone()
        if row is None:
            raise EngineeringError("unknown_worker")
        if int(row["revision"]) != expected_revision:
            raise EngineeringError("stale_worker_revision")
        if str(row["state"]) != "active":
            raise EngineeringError("worker_not_active")
        store.connection.execute(
            "UPDATE worker_registrations SET state='revoked',revision=?,"
            "recorded_unix_ns=? WHERE worker_id=? AND revision=?",
            (expected_revision + 1, now, worker_id, expected_revision),
        )
        store.connection.execute(
            "UPDATE worker_claims SET state='failed',revision=revision+1,"
            "failure_class='worker_revoked',updated_unix_ns=? "
            "WHERE worker_id=? AND state IN ('claimed','running','retryable')",
            (now, worker_id),
        )
        store._append_audit(
            "worker_revoked",
            {"workerId": worker_id, "revision": expected_revision + 1},
            now,
        )


def _load_plan(store: EngineeringStore, generation_id: str) -> dict[str, object]:
    checked_id(generation_id, "generation_id")
    row = store.connection.execute(
        "SELECT semantic_digest,plan_json FROM orchestration_generations "
        "WHERE generation_id=?",
        (generation_id,),
    ).fetchone()
    if row is None:
        raise EngineeringError("orchestration_generation_unknown")
    plan = _decode_json(row["plan_json"], "orchestration_generation_invalid")
    if not isinstance(plan, dict) or semantic_digest(plan) != str(row["semantic_digest"]):
        raise EngineeringError("orchestration_generation_invalid")
    return plan


def claim_assignment(
    store: EngineeringStore,
    generation_id: str,
    package_id: str,
    worker_id: str,
    lease_id: str,
    *,
    heartbeat_ttl_ns: int,
    now_ns: int | None = None,
) -> WorkerClaim:
    now = _now(now_ns)
    checked_id(package_id, "package_id")
    checked_id(worker_id, "worker_id")
    checked_id(lease_id, "lease_id")
    if (
        type(heartbeat_ttl_ns) is not int
        or not 1 <= heartbeat_ttl_ns <= MAX_HEARTBEAT_TTL_NS
    ):
        raise EngineeringError("invalid_heartbeat_ttl")
    with store._transaction():
        plan = _load_plan(store, generation_id)
        assignments = plan.get("assignments")
        packages = plan.get("packages")
        workers = plan.get("workers")
        if not all(isinstance(value, list) for value in (assignments, packages, workers)):
            raise EngineeringError("orchestration_generation_invalid")
        assignment = next(
            (
                row for row in assignments
                if isinstance(row, dict) and row.get("package_id") == package_id
            ),
            None,
        )
        if assignment is None:
            raise EngineeringError("package_not_assigned")
        if assignment.get("worker_id") != worker_id:
            raise EngineeringError("assignment_worker_mismatch")
        package = next(
            (
                row for row in packages
                if isinstance(row, dict) and row.get("package_id") == package_id
            ),
            None,
        )
        plan_worker = next(
            (
                row for row in workers
                if isinstance(row, dict) and row.get("worker_id") == worker_id
            ),
            None,
        )
        if package is None or plan_worker is None:
            raise EngineeringError("orchestration_generation_invalid")

        registration = store.connection.execute(
            "SELECT * FROM worker_registrations WHERE worker_id=?",
            (worker_id,),
        ).fetchone()
        if (
            registration is None
            or str(registration["state"]) != "active"
            or int(registration["expires_unix_ns"]) <= now
        ):
            raise EngineeringError("worker_not_active")
        expected_profile = {
            "workerId": worker_id,
            "workerSigningIdentity": str(registration["worker_signing_identity"]),
            "skills": tuple(plan_worker.get("skills", ())),
            "capacityUnits": plan_worker.get("capacity_units"),
            "allowedPaths": tuple(plan_worker.get("allowed_paths", ())),
        }
        if semantic_digest(expected_profile) != str(registration["profile_digest"]):
            raise EngineeringError("worker_profile_drift")

        generation = store.connection.execute(
            "SELECT envelope_id FROM assignment_generations WHERE generation_id=?",
            (generation_id,),
        ).fetchone()
        if generation is None:
            raise EngineeringError("assignment_generation_unknown")
        envelope = store._get_envelope(str(generation["envelope_id"]), now)
        lease = store.connection.execute(
            "SELECT * FROM path_leases WHERE lease_id=?",
            (lease_id,),
        ).fetchone()
        if (
            lease is None
            or str(lease["state"]) != "active"
            or int(lease["expires_unix_ns"]) <= now
            or str(lease["envelope_id"]) != str(envelope["envelope_id"])
            or str(lease["holder"]) != worker_id
        ):
            raise EngineeringError("claim_lease_invalid")
        lease_paths = tuple(_decode_json(lease["paths_json"], "claim_lease_invalid"))
        package_paths = tuple(package.get("write_paths", ()))
        if not package_paths or any(
            not path_is_within(path, lease_paths) for path in package_paths
        ):
            raise EngineeringError("claim_lease_scope_mismatch")

        previous = store.connection.execute(
            "SELECT * FROM worker_claims WHERE generation_id=? AND package_id=? "
            "ORDER BY attempt DESC LIMIT 1",
            (generation_id, package_id),
        ).fetchone()
        attempt = 1
        if previous is not None:
            if str(previous["state"]) != "retryable":
                raise EngineeringError("assignment_already_claimed")
            attempt = int(previous["attempt"]) + 1
        if attempt > MAX_CLAIM_ATTEMPTS:
            raise EngineeringError("claim_attempts_exhausted")
        fence = int(
            store.connection.execute(
                "SELECT COALESCE(MAX(claim_fence),0)+1 FROM worker_claims"
            ).fetchone()[0]
        )
        deadline = min(
            now + heartbeat_ttl_ns,
            int(lease["expires_unix_ns"]),
            int(registration["expires_unix_ns"]),
            int(envelope["expires_unix_ns"]),
        )
        if deadline <= now:
            raise EngineeringError("claim_window_exhausted")
        identity = {
            "generationId": generation_id,
            "packageId": package_id,
            "workerId": worker_id,
            "leaseId": lease_id,
            "attempt": attempt,
            "claimFence": fence,
        }
        digest = semantic_digest(identity)
        claim_id = digest[:32]
        store.connection.execute(
            "INSERT INTO worker_claims VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                claim_id,
                generation_id,
                package_id,
                worker_id,
                lease_id,
                attempt,
                "claimed",
                fence,
                1,
                now,
                now,
                deadline,
                None,
                None,
                digest,
                now,
            ),
        )
        store._append_audit(
            "worker_assignment_claimed",
            {
                "claimId": claim_id,
                "generationId": generation_id,
                "packageId": package_id,
                "workerId": worker_id,
                "attempt": attempt,
                "claimFence": fence,
            },
            now,
        )
        row = store.connection.execute(
            "SELECT * FROM worker_claims WHERE claim_id=?",
            (claim_id,),
        ).fetchone()
    return _claim(row)


def _active_worker_and_claim(store, claim_id: str, now: int):
    checked_id(claim_id, "claim_id")
    claim = store.connection.execute(
        "SELECT * FROM worker_claims WHERE claim_id=?",
        (claim_id,),
    ).fetchone()
    if claim is None:
        raise EngineeringError("unknown_worker_claim")
    registration = store.connection.execute(
        "SELECT * FROM worker_registrations WHERE worker_id=?",
        (claim["worker_id"],),
    ).fetchone()
    if (
        registration is None
        or str(registration["state"]) != "active"
        or int(registration["expires_unix_ns"]) <= now
    ):
        raise EngineeringError("worker_not_active")
    lease = store.connection.execute(
        "SELECT * FROM path_leases WHERE lease_id=?",
        (claim["lease_id"],),
    ).fetchone()
    if (
        lease is None
        or str(lease["state"]) != "active"
        or int(lease["expires_unix_ns"]) <= now
        or str(lease["holder"]) != str(claim["worker_id"])
    ):
        raise EngineeringError("claim_lease_invalid")
    return claim, registration, lease


def heartbeat_claim(
    store: EngineeringStore,
    receipt: WorkerHeartbeatReceipt,
    trust_store: SignatureTrustStore,
    *,
    heartbeat_ttl_ns: int,
    now_ns: int | None = None,
) -> WorkerClaim:
    now = _now(now_ns)
    if not isinstance(receipt, WorkerHeartbeatReceipt):
        raise EngineeringError("worker_heartbeat_required")
    if (
        type(heartbeat_ttl_ns) is not int
        or not 1 <= heartbeat_ttl_ns <= MAX_HEARTBEAT_TTL_NS
    ):
        raise EngineeringError("invalid_heartbeat_ttl")
    with store._transaction():
        claim, registration, lease = _active_worker_and_claim(store, receipt.claim_id, now)
        if str(claim["state"]) not in {"claimed", "running"}:
            raise EngineeringError("claim_not_running")
        if (
            receipt.worker_id != str(claim["worker_id"])
            or receipt.worker_signing_identity
            != str(registration["worker_signing_identity"])
            or receipt.claim_fence != int(claim["claim_fence"])
            or receipt.expected_revision != int(claim["revision"])
        ):
            raise EngineeringError("worker_heartbeat_binding")
        if not (
            type(receipt.observed_unix_ns) is int
            and type(receipt.expires_unix_ns) is int
            and int(claim["claimed_unix_ns"]) <= receipt.observed_unix_ns <= now
            and now < receipt.expires_unix_ns
        ):
            raise EngineeringError("worker_heartbeat_stale")
        if not trust_store.verify(
            receipt,
            receipt.worker_id,
            receipt.worker_signing_identity,
            receipt.signature,
        ):
            raise EngineeringError("worker_heartbeat_signature")
        generation = store.connection.execute(
            "SELECT envelope_id FROM assignment_generations WHERE generation_id=?",
            (claim["generation_id"],),
        ).fetchone()
        envelope = store._get_envelope(str(generation["envelope_id"]), now)
        deadline = min(
            receipt.observed_unix_ns + heartbeat_ttl_ns,
            receipt.expires_unix_ns,
            int(lease["expires_unix_ns"]),
            int(registration["expires_unix_ns"]),
            int(envelope["expires_unix_ns"]),
        )
        if deadline <= now:
            raise EngineeringError("claim_window_exhausted")
        revision = int(claim["revision"]) + 1
        store.connection.execute(
            "UPDATE worker_claims SET state='running',revision=?,"
            "last_heartbeat_unix_ns=?,heartbeat_deadline_unix_ns=?,updated_unix_ns=? "
            "WHERE claim_id=? AND revision=?",
            (
                revision,
                receipt.observed_unix_ns,
                deadline,
                now,
                receipt.claim_id,
                receipt.expected_revision,
            ),
        )
        store.connection.execute(
            "UPDATE worker_registrations SET last_heartbeat_unix_ns=? "
            "WHERE worker_id=?",
            (receipt.observed_unix_ns, receipt.worker_id),
        )
        store._append_audit(
            "worker_claim_heartbeat",
            {"claimId": receipt.claim_id, "revision": revision},
            now,
        )
        row = store.connection.execute(
            "SELECT * FROM worker_claims WHERE claim_id=?",
            (receipt.claim_id,),
        ).fetchone()
    return _claim(row)


def submit_worker_result(
    store: EngineeringStore,
    receipt: WorkerResultReceipt,
    trust_store: SignatureTrustStore,
    *,
    now_ns: int | None = None,
) -> WorkerClaim:
    now = _now(now_ns)
    if not isinstance(receipt, WorkerResultReceipt):
        raise EngineeringError("worker_result_required")
    checked_sha256(receipt.result_digest, "result_digest")
    if receipt.outcome not in {"success", "infra_failure", "semantic_failure"}:
        raise EngineeringError("invalid_worker_outcome")
    with store._transaction():
        claim, registration, _lease = _active_worker_and_claim(store, receipt.claim_id, now)
        if str(claim["state"]) != "running":
            raise EngineeringError("claim_not_running")
        if (
            receipt.worker_id != str(claim["worker_id"])
            or receipt.worker_signing_identity
            != str(registration["worker_signing_identity"])
            or receipt.claim_fence != int(claim["claim_fence"])
            or receipt.expected_revision != int(claim["revision"])
        ):
            raise EngineeringError("worker_result_binding")
        if not (
            type(receipt.observed_unix_ns) is int
            and type(receipt.expires_unix_ns) is int
            and int(claim["claimed_unix_ns"]) <= receipt.observed_unix_ns <= now
            and now < receipt.expires_unix_ns
        ):
            raise EngineeringError("worker_result_stale")
        if not trust_store.verify(
            receipt,
            receipt.worker_id,
            receipt.worker_signing_identity,
            receipt.signature,
        ):
            raise EngineeringError("worker_result_signature")
        if receipt.outcome == "success":
            state = "result_submitted"
            failure = None
        elif receipt.outcome == "infra_failure":
            state = (
                "retryable"
                if int(claim["attempt"]) < MAX_CLAIM_ATTEMPTS
                else "failed"
            )
            failure = "infrastructure"
        else:
            state = "failed"
            failure = "semantic"
        revision = int(claim["revision"]) + 1
        store.connection.execute(
            "UPDATE worker_claims SET state=?,revision=?,result_digest=?,"
            "failure_class=?,updated_unix_ns=? WHERE claim_id=? AND revision=?",
            (
                state,
                revision,
                receipt.result_digest,
                failure,
                now,
                receipt.claim_id,
                receipt.expected_revision,
            ),
        )
        store._append_audit(
            "worker_result_submitted",
            {
                "claimId": receipt.claim_id,
                "state": state,
                "outcome": receipt.outcome,
                "revision": revision,
            },
            now,
        )
        row = store.connection.execute(
            "SELECT * FROM worker_claims WHERE claim_id=?",
            (receipt.claim_id,),
        ).fetchone()
    return _claim(row)


def expire_stale_claims(
    store: EngineeringStore,
    *,
    now_ns: int | None = None,
) -> tuple[str, ...]:
    now = _now(now_ns)
    expired: list[str] = []
    with store._transaction():
        rows = store.connection.execute(
            "SELECT * FROM worker_claims WHERE state IN ('claimed','running') "
            "AND heartbeat_deadline_unix_ns<=? ORDER BY claim_fence",
            (now,),
        ).fetchall()
        for row in rows:
            state = (
                "retryable"
                if int(row["attempt"]) < MAX_CLAIM_ATTEMPTS
                else "failed"
            )
            revision = int(row["revision"]) + 1
            store.connection.execute(
                "UPDATE worker_claims SET state=?,revision=?,"
                "failure_class='heartbeat_timeout',updated_unix_ns=? "
                "WHERE claim_id=? AND revision=?",
                (state, revision, now, row["claim_id"], row["revision"]),
            )
            store._append_audit(
                "worker_claim_expired",
                {
                    "claimId": str(row["claim_id"]),
                    "state": state,
                    "revision": revision,
                },
                now,
            )
            expired.append(str(row["claim_id"]))
    return tuple(expired)


def observe_claim_completion(
    store: EngineeringStore,
    claim_id: str,
    envelope: WorkEnvelope,
    completion: CompletionReceipt,
    trust_store: SignatureTrustStore,
    *,
    now_ns: int | None = None,
) -> WorkerClaim:
    now = _now(now_ns)
    with store._transaction():
        claim = store.connection.execute(
            "SELECT * FROM worker_claims WHERE claim_id=?",
            (claim_id,),
        ).fetchone()
        if claim is None:
            raise EngineeringError("unknown_worker_claim")
        if str(claim["state"]) != "result_submitted":
            raise EngineeringError("worker_result_not_submitted")
        if (
            completion.generation_id != str(claim["generation_id"])
            or completion.package_id != str(claim["package_id"])
            or completion.result_digest != str(claim["result_digest"])
        ):
            raise EngineeringError("completion_claim_mismatch")
        _verify_completion(completion, envelope, store, trust_store, now)
        revision = int(claim["revision"]) + 1
        store.connection.execute(
            "UPDATE worker_claims SET state='completed_observed',revision=?,"
            "updated_unix_ns=? WHERE claim_id=? AND revision=?",
            (revision, now, claim_id, claim["revision"]),
        )
        store._append_audit(
            "worker_claim_completed_observed",
            {
                "claimId": claim_id,
                "completionDigest": semantic_digest(asdict(completion)),
                "revision": revision,
            },
            now,
        )
        row = store.connection.execute(
            "SELECT * FROM worker_claims WHERE claim_id=?",
            (claim_id,),
        ).fetchone()
    return _claim(row)


def worker_claim(
    store: EngineeringStore,
    claim_id: str,
) -> WorkerClaim:
    checked_id(claim_id, "claim_id")
    row = store.connection.execute(
        "SELECT * FROM worker_claims WHERE claim_id=?",
        (claim_id,),
    ).fetchone()
    if row is None:
        raise EngineeringError("unknown_worker_claim")
    return _claim(row)
