"""Revision-bound worker registration renewal and signing-key rotation.

Initial worker admission remains in :mod:`worker_lifecycle`.  This module owns the
subsequent governance transitions: a registration can be renewed or narrowed only
under an authenticated authority receipt, and a signing key can rotate only while
no active claim is using the predecessor identity.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json

from .clock import Clock, ClockPolicy, validate_observation_window
from .control_plane import (
    EngineeringError,
    EngineeringStore,
    canonical_json,
    canonical_paths,
    checked_id,
    checked_sha256,
    path_is_within,
    semantic_digest,
)
from .evidence import SignatureTrustStore
from .worker_lifecycle import WORKER_IDENTITY_ISSUER


@dataclass(frozen=True)
class WorkerRegistrationRenewalReceipt:
    worker_id: str
    worker_signing_identity: str
    expected_revision: int
    previous_profile_digest: str
    skills: tuple[str, ...]
    capacity_units: int
    allowed_paths: tuple[str, ...]
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class WorkerKeyRotationReceipt:
    worker_id: str
    expected_revision: int
    previous_profile_digest: str
    previous_worker_signing_identity: str
    new_worker_signing_identity: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class WorkerRegistrationState:
    worker_id: str
    profile_digest: str
    worker_signing_identity: str
    skills: tuple[str, ...]
    capacity_units: int
    allowed_paths: tuple[str, ...]
    expires_unix_ns: int
    state: str
    revision: int


def _decode_tuple(value: object, code: str) -> tuple[str, ...]:
    try:
        raw = value if isinstance(value, str) else bytes(value).decode("utf-8")
        decoded = json.loads(raw)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise EngineeringError(code) from None
    if not isinstance(decoded, list) or any(not isinstance(item, str) for item in decoded):
        raise EngineeringError(code)
    return tuple(decoded)


def _state(row) -> WorkerRegistrationState:
    return WorkerRegistrationState(
        worker_id=str(row["worker_id"]),
        profile_digest=str(row["profile_digest"]),
        worker_signing_identity=str(row["worker_signing_identity"]),
        skills=_decode_tuple(row["skills_json"], "worker_registration_skills_invalid"),
        capacity_units=int(row["capacity_units"]),
        allowed_paths=_decode_tuple(
            row["allowed_paths_json"], "worker_registration_paths_invalid"
        ),
        expires_unix_ns=int(row["expires_unix_ns"]),
        state=str(row["state"]),
        revision=int(row["revision"]),
    )


def worker_registration_state(
    store: EngineeringStore, worker_id: str
) -> WorkerRegistrationState:
    checked_id(worker_id, "worker_id")
    row = store.connection.execute(
        "SELECT * FROM worker_registrations WHERE worker_id=?", (worker_id,)
    ).fetchone()
    if row is None:
        raise EngineeringError("unknown_worker")
    return _state(row)


def _profile_digest(
    worker_id: str,
    worker_signing_identity: str,
    skills: tuple[str, ...],
    capacity_units: int,
    allowed_paths: tuple[str, ...],
) -> str:
    return semantic_digest(
        {
            "workerId": worker_id,
            "workerSigningIdentity": worker_signing_identity,
            "skills": tuple(sorted(skills)),
            "capacityUnits": capacity_units,
            "allowedPaths": allowed_paths,
        }
    )


def _validate_authority_receipt(
    receipt: object,
    issuer: str,
    signing_identity: str,
    signature: str,
    observed_unix_ns: int,
    expires_unix_ns: int,
    trust_store: SignatureTrustStore,
    clock_policy: ClockPolicy,
    *,
    clock: Clock | None,
    now_ns: int | None,
) -> int:
    if issuer != WORKER_IDENTITY_ISSUER:
        raise EngineeringError("worker_registration_issuer_role")
    checked_id(signing_identity, "signing_identity")
    now = validate_observation_window(
        observed_unix_ns,
        expires_unix_ns,
        clock_policy,
        clock=clock,
        now_ns=now_ns,
    )
    if not trust_store.verify(receipt, issuer, signing_identity, signature):
        raise EngineeringError("worker_registration_signature")
    return now


def _validate_profile(
    worker_id: str,
    signing_identity: str,
    skills: tuple[str, ...],
    capacity_units: int,
    allowed_paths: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    checked_id(worker_id, "worker_id")
    checked_id(signing_identity, "worker_signing_identity")
    if (
        not isinstance(skills, tuple)
        or len(skills) > 64
        or len(set(skills)) != len(skills)
        or any(not isinstance(skill, str) for skill in skills)
    ):
        raise EngineeringError("invalid_worker_profile")
    normalized_skills = tuple(sorted(checked_id(skill, "worker_skill") for skill in skills))
    if type(capacity_units) is not int or not 1 <= capacity_units <= 1_000_000:
        raise EngineeringError("invalid_worker_profile")
    normalized_paths = canonical_paths(allowed_paths)
    return (
        normalized_skills,
        normalized_paths,
        _profile_digest(
            worker_id,
            signing_identity,
            normalized_skills,
            capacity_units,
            normalized_paths,
        ),
    )


def _active_reservation_units(store: EngineeringStore, worker_id: str) -> int:
    row = store.connection.execute(
        "SELECT COALESCE(SUM(capacity_units),0) FROM worker_capacity_reservations "
        "WHERE worker_id=? AND state='active'",
        (worker_id,),
    ).fetchone()
    return int(row[0])


def _validate_active_claim_scope(
    store: EngineeringStore, worker_id: str, allowed_paths: tuple[str, ...]
) -> None:
    rows = store.connection.execute(
        "SELECT l.paths_json FROM worker_claims c JOIN path_leases l "
        "ON l.lease_id=c.lease_id WHERE c.worker_id=? "
        "AND c.state IN ('claimed','running') ORDER BY c.claim_fence",
        (worker_id,),
    ).fetchall()
    for row in rows:
        paths = _decode_tuple(row["paths_json"], "claim_lease_invalid")
        if any(not path_is_within(path, allowed_paths) for path in paths):
            raise EngineeringError("worker_registration_scope_would_orphan_claim")


def renew_worker_registration(
    store: EngineeringStore,
    receipt: WorkerRegistrationRenewalReceipt,
    trust_store: SignatureTrustStore,
    clock_policy: ClockPolicy,
    *,
    clock: Clock | None = None,
    now_ns: int | None = None,
) -> WorkerRegistrationState:
    if not isinstance(receipt, WorkerRegistrationRenewalReceipt):
        raise EngineeringError("worker_registration_renewal_required")
    checked_sha256(receipt.previous_profile_digest, "previous_profile_digest")
    if type(receipt.expected_revision) is not int or receipt.expected_revision < 1:
        raise EngineeringError("stale_worker_revision")
    skills, paths, target_digest = _validate_profile(
        receipt.worker_id,
        receipt.worker_signing_identity,
        receipt.skills,
        receipt.capacity_units,
        receipt.allowed_paths,
    )
    now = _validate_authority_receipt(
        receipt,
        receipt.issuer,
        receipt.signing_identity,
        receipt.signature,
        receipt.observed_unix_ns,
        receipt.expires_unix_ns,
        trust_store,
        clock_policy,
        clock=clock,
        now_ns=now_ns,
    )
    with store._transaction():
        row = store.connection.execute(
            "SELECT * FROM worker_registrations WHERE worker_id=?",
            (receipt.worker_id,),
        ).fetchone()
        if row is None:
            raise EngineeringError("unknown_worker")
        current = _state(row)
        if (
            current.revision == receipt.expected_revision + 1
            and current.profile_digest == target_digest
            and current.expires_unix_ns == receipt.expires_unix_ns
            and current.state == "active"
        ):
            return current
        if current.revision != receipt.expected_revision:
            raise EngineeringError("stale_worker_revision")
        if current.state != "active":
            raise EngineeringError("worker_not_active")
        if current.profile_digest != receipt.previous_profile_digest:
            raise EngineeringError("worker_profile_drift")
        if current.worker_signing_identity != receipt.worker_signing_identity:
            raise EngineeringError("worker_registration_rotation_required")
        reserved = _active_reservation_units(store, receipt.worker_id)
        if reserved > receipt.capacity_units:
            raise EngineeringError("worker_capacity_shrink_conflict")
        _validate_active_claim_scope(store, receipt.worker_id, paths)
        revision = receipt.expected_revision + 1
        updated = store.connection.execute(
            "UPDATE worker_registrations SET profile_digest=?,skills_json=?,"
            "allowed_paths_json=?,capacity_units=?,issuer=?,"
            "authority_signing_identity=?,observed_unix_ns=?,expires_unix_ns=?,"
            "revision=?,recorded_unix_ns=? WHERE worker_id=? AND revision=? AND state='active'",
            (
                target_digest,
                canonical_json(skills),
                canonical_json(paths),
                receipt.capacity_units,
                receipt.issuer,
                receipt.signing_identity,
                receipt.observed_unix_ns,
                receipt.expires_unix_ns,
                revision,
                now,
                receipt.worker_id,
                receipt.expected_revision,
            ),
        )
        if updated.rowcount != 1:
            raise EngineeringError("worker_registration_race")
        store._append_audit(
            "worker_registration_renewed",
            {
                "workerId": receipt.worker_id,
                "priorProfileDigest": receipt.previous_profile_digest,
                "profileDigest": target_digest,
                "receiptDigest": semantic_digest(asdict(receipt)),
                "revision": revision,
            },
            now,
        )
        result = store.connection.execute(
            "SELECT * FROM worker_registrations WHERE worker_id=?",
            (receipt.worker_id,),
        ).fetchone()
    return _state(result)


def rotate_worker_signing_identity(
    store: EngineeringStore,
    receipt: WorkerKeyRotationReceipt,
    trust_store: SignatureTrustStore,
    clock_policy: ClockPolicy,
    *,
    clock: Clock | None = None,
    now_ns: int | None = None,
) -> WorkerRegistrationState:
    if not isinstance(receipt, WorkerKeyRotationReceipt):
        raise EngineeringError("worker_key_rotation_required")
    checked_id(receipt.worker_id, "worker_id")
    checked_id(receipt.previous_worker_signing_identity, "worker_signing_identity")
    checked_id(receipt.new_worker_signing_identity, "worker_signing_identity")
    if receipt.previous_worker_signing_identity == receipt.new_worker_signing_identity:
        raise EngineeringError("worker_key_rotation_no_change")
    checked_sha256(receipt.previous_profile_digest, "previous_profile_digest")
    if type(receipt.expected_revision) is not int or receipt.expected_revision < 1:
        raise EngineeringError("stale_worker_revision")
    now = _validate_authority_receipt(
        receipt,
        receipt.issuer,
        receipt.signing_identity,
        receipt.signature,
        receipt.observed_unix_ns,
        receipt.expires_unix_ns,
        trust_store,
        clock_policy,
        clock=clock,
        now_ns=now_ns,
    )
    with store._transaction():
        row = store.connection.execute(
            "SELECT * FROM worker_registrations WHERE worker_id=?",
            (receipt.worker_id,),
        ).fetchone()
        if row is None:
            raise EngineeringError("unknown_worker")
        current = _state(row)
        target_digest = _profile_digest(
            current.worker_id,
            receipt.new_worker_signing_identity,
            current.skills,
            current.capacity_units,
            current.allowed_paths,
        )
        if (
            current.revision == receipt.expected_revision + 1
            and current.worker_signing_identity == receipt.new_worker_signing_identity
            and current.profile_digest == target_digest
        ):
            return current
        if current.revision != receipt.expected_revision:
            raise EngineeringError("stale_worker_revision")
        if current.state != "active":
            raise EngineeringError("worker_not_active")
        if (
            current.profile_digest != receipt.previous_profile_digest
            or current.worker_signing_identity
            != receipt.previous_worker_signing_identity
        ):
            raise EngineeringError("worker_profile_drift")
        active = store.connection.execute(
            "SELECT 1 FROM worker_claims WHERE worker_id=? "
            "AND state IN ('claimed','running','result_submitted') LIMIT 1",
            (receipt.worker_id,),
        ).fetchone()
        if active is not None or _active_reservation_units(store, receipt.worker_id) != 0:
            raise EngineeringError("worker_key_rotation_active_claims")
        revision = receipt.expected_revision + 1
        updated = store.connection.execute(
            "UPDATE worker_registrations SET worker_signing_identity=?,"
            "profile_digest=?,issuer=?,authority_signing_identity=?,"
            "observed_unix_ns=?,expires_unix_ns=?,revision=?,recorded_unix_ns=? "
            "WHERE worker_id=? AND revision=? AND state='active'",
            (
                receipt.new_worker_signing_identity,
                target_digest,
                receipt.issuer,
                receipt.signing_identity,
                receipt.observed_unix_ns,
                receipt.expires_unix_ns,
                revision,
                now,
                receipt.worker_id,
                receipt.expected_revision,
            ),
        )
        if updated.rowcount != 1:
            raise EngineeringError("worker_registration_race")
        store._append_audit(
            "worker_signing_identity_rotated",
            {
                "workerId": receipt.worker_id,
                "previousSigningIdentity": receipt.previous_worker_signing_identity,
                "newSigningIdentity": receipt.new_worker_signing_identity,
                "profileDigest": target_digest,
                "receiptDigest": semantic_digest(asdict(receipt)),
                "revision": revision,
            },
            now,
        )
        result = store.connection.execute(
            "SELECT * FROM worker_registrations WHERE worker_id=?",
            (receipt.worker_id,),
        ).fetchone()
    return _state(result)
