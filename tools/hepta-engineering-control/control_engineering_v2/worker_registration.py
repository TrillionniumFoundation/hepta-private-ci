"""Revision-bound worker registration renewal and signing-key rotation.

The SQLite v10 row already owns a monotonically increasing registration revision,
so renewal does not require a schema migration.  A receipt is authority-signed,
binds the predecessor profile/key/revision, and is replay-stable after an
acknowledgement loss.  Key/profile rotation is forbidden while a Worker has an
active claim; an expiry-only renewal may continue an already admitted Worker.
"""

from __future__ import annotations

from dataclasses import dataclass

from .clock_policy import (
    ClockSkewPolicy,
    STRICT_CLOCK_POLICY,
    checked_now,
    validate_signed_window,
)
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
from .worker_lifecycle import WORKER_IDENTITY_ISSUER


@dataclass(frozen=True)
class WorkerRegistrationRenewalReceipt:
    worker_id: str
    expected_revision: int
    predecessor_profile_digest: str
    predecessor_signing_identity: str
    worker_signing_identity: str
    skills: tuple[str, ...]
    capacity_units: int
    allowed_paths: tuple[str, ...]
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


def _profile(receipt: WorkerRegistrationRenewalReceipt) -> tuple[dict[str, object], tuple[str, ...]]:
    checked_id(receipt.worker_id, "worker_id")
    checked_id(receipt.predecessor_signing_identity, "predecessor_signing_identity")
    checked_id(receipt.worker_signing_identity, "worker_signing_identity")
    checked_id(receipt.signing_identity, "authority_signing_identity")
    checked_sha256(receipt.predecessor_profile_digest, "predecessor_profile_digest")
    if (
        type(receipt.expected_revision) is not int
        or receipt.expected_revision < 1
        or type(receipt.capacity_units) is not int
        or not 1 <= receipt.capacity_units <= 1_000_000
        or not isinstance(receipt.skills, tuple)
        or len(receipt.skills) > 64
        or len(set(receipt.skills)) != len(receipt.skills)
    ):
        raise EngineeringError("invalid_worker_registration_renewal")
    for skill in receipt.skills:
        checked_id(skill, "worker_skill")
    paths = canonical_paths(receipt.allowed_paths)
    profile = {
        "workerId": receipt.worker_id,
        "workerSigningIdentity": receipt.worker_signing_identity,
        "skills": tuple(sorted(receipt.skills)),
        "capacityUnits": receipt.capacity_units,
        "allowedPaths": paths,
    }
    return profile, paths


def renew_worker_registration(
    store: EngineeringStore,
    receipt: WorkerRegistrationRenewalReceipt,
    trust_store: SignatureTrustStore,
    *,
    clock_policy: ClockSkewPolicy = STRICT_CLOCK_POLICY,
    now_ns: int | None = None,
) -> str:
    """Renew or rotate one active registration under optimistic concurrency."""

    if not isinstance(store, EngineeringStore):
        raise EngineeringError("worker_registration_store_required")
    if not isinstance(receipt, WorkerRegistrationRenewalReceipt):
        raise EngineeringError("worker_registration_renewal_required")
    if receipt.issuer != WORKER_IDENTITY_ISSUER:
        raise EngineeringError("worker_registration_issuer_role")
    now = checked_now(now_ns)
    validate_signed_window(
        receipt.observed_unix_ns,
        receipt.expires_unix_ns,
        now,
        clock_policy,
        error_code="worker_registration_renewal_stale",
    )
    profile, paths = _profile(receipt)
    digest = semantic_digest(profile)
    if not trust_store.verify(
        receipt,
        receipt.issuer,
        receipt.signing_identity,
        receipt.signature,
    ):
        raise EngineeringError("worker_registration_renewal_signature")

    skills_json = canonical_json(tuple(sorted(receipt.skills)))
    paths_json = canonical_json(paths)
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
                str(current["profile_digest"]) == digest
                and str(current["worker_signing_identity"])
                == receipt.worker_signing_identity
                and bytes(current["skills_json"]) == skills_json
                and bytes(current["allowed_paths_json"]) == paths_json
                and int(current["capacity_units"]) == receipt.capacity_units
                and str(current["issuer"]) == receipt.issuer
                and str(current["authority_signing_identity"])
                == receipt.signing_identity
                and int(current["observed_unix_ns"])
                == receipt.observed_unix_ns
                and int(current["expires_unix_ns"])
                == receipt.expires_unix_ns
                and str(current["state"]) == "active"
            )
            if replay_matches:
                return digest
            raise EngineeringError("worker_registration_renewal_replay_conflict")
        if current_revision != receipt.expected_revision:
            raise EngineeringError("stale_worker_revision")
        if str(current["state"]) != "active":
            raise EngineeringError("worker_not_active")
        if int(current["expires_unix_ns"]) <= now:
            raise EngineeringError("worker_registration_expired")
        if (
            str(current["profile_digest"]) != receipt.predecessor_profile_digest
            or str(current["worker_signing_identity"])
            != receipt.predecessor_signing_identity
        ):
            raise EngineeringError("worker_registration_predecessor_mismatch")
        if receipt.observed_unix_ns < int(current["observed_unix_ns"]):
            raise EngineeringError("worker_registration_observation_rollback")
        if receipt.expires_unix_ns < int(current["expires_unix_ns"]):
            raise EngineeringError("worker_registration_expiry_rollback")

        profile_changed = (
            digest != str(current["profile_digest"])
            or receipt.worker_signing_identity
            != str(current["worker_signing_identity"])
        )
        expiry_changed = receipt.expires_unix_ns != int(current["expires_unix_ns"])
        if not profile_changed and not expiry_changed:
            raise EngineeringError("worker_registration_renewal_noop")

        active_claims = int(
            store.connection.execute(
                "SELECT COUNT(*) FROM worker_claims WHERE worker_id=? "
                "AND state IN ('claimed','running')",
                (receipt.worker_id,),
            ).fetchone()[0]
        )
        if active_claims and profile_changed:
            raise EngineeringError("worker_registration_rotation_active_claims")
        reserved = int(
            store.connection.execute(
                "SELECT COALESCE(SUM(capacity_units),0) "
                "FROM worker_capacity_reservations WHERE worker_id=? AND state='active'",
                (receipt.worker_id,),
            ).fetchone()[0]
        )
        if receipt.capacity_units < reserved:
            raise EngineeringError("worker_registration_capacity_below_reservation")

        revision = current_revision + 1
        updated = store.connection.execute(
            "UPDATE worker_registrations SET profile_digest=?,"
            "worker_signing_identity=?,skills_json=?,allowed_paths_json=?,"
            "capacity_units=?,issuer=?,authority_signing_identity=?,"
            "observed_unix_ns=?,expires_unix_ns=?,revision=?,recorded_unix_ns=? "
            "WHERE worker_id=? AND revision=? AND state='active'",
            (
                digest,
                receipt.worker_signing_identity,
                skills_json,
                paths_json,
                receipt.capacity_units,
                receipt.issuer,
                receipt.signing_identity,
                receipt.observed_unix_ns,
                receipt.expires_unix_ns,
                revision,
                now,
                receipt.worker_id,
                current_revision,
            ),
        )
        if updated.rowcount != 1:
            raise EngineeringError("stale_worker_revision")
        store._append_audit(
            "worker_registration_renewed",
            {
                "workerId": receipt.worker_id,
                "predecessorProfileDigest": receipt.predecessor_profile_digest,
                "profileDigest": digest,
                "signingIdentityRotated": (
                    receipt.worker_signing_identity
                    != receipt.predecessor_signing_identity
                ),
                "revision": revision,
                "expiresUnixNs": receipt.expires_unix_ns,
            },
            now,
        )
    return digest
