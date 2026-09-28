"""Revision-bound worker registration renewal and signing-key rotation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json

from .clock_policy import ClockPolicy, validate_signed_window
from .control_plane import (
    EngineeringError,
    EngineeringStore,
    canonical_json,
    canonical_paths,
    checked_id,
    semantic_digest,
)
from .evidence import SignatureTrustStore
from .worker_lifecycle import WORKER_IDENTITY_ISSUER

MAX_WORKER_SKILLS = 64


@dataclass(frozen=True)
class WorkerRegistrationRenewalReceipt:
    worker_id: str
    expected_revision: int
    previous_profile_digest: str
    previous_signing_identity: str
    worker_signing_identity: str
    skills: tuple[str, ...]
    capacity_units: int
    allowed_paths: tuple[str, ...]
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    rotation_reason: str = ""
    signature: str = ""


@dataclass(frozen=True)
class WorkerRegistrationRenewalDecision:
    worker_id: str
    profile_digest: str
    revision: int
    key_rotated: bool
    replayed: bool
    receipt_digest: str


def _profile(receipt: WorkerRegistrationRenewalReceipt) -> tuple[dict[str, object], tuple[str, ...], tuple[str, ...]]:
    checked_id(receipt.worker_id, "worker_id")
    checked_id(receipt.previous_signing_identity, "previous_signing_identity")
    if (
        not isinstance(receipt.previous_profile_digest, str)
        or len(receipt.previous_profile_digest) != 64
        or any(character not in "0123456789abcdef" for character in receipt.previous_profile_digest)
    ):
        raise EngineeringError("invalid_previous_profile_digest")
    checked_id(receipt.worker_signing_identity, "worker_signing_identity")
    if (
        type(receipt.expected_revision) is not int
        or receipt.expected_revision < 1
        or type(receipt.capacity_units) is not int
        or not 1 <= receipt.capacity_units <= 1_000_000
        or not isinstance(receipt.skills, tuple)
        or len(receipt.skills) > MAX_WORKER_SKILLS
        or len(set(receipt.skills)) != len(receipt.skills)
    ):
        raise EngineeringError("invalid_worker_renewal")
    skills = tuple(sorted(checked_id(value, "worker_skill") for value in receipt.skills))
    paths = canonical_paths(receipt.allowed_paths)
    if not paths:
        raise EngineeringError("invalid_worker_renewal")
    profile = {
        "workerId": receipt.worker_id,
        "workerSigningIdentity": receipt.worker_signing_identity,
        "skills": skills,
        "capacityUnits": receipt.capacity_units,
        "allowedPaths": paths,
    }
    return profile, skills, paths


def _decode_tuple(value: object, code: str) -> tuple[str, ...]:
    try:
        raw = value if isinstance(value, str) else bytes(value).decode("utf-8")
        parsed = json.loads(raw)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise EngineeringError(code) from None
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise EngineeringError(code)
    return tuple(parsed)


def _renewal_replay_present(
    store: EngineeringStore,
    worker_id: str,
    receipt_digest: str,
) -> bool:
    rows = store.connection.execute(
        "SELECT payload_json FROM audit_events WHERE event_type='worker_registration_renewed' "
        "ORDER BY sequence DESC LIMIT 256"
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(bytes(row[0]).decode("utf-8"))
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
            raise EngineeringError("audit_payload_invalid") from None
        if (
            isinstance(payload, dict)
            and payload.get("workerId") == worker_id
            and payload.get("renewalDigest") == receipt_digest
        ):
            return True
    return False


def renew_worker_registration(
    store: EngineeringStore,
    receipt: WorkerRegistrationRenewalReceipt,
    trust_store: SignatureTrustStore,
    *,
    now_ns: int,
    clock_policy: ClockPolicy = ClockPolicy(),
) -> WorkerRegistrationRenewalDecision:
    if not isinstance(store, EngineeringStore):
        raise EngineeringError("worker_renewal_store_required")
    if not isinstance(receipt, WorkerRegistrationRenewalReceipt):
        raise EngineeringError("worker_renewal_receipt_required")
    if receipt.issuer != WORKER_IDENTITY_ISSUER:
        raise EngineeringError("worker_renewal_issuer_role")
    profile, skills, paths = _profile(receipt)
    validate_signed_window(
        receipt.observed_unix_ns,
        receipt.expires_unix_ns,
        now_ns=now_ns,
        policy=clock_policy,
        label="worker_renewal",
    )
    if not trust_store.verify(
        receipt,
        receipt.issuer,
        receipt.signing_identity,
        receipt.signature,
    ):
        raise EngineeringError("worker_renewal_signature")
    receipt_digest = semantic_digest(asdict(receipt))
    target_profile_digest = semantic_digest(profile)

    with store._transaction():
        row = store.connection.execute(
            "SELECT * FROM worker_registrations WHERE worker_id=?",
            (receipt.worker_id,),
        ).fetchone()
        if row is None:
            raise EngineeringError("unknown_worker")
        current_revision = int(row["revision"])
        current_profile_digest = str(row["profile_digest"])
        current_identity = str(row["worker_signing_identity"])
        current_skills = _decode_tuple(row["skills_json"], "worker_registration_invalid")
        current_paths = _decode_tuple(
            row["allowed_paths_json"], "worker_registration_invalid"
        )
        current_capacity = int(row["capacity_units"])

        target_matches = (
            str(row["state"]) == "active"
            and current_profile_digest == target_profile_digest
            and current_identity == receipt.worker_signing_identity
            and current_skills == skills
            and current_paths == paths
            and current_capacity == receipt.capacity_units
            and int(row["expires_unix_ns"]) == receipt.expires_unix_ns
        )
        if current_revision == receipt.expected_revision + 1 and target_matches:
            if not _renewal_replay_present(store, receipt.worker_id, receipt_digest):
                raise EngineeringError("worker_renewal_replay_conflict")
            return WorkerRegistrationRenewalDecision(
                receipt.worker_id,
                target_profile_digest,
                current_revision,
                current_identity != receipt.previous_signing_identity,
                True,
                receipt_digest,
            )
        if current_revision != receipt.expected_revision:
            raise EngineeringError("stale_worker_revision")
        if str(row["state"]) != "active":
            raise EngineeringError("worker_not_active")
        if (
            current_profile_digest != receipt.previous_profile_digest
            or current_identity != receipt.previous_signing_identity
        ):
            raise EngineeringError("worker_renewal_predecessor_mismatch")
        if receipt.expires_unix_ns < int(row["expires_unix_ns"]):
            raise EngineeringError("worker_renewal_expiry_regression")

        reserved = int(
            store.connection.execute(
                "SELECT COALESCE(SUM(capacity_units),0) FROM worker_capacity_reservations "
                "WHERE worker_id=? AND state='active'",
                (receipt.worker_id,),
            ).fetchone()[0]
        )
        if receipt.capacity_units < reserved:
            raise EngineeringError("worker_renewal_capacity_below_reservation")
        active_claims = int(
            store.connection.execute(
                "SELECT COUNT(*) FROM worker_claims WHERE worker_id=? "
                "AND state IN ('claimed','running')",
                (receipt.worker_id,),
            ).fetchone()[0]
        )
        key_rotated = receipt.worker_signing_identity != current_identity
        profile_restricted = (
            skills != current_skills
            or paths != current_paths
            or receipt.capacity_units < current_capacity
        )
        if active_claims and (key_rotated or profile_restricted):
            raise EngineeringError("worker_renewal_requires_quiescence")
        if key_rotated:
            checked_id(receipt.rotation_reason, "rotation_reason")
        elif receipt.rotation_reason:
            raise EngineeringError("worker_renewal_unexpected_rotation_reason")

        revision = current_revision + 1
        updated = store.connection.execute(
            "UPDATE worker_registrations SET profile_digest=?,worker_signing_identity=?,"
            "skills_json=?,allowed_paths_json=?,capacity_units=?,issuer=?,"
            "authority_signing_identity=?,observed_unix_ns=?,expires_unix_ns=?,"
            "revision=?,recorded_unix_ns=? WHERE worker_id=? AND revision=? AND state='active'",
            (
                target_profile_digest,
                receipt.worker_signing_identity,
                canonical_json(skills),
                canonical_json(paths),
                receipt.capacity_units,
                receipt.issuer,
                receipt.signing_identity,
                receipt.observed_unix_ns,
                receipt.expires_unix_ns,
                revision,
                now_ns,
                receipt.worker_id,
                current_revision,
            ),
        )
        if updated.rowcount != 1:
            raise EngineeringError("worker_renewal_race")
        store._append_audit(
            "worker_registration_renewed",
            {
                "workerId": receipt.worker_id,
                "revision": revision,
                "profileDigest": target_profile_digest,
                "keyRotated": key_rotated,
                "renewalDigest": receipt_digest,
            },
            now_ns,
        )
    return WorkerRegistrationRenewalDecision(
        receipt.worker_id,
        target_profile_digest,
        revision,
        key_rotated,
        False,
        receipt_digest,
    )
