"""Fail-closed external evidence adapters for production Lane G.

Repository code can verify external receipts, but it cannot manufacture the
external authority they represent. Production composition supplies a verifier
backed by an independently controlled keystore/HSM or equivalent trust service.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import time
from typing import Iterable, Mapping, Protocol

from .control_plane import (
    ZERO_DIGEST,
    EngineeringError,
    EngineeringStore,
    checked_id,
    checked_sha256,
    semantic_digest,
)


class ReceiptVerifier(Protocol):
    def verify(
        self,
        value: object,
        issuer: str,
        signing_identity: str,
        signature: str,
    ) -> bool: ...


@dataclass(frozen=True)
class ExternalFactReceipt:
    fact: str
    subject_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class AuditAnchorReceipt:
    store_identity_digest: str
    audit_sequence: int
    audit_head_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class KeyCustodyReceipt:
    provider: str
    key_identity: str
    allowed_roles: tuple[str, ...]
    custody_policy_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


_FACT_ISSUERS = {
    "independent_review_accepted": frozenset({"independent_review_authority"}),
    "authorized_handoff": frozenset({"deployment_handoff_authority"}),
    "strong_sandbox_observed": frozenset({"sandbox_qualification_authority"}),
    "deployment_observed": frozenset({"deployment_authority"}),
    "rollback_rehearsed": frozenset({"rollback_authority"}),
    "distributed_fencing_verified": frozenset({"coordination_authority"}),
}
_ALLOWED_FACTS = frozenset(_FACT_ISSUERS)


def _now(value: int | None) -> int:
    current = time.time_ns() if value is None else value
    if type(current) is not int or current < 0:
        raise EngineeringError("invalid_time")
    return current


def _window(observed: int, expires: int, now: int) -> bool:
    return (
        type(observed) is int
        and type(expires) is int
        and observed <= now < expires
        and expires > observed
    )


def verify_external_fact_receipts(
    receipts: Iterable[ExternalFactReceipt],
    verifier: ReceiptVerifier,
    *,
    subject_digest: str,
    now_ns: int | None = None,
) -> dict[str, str]:
    """Return authenticated fact -> receipt digest, rejecting duplicates/drift."""
    now = _now(now_ns)
    checked_sha256(subject_digest, "subject_digest")
    result: dict[str, str] = {}
    for receipt in receipts:
        if not isinstance(receipt, ExternalFactReceipt):
            raise EngineeringError("invalid_external_fact_receipt")
        if receipt.fact not in _ALLOWED_FACTS:
            raise EngineeringError("invalid_external_fact")
        if receipt.fact in result:
            raise EngineeringError("duplicate_external_fact")
        checked_sha256(receipt.subject_digest, "subject_digest")
        if receipt.subject_digest != subject_digest:
            raise EngineeringError("external_fact_subject_mismatch")
        checked_id(receipt.issuer, "external_fact_issuer")
        checked_id(receipt.signing_identity, "external_fact_signing_identity")
        if receipt.issuer not in _FACT_ISSUERS[receipt.fact]:
            raise EngineeringError("external_fact_issuer_role")
        if not _window(receipt.observed_unix_ns, receipt.expires_unix_ns, now):
            raise EngineeringError("external_fact_stale")
        if not verifier.verify(
            receipt, receipt.issuer, receipt.signing_identity, receipt.signature
        ):
            raise EngineeringError("external_fact_signature")
        result[receipt.fact] = semantic_digest(asdict(receipt))
    return result


def verify_audit_anchor(
    receipt: AuditAnchorReceipt,
    verifier: ReceiptVerifier,
    *,
    expected_store_identity_digest: str,
    expected_sequence: int,
    expected_head_digest: str,
    now_ns: int | None = None,
) -> str:
    now = _now(now_ns)
    if not isinstance(receipt, AuditAnchorReceipt):
        raise EngineeringError("audit_anchor_required")
    checked_sha256(expected_store_identity_digest, "store_identity_digest")
    checked_sha256(expected_head_digest, "audit_head_digest")
    checked_sha256(receipt.store_identity_digest, "store_identity_digest")
    checked_sha256(receipt.audit_head_digest, "audit_head_digest")
    if (
        type(expected_sequence) is not int
        or expected_sequence < 0
        or type(receipt.audit_sequence) is not int
        or receipt.audit_sequence < 0
    ):
        raise EngineeringError("invalid_audit_sequence")
    if (
        receipt.store_identity_digest != expected_store_identity_digest
        or receipt.audit_sequence != expected_sequence
        or receipt.audit_head_digest != expected_head_digest
    ):
        raise EngineeringError("audit_anchor_mismatch")
    if receipt.issuer != "audit_anchor_authority":
        raise EngineeringError("audit_anchor_issuer_role")
    if not _window(receipt.observed_unix_ns, receipt.expires_unix_ns, now):
        raise EngineeringError("audit_anchor_stale")
    if not verifier.verify(receipt, receipt.issuer, receipt.signing_identity, receipt.signature):
        raise EngineeringError("audit_anchor_signature")
    return semantic_digest(asdict(receipt))


def verify_key_custody(
    receipt: KeyCustodyReceipt,
    verifier: ReceiptVerifier,
    *,
    required_roles: Iterable[str],
    now_ns: int | None = None,
) -> str:
    now = _now(now_ns)
    if not isinstance(receipt, KeyCustodyReceipt):
        raise EngineeringError("key_custody_receipt_required")
    checked_id(receipt.provider, "key_provider")
    checked_id(receipt.key_identity, "key_identity")
    checked_sha256(receipt.custody_policy_digest, "custody_policy_digest")
    roles = tuple(sorted(set(required_roles)))
    if not roles or any(not isinstance(role, str) or not role for role in roles):
        raise EngineeringError("invalid_key_custody_role")
    if not set(roles).issubset(set(receipt.allowed_roles)):
        raise EngineeringError("key_custody_role_missing")
    if receipt.issuer != "key_custody_authority":
        raise EngineeringError("key_custody_issuer_role")
    if not _window(receipt.observed_unix_ns, receipt.expires_unix_ns, now):
        raise EngineeringError("key_custody_receipt_stale")
    if not verifier.verify(receipt, receipt.issuer, receipt.signing_identity, receipt.signature):
        raise EngineeringError("key_custody_signature")
    return semantic_digest(asdict(receipt))



def verify_store_audit_anchor(
    store: EngineeringStore,
    receipt: AuditAnchorReceipt,
    verifier: ReceiptVerifier,
    *,
    store_identity_digest: str,
    now_ns: int | None = None,
) -> str:
    """Bind an external anchor directly to the currently verified SQLite audit head."""
    if not isinstance(store, EngineeringStore):
        raise EngineeringError("engineering_store_required")
    checked_sha256(store_identity_digest, "store_identity_digest")
    store.verify_audit_chain()
    row = store.connection.execute(
        "SELECT sequence,event_digest FROM audit_events ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    sequence = 0 if row is None else int(row["sequence"])
    head = ZERO_DIGEST if row is None else str(row["event_digest"])
    return verify_audit_anchor(
        receipt,
        verifier,
        expected_store_identity_digest=store_identity_digest,
        expected_sequence=sequence,
        expected_head_digest=head,
        now_ns=now_ns,
    )


def verify_key_custody_set(
    receipts: Iterable[KeyCustodyReceipt],
    verifier: ReceiptVerifier,
    *,
    required_role_keys: Mapping[str, str],
    now_ns: int | None = None,
) -> str:
    """Require distinct externally custodied key identities for each required role."""
    if not isinstance(required_role_keys, Mapping) or not required_role_keys:
        raise EngineeringError("key_custody_roles_required")
    expected: dict[str, str] = {}
    for role, key_identity in required_role_keys.items():
        if not isinstance(role, str) or not role:
            raise EngineeringError("invalid_key_custody_role")
        checked_id(key_identity, "key_identity")
        expected[role] = key_identity
    if len(set(expected.values())) != len(expected):
        raise EngineeringError("key_custody_role_collision")

    values = tuple(receipts)
    if len(values) > 32:
        raise EngineeringError("key_custody_receipt_limit_exceeded")
    by_key: dict[str, KeyCustodyReceipt] = {}
    for receipt in values:
        if not isinstance(receipt, KeyCustodyReceipt):
            raise EngineeringError("key_custody_receipt_required")
        if receipt.key_identity in by_key:
            raise EngineeringError("duplicate_key_custody_receipt")
        by_key[receipt.key_identity] = receipt

    digests: dict[str, str] = {}
    for role, key_identity in sorted(expected.items()):
        receipt = by_key.get(key_identity)
        if receipt is None:
            raise EngineeringError("key_custody_receipt_missing")
        digests[role] = verify_key_custody(
            receipt,
            verifier,
            required_roles=(role,),
            now_ns=now_ns,
        )
    return semantic_digest(digests)
