"""Registration renewal on the existing EngineeringStore transaction and audit.

The audit is the existing durable fact owner, not a second result database.
A replay authenticates the original signed receipt against the current verifier,
then returns its retained result without renewing authority or changing state.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import time

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
from .time_policy import (
    ClockSkewPolicy,
    STRICT_CLOCK_SKEW_POLICY,
    validate_signed_window,
)


@dataclass(frozen=True)
class WorkerRegistrationRenewalReceipt:
    worker_id: str
    expected_revision: int
    predecessor_profile_digest: str
    worker_signing_identity: str
    skills: tuple[str, ...]
    capacity_units: int
    allowed_paths: tuple[str, ...]
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


def renew_worker_registration(
    store: EngineeringStore,
    receipt: WorkerRegistrationRenewalReceipt,
    trust_store: SignatureTrustStore,
    *,
    now_ns: int | None = None,
    clock_policy: ClockSkewPolicy = STRICT_CLOCK_SKEW_POLICY,
) -> str:
    """Renew one authenticated revision, or return its exact committed outcome.

    Historical replay does not require the old execution window to remain live.
    It does require a currently accepted signature and an active worker. The
    original expiry is never extended by replay. Changing receipt bytes under
    the same worker/revision identity is a conflict even when the resulting
    profile happens to be identical.
    """
    if not isinstance(store, EngineeringStore) or not isinstance(
        receipt, WorkerRegistrationRenewalReceipt
    ):
        raise EngineeringError("worker_registration_renewal_required")
    checked_id(receipt.worker_id, "worker_id")
    checked_id(receipt.worker_signing_identity, "worker_signing_identity")
    checked_id(receipt.signing_identity, "signing_identity")
    checked_sha256(receipt.predecessor_profile_digest, "predecessor_profile_digest")
    if receipt.issuer != "engineering_worker_identity":
        raise EngineeringError("worker_registration_renewal_issuer_role")
    if type(receipt.expected_revision) is not int or not 1 <= receipt.expected_revision < 2**63 - 1:
        raise EngineeringError("invalid_worker_registration_revision")
    if (
        type(receipt.capacity_units) is not int
        or not 1 <= receipt.capacity_units <= 1_000_000
        or not isinstance(receipt.skills, tuple)
        or len(receipt.skills) > 64
        or any(not isinstance(skill, str) for skill in receipt.skills)
        or len(set(receipt.skills)) != len(receipt.skills)
        or not isinstance(receipt.signature, str)
        or not 1 <= len(receipt.signature) <= 16384
    ):
        raise EngineeringError("invalid_worker_profile")
    for skill in receipt.skills:
        checked_id(skill, "worker_skill")
    for value in (receipt.observed_unix_ns, receipt.expires_unix_ns):
        if type(value) is not int or not 0 <= value <= 2**63 - 1:
            raise EngineeringError("invalid_time")
    if receipt.observed_unix_ns >= receipt.expires_unix_ns:
        raise EngineeringError("worker_registration_renewal_invalid_window")
    if not isinstance(clock_policy, ClockSkewPolicy):
        raise EngineeringError("invalid_clock_skew_policy")
    paths = canonical_paths(receipt.allowed_paths)
    skills = tuple(sorted(receipt.skills))
    if not trust_store.verify(receipt, receipt.issuer, receipt.signing_identity, receipt.signature):
        raise EngineeringError("worker_registration_renewal_signature")
    profile = {
        "workerId": receipt.worker_id,
        "workerSigningIdentity": receipt.worker_signing_identity,
        "skills": skills,
        "capacityUnits": receipt.capacity_units,
        "allowedPaths": paths,
    }
    digest = semantic_digest(profile)
    receipt_digest = semantic_digest(asdict(receipt))
    with store._transaction():
        now = time.time_ns() if now_ns is None else now_ns
        if type(now) is not int or not 0 <= now <= 2**63 - 1:
            raise EngineeringError("invalid_time")
        current = store.connection.execute(
            "SELECT * FROM worker_registrations WHERE worker_id=?", (receipt.worker_id,)
        ).fetchone()
        if current is None:
            raise EngineeringError("unknown_worker")
        if current["state"] != "active":
            raise EngineeringError("worker_not_active")
        # Cold-path exact lookup in the canonical audit. LIMIT bounds returned
        # payloads; this is not advertised as a history-independent SQL scan.
        prior = store.connection.execute(
            "SELECT payload_json FROM audit_events "
            "WHERE event_type='worker_registration_renewed' "
            "AND json_extract(payload_json,'$.workerId')=? "
            "AND json_extract(payload_json,'$.expectedRevision')=? "
            "ORDER BY sequence DESC LIMIT 1",
            (receipt.worker_id, receipt.expected_revision),
        ).fetchone()
        if prior is not None:
            observed = json.loads(bytes(prior[0]).decode("utf-8"))
            if (
                observed.get("receiptDigest") != receipt_digest
                or observed.get("profileDigest") != digest
                or observed.get("resultingRevision") != receipt.expected_revision + 1
            ):
                raise EngineeringError("worker_renewal_identity_conflict")
            return digest
        validate_signed_window(
            receipt.observed_unix_ns, receipt.expires_unix_ns, now,
            policy=clock_policy,
        )
        if int(current["revision"]) != receipt.expected_revision:
            raise EngineeringError("stale_worker_revision")
        if current["profile_digest"] != receipt.predecessor_profile_digest:
            raise EngineeringError("worker_registration_predecessor_mismatch")
        if receipt.observed_unix_ns < int(current["observed_unix_ns"]):
            raise EngineeringError("worker_registration_renewal_order")
        if receipt.expires_unix_ns < int(current["expires_unix_ns"]):
            raise EngineeringError("worker_registration_expiry_regression")
        used = int(store.connection.execute(
            "SELECT COALESCE(SUM(capacity_units),0) FROM worker_capacity_reservations "
            "WHERE worker_id=? AND state='active'", (receipt.worker_id,)
        ).fetchone()[0])
        if used > receipt.capacity_units:
            raise EngineeringError("worker_registration_capacity_below_reserved")
        changed_binding = (
            current["worker_signing_identity"] != receipt.worker_signing_identity
            or bytes(current["skills_json"]) != canonical_json(skills)
            or bytes(current["allowed_paths_json"]) != canonical_json(paths)
        )
        if used and changed_binding:
            raise EngineeringError("worker_registration_rotation_with_active_claims")
        updated = store.connection.execute(
            "UPDATE worker_registrations SET profile_digest=?,worker_signing_identity=?,"
            "skills_json=?,allowed_paths_json=?,capacity_units=?,issuer=?,"
            "authority_signing_identity=?,observed_unix_ns=?,expires_unix_ns=?,"
            "revision=revision+1,recorded_unix_ns=? WHERE worker_id=? AND revision=?",
            (digest, receipt.worker_signing_identity, canonical_json(skills),
             canonical_json(paths), receipt.capacity_units, receipt.issuer,
             receipt.signing_identity, receipt.observed_unix_ns,
             receipt.expires_unix_ns, now, receipt.worker_id, receipt.expected_revision),
        )
        if updated.rowcount != 1:
            raise EngineeringError("stale_worker_revision")
        store._append_audit("worker_registration_renewed", {
            "workerId": receipt.worker_id,
            "expectedRevision": receipt.expected_revision,
            "resultingRevision": receipt.expected_revision + 1,
            "predecessorProfileDigest": receipt.predecessor_profile_digest,
            "profileDigest": digest,
            "receiptDigest": receipt_digest,
            "expiresUnixNs": receipt.expires_unix_ns,
        }, now)
    return digest
