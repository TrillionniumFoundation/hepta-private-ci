"""Authenticated renewal and key rotation for durable Worker registrations."""

from __future__ import annotations

from dataclasses import dataclass

from .clock_policy import ClockSkewPolicy, validate_receipt_window
from .control_plane import (
    EngineeringError,
    EngineeringStore,
    canonical_json,
    canonical_paths,
    checked_id,
    checked_sha256,
    semantic_digest,
)
from .evidence import SignatureTrustStore

WORKER_IDENTITY_ISSUER = "engineering_worker_identity"
_ROTATION_REASONS = frozenset(
    {"renewal", "key_rotation", "capacity_change", "scope_change", "composite"}
)


@dataclass(frozen=True)
class WorkerRegistrationRotationReceipt:
    worker_id: str
    expected_revision: int
    predecessor_profile_digest: str
    worker_signing_identity: str
    skills: tuple[str, ...]
    capacity_units: int
    allowed_paths: tuple[str, ...]
    reason: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


def _rotation_profile(
    receipt: WorkerRegistrationRotationReceipt,
) -> tuple[dict[str, object], bytes, bytes]:
    checked_id(receipt.worker_id, "worker_id")
    checked_id(receipt.worker_signing_identity, "worker_signing_identity")
    checked_id(receipt.signing_identity, "signing_identity")
    checked_sha256(receipt.predecessor_profile_digest, "predecessor_profile_digest")
    if receipt.issuer != WORKER_IDENTITY_ISSUER:
        raise EngineeringError("worker_registration_issuer_role")
    if receipt.reason not in _ROTATION_REASONS:
        raise EngineeringError("worker_registration_rotation_reason")
    if type(receipt.expected_revision) is not int or receipt.expected_revision < 1:
        raise EngineeringError("worker_registration_rotation_revision")
    if (
        type(receipt.capacity_units) is not int
        or not 1 <= receipt.capacity_units <= 1_000_000
        or not isinstance(receipt.skills, tuple)
        or not receipt.skills
        or len(receipt.skills) > 64
        or len(set(receipt.skills)) != len(receipt.skills)
    ):
        raise EngineeringError("invalid_worker_profile")
    for skill in receipt.skills:
        checked_id(skill, "worker_skill")
    skills = tuple(sorted(receipt.skills))
    paths = canonical_paths(receipt.allowed_paths)
    profile: dict[str, object] = {
        "workerId": receipt.worker_id,
        "workerSigningIdentity": receipt.worker_signing_identity,
        "skills": skills,
        "capacityUnits": receipt.capacity_units,
        "allowedPaths": paths,
    }
    return profile, canonical_json(skills), canonical_json(paths)


def rotate_worker_registration(
    store: EngineeringStore,
    receipt: WorkerRegistrationRotationReceipt,
    trust_store: SignatureTrustStore,
    *,
    clock_policy: ClockSkewPolicy = ClockSkewPolicy(),
    now_ns: int | None = None,
) -> str:
    """Renew/rotate one Worker registration with revision and claim fencing."""

    if not isinstance(store, EngineeringStore):
        raise EngineeringError("worker_registration_store_required")
    if not isinstance(receipt, WorkerRegistrationRotationReceipt):
        raise EngineeringError("worker_registration_rotation_required")
    profile, skills_json, paths_json = _rotation_profile(receipt)
    now = store._now(now_ns)
    validate_receipt_window(
        receipt.observed_unix_ns,
        receipt.expires_unix_ns,
        now_ns=now,
        policy=clock_policy,
    )
    if not trust_store.verify(
        receipt,
        receipt.issuer,
        receipt.signing_identity,
        receipt.signature,
    ):
        raise EngineeringError("worker_registration_rotation_signature")
    new_digest = semantic_digest(profile)

    with store._transaction():
        current = store.connection.execute(
            "SELECT * FROM worker_registrations WHERE worker_id=?",
            (receipt.worker_id,),
        ).fetchone()
        if current is None:
            raise EngineeringError("unknown_worker")
        current_revision = int(current["revision"])
        if current_revision == receipt.expected_revision + 1:
            replay_matches = (
                str(current["state"]) == "active"
                and str(current["profile_digest"]) == new_digest
                and str(current["worker_signing_identity"])
                == receipt.worker_signing_identity
                and int(current["expires_unix_ns"]) == receipt.expires_unix_ns
                and str(current["issuer"]) == receipt.issuer
                and str(current["authority_signing_identity"])
                == receipt.signing_identity
            )
            if replay_matches:
                return new_digest
            raise EngineeringError("worker_registration_rotation_replay_conflict")
        if current_revision != receipt.expected_revision:
            raise EngineeringError("stale_worker_revision")
        if str(current["state"]) != "active":
            raise EngineeringError("worker_not_active")
        if int(current["expires_unix_ns"]) <= now:
            raise EngineeringError("worker_registration_expired")
        if str(current["profile_digest"]) != receipt.predecessor_profile_digest:
            raise EngineeringError("worker_registration_predecessor_mismatch")

        active_claims = int(
            store.connection.execute(
                "SELECT COUNT(*) FROM worker_claims WHERE worker_id=? "
                "AND state IN ('claimed','running')",
                (receipt.worker_id,),
            ).fetchone()[0]
        )
        profile_changed = (
            str(current["profile_digest"]) != new_digest
            or str(current["worker_signing_identity"])
            != receipt.worker_signing_identity
        )
        if active_claims and profile_changed:
            raise EngineeringError("worker_registration_active_claims")
        reserved_units = int(
            store.connection.execute(
                "SELECT COALESCE(SUM(capacity_units),0) FROM "
                "worker_capacity_reservations WHERE worker_id=? AND state='active'",
                (receipt.worker_id,),
            ).fetchone()[0]
        )
        if reserved_units > receipt.capacity_units:
            raise EngineeringError("worker_registration_capacity_below_reservations")
        if not profile_changed and receipt.expires_unix_ns <= int(current["expires_unix_ns"]):
            raise EngineeringError("worker_registration_renewal_not_extended")

        new_revision = current_revision + 1
        updated = store.connection.execute(
            "UPDATE worker_registrations SET profile_digest=?,"
            "worker_signing_identity=?,skills_json=?,allowed_paths_json=?,"
            "capacity_units=?,issuer=?,authority_signing_identity=?,"
            "observed_unix_ns=?,expires_unix_ns=?,revision=?,recorded_unix_ns=? "
            "WHERE worker_id=? AND revision=? AND state='active'",
            (
                new_digest,
                receipt.worker_signing_identity,
                skills_json,
                paths_json,
                receipt.capacity_units,
                receipt.issuer,
                receipt.signing_identity,
                receipt.observed_unix_ns,
                receipt.expires_unix_ns,
                new_revision,
                now,
                receipt.worker_id,
                current_revision,
            ),
        )
        if updated.rowcount != 1:
            raise EngineeringError("worker_registration_rotation_race")
        store._append_audit(
            "worker_registration_rotated",
            {
                "workerId": receipt.worker_id,
                "priorProfileDigest": receipt.predecessor_profile_digest,
                "profileDigest": new_digest,
                "reason": receipt.reason,
                "revision": new_revision,
                "keyRotated": str(current["worker_signing_identity"])
                != receipt.worker_signing_identity,
                "activeClaims": active_claims,
                "reservedUnits": reserved_units,
                "capacityUnits": receipt.capacity_units,
            },
            now,
        )
    return new_digest
