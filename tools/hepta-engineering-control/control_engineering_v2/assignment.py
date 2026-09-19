"""Durable worker assignment lifecycle for Lane G engineering control.

Scheduling selects packages. This module binds an assigned package to one
authenticated worker and one active path lease, then fences execution through a
bounded claim lifecycle. Failure and expiry never cause an implicit retry:
a terminal claim must be explicitly requeued before a later attempt may be
claimed.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import TYPE_CHECKING

from . import control_plane as _control
from .evidence import SignatureVerifier

if TYPE_CHECKING:
    from .control_plane import EngineeringStore

MAX_WORKER_CAPABILITIES = 64
MAX_WORKER_CONCURRENCY = 32

_ACTIVE_CLAIM_STATES = ("claimed", "running")


@dataclass(frozen=True)
class WorkerReceipt:
    worker_id: str
    principal: str
    credential_chain_digest: str
    capabilities: tuple[str, ...]
    maximum_concurrency: int
    state: str
    authority_epoch: int
    revision: int
    registered_unix_ns: int
    last_heartbeat_unix_ns: int
    lease_expires_unix_ns: int
    identity_expires_unix_ns: int


@dataclass(frozen=True)
class WorkerIdentityReceipt:
    worker_id: str
    principal: str
    credential_chain_digest: str
    capabilities: tuple[str, ...]
    maximum_concurrency: int
    authority_epoch: int
    observed_unix_ns: int
    lease_expires_unix_ns: int
    expires_unix_ns: int
    issuer: str
    signing_identity: str
    signature: str = ""


@dataclass(frozen=True)
class AssignmentClaimReceipt:
    claim_id: str
    generation_id: str
    package_id: str
    worker_id: str
    lease_id: str
    state: str
    attempt: int
    authority_epoch: int
    fencing_token: int
    revision: int
    claimed_unix_ns: int
    started_unix_ns: int | None
    heartbeat_unix_ns: int
    expires_unix_ns: int
    completed_unix_ns: int | None
    result_digest: str | None
    failure_code: str | None
    retryable: bool
    runtime_authority: bool = False
    merge_authority: bool = False
    activation_authority: bool = False
    promotion_authority: bool = False
    release_authority: bool = False


def _decode_strings(value: object, code: str) -> tuple[str, ...]:
    if isinstance(value, str):
        text = value
    elif isinstance(value, (bytes, bytearray, memoryview)):
        try:
            text = bytes(value).decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise _control.EngineeringError(code) from None
    else:
        raise _control.EngineeringError(code)
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        raise _control.EngineeringError(code) from None
    if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
        raise _control.EngineeringError(code)
    return tuple(decoded)


def _worker_receipt(row) -> WorkerReceipt:
    return WorkerReceipt(
        str(row["worker_id"]),
        str(row["principal"]),
        str(row["credential_chain_digest"]),
        _decode_strings(row["capabilities_json"], "invalid_worker_capabilities"),
        int(row["maximum_concurrency"]),
        str(row["state"]),
        int(row["authority_epoch"]),
        int(row["revision"]),
        int(row["registered_unix_ns"]),
        int(row["last_heartbeat_unix_ns"]),
        int(row["lease_expires_unix_ns"]),
        int(row["identity_expires_unix_ns"]),
    )


def _claim_receipt(row) -> AssignmentClaimReceipt:
    return AssignmentClaimReceipt(
        str(row["claim_id"]),
        str(row["generation_id"]),
        str(row["package_id"]),
        str(row["worker_id"]),
        str(row["lease_id"]),
        str(row["state"]),
        int(row["attempt"]),
        int(row["authority_epoch"]),
        int(row["fencing_token"]),
        int(row["revision"]),
        int(row["claimed_unix_ns"]),
        None if row["started_unix_ns"] is None else int(row["started_unix_ns"]),
        int(row["heartbeat_unix_ns"]),
        int(row["expires_unix_ns"]),
        None if row["completed_unix_ns"] is None else int(row["completed_unix_ns"]),
        None if row["result_digest"] is None else str(row["result_digest"]),
        None if row["failure_code"] is None else str(row["failure_code"]),
        bool(row["retryable"]),
    )


def _canonical_capabilities(values) -> tuple[str, ...]:
    raw = _control.bounded_tuple(
        values, MAX_WORKER_CAPABILITIES, "worker_capability_limit_exceeded"
    )
    if any(not isinstance(value, str) for value in raw):
        raise _control.EngineeringError("invalid_worker_capability")
    return tuple(sorted({_control.checked_id(value, "worker_capability") for value in raw}))


def _expire_state(store: "EngineeringStore", now: int) -> None:
    worker_rows = store.connection.execute(
        "SELECT worker_id,revision FROM engineering_workers "
        "WHERE state IN ('active','draining') AND lease_expires_unix_ns<=? "
        "ORDER BY worker_id",
        (now,),
    ).fetchall()
    for row in worker_rows:
        revision = int(row["revision"]) + 1
        store.connection.execute(
            "UPDATE engineering_workers SET state='expired',revision=? "
            "WHERE worker_id=? AND state IN ('active','draining')",
            (revision, row["worker_id"]),
        )
        store._append_audit(
            "engineering_worker_expired",
            {"workerId": str(row["worker_id"]), "revision": revision},
            now,
        )

    claim_rows = store.connection.execute(
        "SELECT c.claim_id,c.revision FROM assignment_claims c "
        "JOIN engineering_workers w ON w.worker_id=c.worker_id "
        "JOIN path_leases l ON l.lease_id=c.lease_id "
        "WHERE c.state IN ('claimed','running') AND "
        "(c.expires_unix_ns<=? OR w.state IN ('revoked','expired') "
        "OR l.state!='active' OR l.expires_unix_ns<=?) "
        "ORDER BY c.fencing_token",
        (now, now),
    ).fetchall()
    for row in claim_rows:
        revision = int(row["revision"]) + 1
        store.connection.execute(
            "UPDATE assignment_claims SET state='expired',revision=?,"
            "completed_unix_ns=?,failure_code='claim_expired',retryable=1 "
            "WHERE claim_id=? AND state IN ('claimed','running')",
            (revision, now, row["claim_id"]),
        )
        store._append_audit(
            "assignment_claim_expired",
            {"claimId": str(row["claim_id"]), "revision": revision},
            now,
        )


def register_authenticated_worker(
    store: "EngineeringStore",
    identity: WorkerIdentityReceipt,
    verifier: SignatureVerifier,
    *,
    now_ns: int | None = None,
) -> WorkerReceipt:
    if not isinstance(identity, WorkerIdentityReceipt):
        raise _control.EngineeringError("worker_identity_receipt_required")
    now = store._now(now_ns)
    capabilities = _canonical_capabilities(identity.capabilities)
    if capabilities != identity.capabilities:
        raise _control.EngineeringError("worker_identity_noncanonical")
    _control.checked_id(identity.worker_id, "worker_id")
    _control.checked_id(identity.principal, "worker_principal")
    _control.checked_sha256(identity.credential_chain_digest, "credential_chain_digest")
    if identity.credential_chain_digest == "0" * 64:
        raise _control.EngineeringError("invalid_credential_chain_digest")
    if (
        type(identity.maximum_concurrency) is not int
        or not 1 <= identity.maximum_concurrency <= MAX_WORKER_CONCURRENCY
        or type(identity.authority_epoch) is not int
        or identity.authority_epoch < 1
    ):
        raise _control.EngineeringError("invalid_worker_identity_bounds")
    if (
        type(identity.observed_unix_ns) is not int
        or type(identity.expires_unix_ns) is not int
        or not identity.observed_unix_ns <= now < identity.expires_unix_ns
        or type(identity.lease_expires_unix_ns) is not int
        or not now < identity.lease_expires_unix_ns <= identity.expires_unix_ns
    ):
        raise _control.EngineeringError("worker_identity_stale")
    if (
        identity.issuer != "engineering_worker_authority"
        or not isinstance(identity.signing_identity, str)
        or not identity.signing_identity
    ):
        raise _control.EngineeringError("worker_identity_issuer_role")
    if not verifier.verify(
        identity,
        identity.issuer,
        identity.signing_identity,
        identity.signature,
    ):
        raise _control.EngineeringError("worker_identity_signature")
    return register_worker(
        store,
        identity.worker_id,
        identity.principal,
        identity.credential_chain_digest,
        identity.capabilities,
        maximum_concurrency=identity.maximum_concurrency,
        authority_epoch=identity.authority_epoch,
        expires_unix_ns=identity.lease_expires_unix_ns,
        identity_expires_unix_ns=identity.expires_unix_ns,
        now_ns=now,
    )


def completed_packages(
    store: "EngineeringStore",
    envelope_id: str,
    *,
    now_ns: int | None = None,
) -> tuple[str, ...]:
    _control.checked_id(envelope_id, "envelope_id")
    now = store._now(now_ns)
    with store._transaction():
        store._get_envelope(envelope_id, now)
        store._expire_leases(now)
        _expire_state(store, now)
        rows = store.connection.execute(
            "SELECT DISTINCT c.package_id FROM assignment_claims c "
            "JOIN assignment_generations g ON g.generation_id=c.generation_id "
            "WHERE g.envelope_id=? AND c.state='completed' ORDER BY c.package_id",
            (envelope_id,),
        ).fetchall()
    return tuple(str(row["package_id"]) for row in rows)


def register_worker(
    store: "EngineeringStore",
    worker_id: str,
    principal: str,
    credential_chain_digest: str,
    capabilities,
    *,
    maximum_concurrency: int,
    authority_epoch: int,
    expires_unix_ns: int,
    identity_expires_unix_ns: int | None = None,
    now_ns: int | None = None,
) -> WorkerReceipt:
    _control.checked_id(worker_id, "worker_id")
    _control.checked_id(principal, "worker_principal")
    _control.checked_sha256(credential_chain_digest, "credential_chain_digest")
    if credential_chain_digest == "0" * 64:
        raise _control.EngineeringError("invalid_credential_chain_digest")
    normalized_capabilities = _canonical_capabilities(capabilities)
    if type(maximum_concurrency) is not int or not 1 <= maximum_concurrency <= MAX_WORKER_CONCURRENCY:
        raise _control.EngineeringError("invalid_worker_concurrency")
    if type(authority_epoch) is not int or authority_epoch < 1:
        raise _control.EngineeringError("invalid_authority_epoch")
    now = store._now(now_ns)
    if type(expires_unix_ns) is not int or expires_unix_ns <= now:
        raise _control.EngineeringError("invalid_worker_expiry")
    identity_expiry = (
        expires_unix_ns
        if identity_expires_unix_ns is None
        else identity_expires_unix_ns
    )
    if (
        type(identity_expiry) is not int
        or identity_expiry < expires_unix_ns
    ):
        raise _control.EngineeringError("invalid_worker_identity_expiry")
    semantic = _control.semantic_digest(
        {
            "workerId": worker_id,
            "principal": principal,
            "credentialChainDigest": credential_chain_digest,
            "capabilities": normalized_capabilities,
            "maximumConcurrency": maximum_concurrency,
            "authorityEpoch": authority_epoch,
            "leaseExpiresUnixNs": expires_unix_ns,
            "identityExpiresUnixNs": identity_expiry,
        }
    )
    with store._transaction():
        _expire_state(store, now)
        existing = store.connection.execute(
            "SELECT * FROM engineering_workers WHERE worker_id=?", (worker_id,)
        ).fetchone()
        if existing is not None:
            if str(existing["semantic_digest"]) != semantic:
                raise _control.EngineeringError("worker_identity_conflict")
            return _worker_receipt(existing)
        store.connection.execute(
            "INSERT INTO engineering_workers("
            "worker_id,principal,credential_chain_digest,capabilities_json,"
            "maximum_concurrency,state,authority_epoch,revision,registered_unix_ns,"
            "last_heartbeat_unix_ns,lease_expires_unix_ns,identity_expires_unix_ns,"
            "semantic_digest"
            ") VALUES(?,?,?,?,?,'active',?,1,?,?,?,?,?)",
            (
                worker_id,
                principal,
                credential_chain_digest,
                _control.canonical_json(normalized_capabilities),
                maximum_concurrency,
                authority_epoch,
                now,
                now,
                expires_unix_ns,
                identity_expiry,
                semantic,
            ),
        )
        store._append_audit(
            "engineering_worker_registered",
            {
                "workerId": worker_id,
                "principal": principal,
                "credentialChainDigest": credential_chain_digest,
                "authorityEpoch": authority_epoch,
            },
            now,
        )
        row = store.connection.execute(
            "SELECT * FROM engineering_workers WHERE worker_id=?", (worker_id,)
        ).fetchone()
    return _worker_receipt(row)


def heartbeat_worker(
    store: "EngineeringStore",
    worker_id: str,
    *,
    expected_revision: int,
    authority_epoch: int,
    new_expiry_unix_ns: int,
    now_ns: int | None = None,
) -> WorkerReceipt:
    _control.checked_id(worker_id, "worker_id")
    now = store._now(now_ns)
    with store._transaction():
        _expire_state(store, now)
        row = store.connection.execute(
            "SELECT * FROM engineering_workers WHERE worker_id=?", (worker_id,)
        ).fetchone()
        if row is None:
            raise _control.EngineeringError("unknown_worker")
        if int(row["revision"]) != expected_revision:
            raise _control.EngineeringError("stale_worker_revision")
        if int(row["authority_epoch"]) != authority_epoch:
            raise _control.EngineeringError("stale_authority_epoch")
        if row["state"] not in {"active", "draining"}:
            raise _control.EngineeringError("worker_not_active")
        if (
            type(new_expiry_unix_ns) is not int
            or new_expiry_unix_ns <= max(now, int(row["lease_expires_unix_ns"]))
            or new_expiry_unix_ns > int(row["identity_expires_unix_ns"])
        ):
            raise _control.EngineeringError("invalid_worker_expiry")
        revision = expected_revision + 1
        store.connection.execute(
            "UPDATE engineering_workers SET revision=?,last_heartbeat_unix_ns=?,"
            "lease_expires_unix_ns=? WHERE worker_id=? AND revision=?",
            (revision, now, new_expiry_unix_ns, worker_id, expected_revision),
        )
        store._append_audit(
            "engineering_worker_heartbeat",
            {"workerId": worker_id, "revision": revision, "expiresUnixNs": new_expiry_unix_ns},
            now,
        )
        updated = store.connection.execute(
            "SELECT * FROM engineering_workers WHERE worker_id=?", (worker_id,)
        ).fetchone()
    return _worker_receipt(updated)


def revoke_worker(
    store: "EngineeringStore",
    worker_id: str,
    *,
    expected_revision: int,
    authority_epoch: int,
    now_ns: int | None = None,
) -> WorkerReceipt:
    _control.checked_id(worker_id, "worker_id")
    now = store._now(now_ns)
    with store._transaction():
        row = store.connection.execute(
            "SELECT * FROM engineering_workers WHERE worker_id=?", (worker_id,)
        ).fetchone()
        if row is None:
            raise _control.EngineeringError("unknown_worker")
        if int(row["revision"]) != expected_revision:
            raise _control.EngineeringError("stale_worker_revision")
        if int(row["authority_epoch"]) != authority_epoch:
            raise _control.EngineeringError("stale_authority_epoch")
        if row["state"] in {"revoked", "expired"}:
            raise _control.EngineeringError("worker_not_active")
        revision = expected_revision + 1
        store.connection.execute(
            "UPDATE engineering_workers SET state='revoked',revision=? "
            "WHERE worker_id=? AND revision=?",
            (revision, worker_id, expected_revision),
        )
        store._append_audit(
            "engineering_worker_revoked",
            {"workerId": worker_id, "revision": revision},
            now,
        )
        _expire_state(store, now)
        updated = store.connection.execute(
            "SELECT * FROM engineering_workers WHERE worker_id=?", (worker_id,)
        ).fetchone()
    return _worker_receipt(updated)


def claim_assignment(
    store: "EngineeringStore",
    claim_id: str,
    generation_id: str,
    package_id: str,
    worker_id: str,
    lease_id: str,
    *,
    authority_epoch: int,
    expires_unix_ns: int,
    now_ns: int | None = None,
) -> AssignmentClaimReceipt:
    for value, label in (
        (claim_id, "claim_id"),
        (generation_id, "generation_id"),
        (package_id, "package_id"),
        (worker_id, "worker_id"),
        (lease_id, "lease_id"),
    ):
        _control.checked_id(value, label)
    if type(authority_epoch) is not int or authority_epoch < 1:
        raise _control.EngineeringError("invalid_authority_epoch")
    now = store._now(now_ns)
    if type(expires_unix_ns) is not int or expires_unix_ns <= now:
        raise _control.EngineeringError("invalid_claim_expiry")

    with store._transaction():
        store._expire_leases(now)
        _expire_state(store, now)
        generation = store.connection.execute(
            "SELECT * FROM assignment_generations WHERE generation_id=?",
            (generation_id,),
        ).fetchone()
        if generation is None:
            raise _control.EngineeringError("unknown_assignment_generation")
        store._get_envelope(str(generation["envelope_id"]), now)
        assigned = _decode_strings(generation["assigned_json"], "invalid_assignment_generation")
        if package_id not in assigned:
            raise _control.EngineeringError("package_not_assigned")
        package = store.connection.execute(
            "SELECT * FROM assignment_generation_packages "
            "WHERE generation_id=? AND package_id=?",
            (generation_id, package_id),
        ).fetchone()
        if package is None:
            raise _control.EngineeringError("unbound_assignment_packages")

        worker = store.connection.execute(
            "SELECT * FROM engineering_workers WHERE worker_id=?", (worker_id,)
        ).fetchone()
        if worker is None:
            raise _control.EngineeringError("unknown_worker")
        if worker["state"] != "active" or int(worker["lease_expires_unix_ns"]) <= now:
            raise _control.EngineeringError("worker_not_active")
        if int(worker["authority_epoch"]) != authority_epoch:
            raise _control.EngineeringError("stale_authority_epoch")
        required = set(
            _decode_strings(package["required_capabilities_json"], "invalid_required_capabilities")
        )
        capabilities = set(
            _decode_strings(worker["capabilities_json"], "invalid_worker_capabilities")
        )
        if not required.issubset(capabilities):
            raise _control.EngineeringError("worker_capability_mismatch")

        lease = store.connection.execute(
            "SELECT * FROM path_leases WHERE lease_id=?", (lease_id,)
        ).fetchone()
        if lease is None:
            raise _control.EngineeringError("unknown_lease")
        if lease["state"] != "active" or int(lease["expires_unix_ns"]) <= now:
            raise _control.EngineeringError("lease_not_active")
        if str(lease["holder"]) != worker_id:
            raise _control.EngineeringError("lease_holder_mismatch")
        if int(lease["authority_epoch"]) != authority_epoch:
            raise _control.EngineeringError("stale_authority_epoch")
        if str(lease["envelope_id"]) != str(generation["envelope_id"]):
            raise _control.EngineeringError("lease_envelope_mismatch")
        if expires_unix_ns > min(
            int(lease["expires_unix_ns"]), int(worker["lease_expires_unix_ns"])
        ):
            raise _control.EngineeringError("claim_outlives_worker_or_lease")
        lease_paths = _decode_strings(lease["paths_json"], "invalid_lease_paths_encoding")
        package_paths = _decode_strings(package["write_paths_json"], "invalid_package_paths")
        if any(not _control.path_is_within(path, lease_paths) for path in package_paths):
            raise _control.EngineeringError("lease_does_not_cover_package")

        existing = store.connection.execute(
            "SELECT * FROM assignment_claims WHERE claim_id=?", (claim_id,)
        ).fetchone()
        if existing is not None:
            replay_semantic = _control.semantic_digest(
                {
                    "claimId": claim_id,
                    "generationId": generation_id,
                    "packageId": package_id,
                    "workerId": worker_id,
                    "leaseId": lease_id,
                    "authorityEpoch": authority_epoch,
                    "attempt": int(existing["attempt"]),
                    "expiresUnixNs": expires_unix_ns,
                }
            )
            if str(existing["semantic_digest"]) != replay_semantic:
                raise _control.EngineeringError("claim_identity_conflict")
            return _claim_receipt(existing)

        active_count = int(
            store.connection.execute(
                "SELECT COUNT(*) FROM assignment_claims "
                "WHERE worker_id=? AND state IN ('claimed','running')",
                (worker_id,),
            ).fetchone()[0]
        )
        if active_count >= int(worker["maximum_concurrency"]):
            raise _control.EngineeringError("worker_capacity_exceeded")

        attempt_rows = store.connection.execute(
            "SELECT * FROM assignment_claims WHERE generation_id=? AND package_id=? "
            "ORDER BY attempt, fencing_token",
            (generation_id, package_id),
        ).fetchall()
        if any(row["state"] == "completed" for row in attempt_rows):
            raise _control.EngineeringError("assignment_already_completed")
        if any(row["state"] in _ACTIVE_CLAIM_STATES for row in attempt_rows):
            raise _control.EngineeringError("assignment_already_claimed")
        if attempt_rows and attempt_rows[-1]["state"] != "requeued":
            raise _control.EngineeringError("assignment_requeue_required")
        maximum_attempts = int(package["maximum_attempts"])
        attempt = len(attempt_rows) + 1
        if attempt > maximum_attempts:
            raise _control.EngineeringError("assignment_retry_exhausted")
        semantic = _control.semantic_digest(
            {
                "claimId": claim_id,
                "generationId": generation_id,
                "packageId": package_id,
                "workerId": worker_id,
                "leaseId": lease_id,
                "authorityEpoch": authority_epoch,
                "attempt": attempt,
                "expiresUnixNs": expires_unix_ns,
            }
        )
        fencing_token = int(
            store.connection.execute(
                "SELECT COALESCE(MAX(fencing_token),0)+1 FROM assignment_claims"
            ).fetchone()[0]
        )
        store.connection.execute(
            "INSERT INTO assignment_claims("
            "claim_id,generation_id,package_id,worker_id,lease_id,state,attempt,"
            "authority_epoch,fencing_token,revision,claimed_unix_ns,started_unix_ns,"
            "heartbeat_unix_ns,expires_unix_ns,completed_unix_ns,result_digest,"
            "failure_code,retryable,semantic_digest"
            ") VALUES(?,?,?,?,?,'claimed',?,?,?,1,?,NULL,?,?,NULL,NULL,NULL,0,?)",
            (
                claim_id,
                generation_id,
                package_id,
                worker_id,
                lease_id,
                attempt,
                authority_epoch,
                fencing_token,
                now,
                now,
                expires_unix_ns,
                semantic,
            ),
        )
        store._append_audit(
            "assignment_claimed",
            {
                "claimId": claim_id,
                "generationId": generation_id,
                "packageId": package_id,
                "workerId": worker_id,
                "leaseId": lease_id,
                "attempt": attempt,
                "fencingToken": fencing_token,
            },
            now,
        )
        row = store.connection.execute(
            "SELECT * FROM assignment_claims WHERE claim_id=?", (claim_id,)
        ).fetchone()
    return _claim_receipt(row)


def _transition_claim(
    store: "EngineeringStore",
    claim_id: str,
    *,
    expected_revision: int,
    authority_epoch: int,
    from_states: tuple[str, ...],
    to_state: str,
    now: int,
    result_digest: str | None = None,
    failure_code: str | None = None,
    retryable: bool = False,
) -> AssignmentClaimReceipt:
    row = store.connection.execute(
        "SELECT * FROM assignment_claims WHERE claim_id=?", (claim_id,)
    ).fetchone()
    if row is None:
        raise _control.EngineeringError("unknown_assignment_claim")
    if int(row["revision"]) != expected_revision:
        raise _control.EngineeringError("stale_claim_revision")
    if int(row["authority_epoch"]) != authority_epoch:
        raise _control.EngineeringError("stale_authority_epoch")
    if str(row["state"]) not in from_states:
        raise _control.EngineeringError("invalid_claim_transition")
    revision = expected_revision + 1
    started = row["started_unix_ns"]
    completed = row["completed_unix_ns"]
    if to_state == "running":
        started = now
    if to_state in {"completed", "failed", "expired"}:
        completed = now
    store.connection.execute(
        "UPDATE assignment_claims SET state=?,revision=?,started_unix_ns=?,"
        "heartbeat_unix_ns=?,completed_unix_ns=?,result_digest=?,failure_code=?,retryable=? "
        "WHERE claim_id=? AND revision=?",
        (
            to_state,
            revision,
            started,
            now,
            completed,
            result_digest,
            failure_code,
            int(retryable),
            claim_id,
            expected_revision,
        ),
    )
    store._append_audit(
        "assignment_" + to_state,
        {"claimId": claim_id, "revision": revision, "state": to_state},
        now,
    )
    updated = store.connection.execute(
        "SELECT * FROM assignment_claims WHERE claim_id=?", (claim_id,)
    ).fetchone()
    return _claim_receipt(updated)


def begin_assignment(
    store: "EngineeringStore",
    claim_id: str,
    *,
    expected_revision: int,
    authority_epoch: int,
    now_ns: int | None = None,
) -> AssignmentClaimReceipt:
    _control.checked_id(claim_id, "claim_id")
    now = store._now(now_ns)
    with store._transaction():
        store._expire_leases(now)
        _expire_state(store, now)
        return _transition_claim(
            store,
            claim_id,
            expected_revision=expected_revision,
            authority_epoch=authority_epoch,
            from_states=("claimed",),
            to_state="running",
            now=now,
        )


def heartbeat_assignment(
    store: "EngineeringStore",
    claim_id: str,
    *,
    expected_revision: int,
    authority_epoch: int,
    new_expiry_unix_ns: int,
    now_ns: int | None = None,
) -> AssignmentClaimReceipt:
    _control.checked_id(claim_id, "claim_id")
    now = store._now(now_ns)
    with store._transaction():
        store._expire_leases(now)
        _expire_state(store, now)
        row = store.connection.execute(
            "SELECT c.*,w.lease_expires_unix_ns AS worker_expiry,"
            "l.expires_unix_ns AS path_lease_expiry,l.state AS path_lease_state "
            "FROM assignment_claims c "
            "JOIN engineering_workers w ON w.worker_id=c.worker_id "
            "JOIN path_leases l ON l.lease_id=c.lease_id "
            "WHERE c.claim_id=?",
            (claim_id,),
        ).fetchone()
        if row is None:
            raise _control.EngineeringError("unknown_assignment_claim")
        if int(row["revision"]) != expected_revision:
            raise _control.EngineeringError("stale_claim_revision")
        if int(row["authority_epoch"]) != authority_epoch:
            raise _control.EngineeringError("stale_authority_epoch")
        if row["state"] not in _ACTIVE_CLAIM_STATES or row["path_lease_state"] != "active":
            raise _control.EngineeringError("invalid_claim_transition")
        if (
            type(new_expiry_unix_ns) is not int
            or new_expiry_unix_ns <= max(now, int(row["expires_unix_ns"]))
            or new_expiry_unix_ns
            > min(int(row["worker_expiry"]), int(row["path_lease_expiry"]))
        ):
            raise _control.EngineeringError("invalid_claim_expiry")
        revision = expected_revision + 1
        store.connection.execute(
            "UPDATE assignment_claims SET revision=?,heartbeat_unix_ns=?,expires_unix_ns=? "
            "WHERE claim_id=? AND revision=?",
            (revision, now, new_expiry_unix_ns, claim_id, expected_revision),
        )
        store._append_audit(
            "assignment_heartbeat",
            {"claimId": claim_id, "revision": revision, "expiresUnixNs": new_expiry_unix_ns},
            now,
        )
        updated = store.connection.execute(
            "SELECT * FROM assignment_claims WHERE claim_id=?", (claim_id,)
        ).fetchone()
    return _claim_receipt(updated)


def complete_assignment(
    store: "EngineeringStore",
    claim_id: str,
    result_digest: str,
    *,
    expected_revision: int,
    authority_epoch: int,
    now_ns: int | None = None,
) -> AssignmentClaimReceipt:
    _control.checked_id(claim_id, "claim_id")
    _control.checked_sha256(result_digest, "assignment_result_digest")
    if result_digest == "0" * 64:
        raise _control.EngineeringError("invalid_assignment_result_digest")
    now = store._now(now_ns)
    with store._transaction():
        store._expire_leases(now)
        _expire_state(store, now)
        return _transition_claim(
            store,
            claim_id,
            expected_revision=expected_revision,
            authority_epoch=authority_epoch,
            from_states=("running",),
            to_state="completed",
            now=now,
            result_digest=result_digest,
        )


def fail_assignment(
    store: "EngineeringStore",
    claim_id: str,
    failure_code: str,
    *,
    retryable: bool,
    expected_revision: int,
    authority_epoch: int,
    now_ns: int | None = None,
) -> AssignmentClaimReceipt:
    _control.checked_id(claim_id, "claim_id")
    _control.checked_id(failure_code, "assignment_failure_code")
    if type(retryable) is not bool:
        raise _control.EngineeringError("invalid_retryable")
    now = store._now(now_ns)
    with store._transaction():
        store._expire_leases(now)
        _expire_state(store, now)
        return _transition_claim(
            store,
            claim_id,
            expected_revision=expected_revision,
            authority_epoch=authority_epoch,
            from_states=_ACTIVE_CLAIM_STATES,
            to_state="failed",
            now=now,
            failure_code=failure_code,
            retryable=retryable,
        )


def requeue_assignment(
    store: "EngineeringStore",
    claim_id: str,
    *,
    expected_revision: int,
    authority_epoch: int,
    now_ns: int | None = None,
) -> AssignmentClaimReceipt:
    _control.checked_id(claim_id, "claim_id")
    now = store._now(now_ns)
    with store._transaction():
        store._expire_leases(now)
        _expire_state(store, now)
        row = store.connection.execute(
            "SELECT c.*,p.maximum_attempts FROM assignment_claims c "
            "JOIN assignment_generation_packages p "
            "ON p.generation_id=c.generation_id AND p.package_id=c.package_id "
            "WHERE c.claim_id=?",
            (claim_id,),
        ).fetchone()
        if row is None:
            raise _control.EngineeringError("unknown_assignment_claim")
        if int(row["revision"]) != expected_revision:
            raise _control.EngineeringError("stale_claim_revision")
        if int(row["authority_epoch"]) != authority_epoch:
            raise _control.EngineeringError("stale_authority_epoch")
        if row["state"] not in {"failed", "expired"} or not bool(row["retryable"]):
            raise _control.EngineeringError("assignment_not_retryable")
        if int(row["attempt"]) >= int(row["maximum_attempts"]):
            raise _control.EngineeringError("assignment_retry_exhausted")
        revision = expected_revision + 1
        store.connection.execute(
            "UPDATE assignment_claims SET state='requeued',revision=?,heartbeat_unix_ns=? "
            "WHERE claim_id=? AND revision=?",
            (revision, now, claim_id, expected_revision),
        )
        store._append_audit(
            "assignment_requeued",
            {"claimId": claim_id, "revision": revision, "attempt": int(row["attempt"])},
            now,
        )
        updated = store.connection.execute(
            "SELECT * FROM assignment_claims WHERE claim_id=?", (claim_id,)
        ).fetchone()
    return _claim_receipt(updated)


def assignment_status(
    store: "EngineeringStore",
    generation_id: str,
    *,
    package_id: str | None = None,
    now_ns: int | None = None,
) -> tuple[AssignmentClaimReceipt, ...]:
    _control.checked_id(generation_id, "generation_id")
    if package_id is not None:
        _control.checked_id(package_id, "package_id")
    now = store._now(now_ns)
    with store._transaction():
        store._expire_leases(now)
        _expire_state(store, now)
        if package_id is None:
            rows = store.connection.execute(
                "SELECT * FROM assignment_claims WHERE generation_id=? "
                "ORDER BY package_id,attempt,fencing_token",
                (generation_id,),
            ).fetchall()
        else:
            rows = store.connection.execute(
                "SELECT * FROM assignment_claims WHERE generation_id=? AND package_id=? "
                "ORDER BY attempt,fencing_token",
                (generation_id, package_id),
            ).fetchall()
    return tuple(_claim_receipt(row) for row in rows)
