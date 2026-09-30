"""Role-separated external key custody with explicit rotation continuity.

The existing per-key custody receipts prove hardware/external custody at one
instant.  This module adds the production continuity contract that was missing:
rotation epochs, predecessor binding, dual-key windows, revocation frontiers and
an immutable external audit-anchor binding.  The receipt is evidence only; it
grants no runtime, merge, deployment, promotion or release authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import time
from typing import Iterable

from .control_plane import EngineeringError, bounded_tuple, semantic_digest
from .evidence import SignatureTrustStore

_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ALLOWED_ALGORITHMS = frozenset(
    {"ed25519", "ecdsa-p256-sha256", "rsa-pss-sha256"}
)
DEFAULT_REQUIRED_ROLES = (
    "source_authority",
    "ci_executor",
    "independent_evaluator",
    "engineering_evidence_binder",
)
MAX_CUSTODY_KEYS = 32


def _identity(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 256
        or value != value.strip()
        or "\x00" in value
    ):
        raise EngineeringError(label)
    return value


def _sha1(value: object, label: str) -> str:
    if not isinstance(value, str) or value == "0" * 40 or _SHA1.fullmatch(value) is None:
        raise EngineeringError(label)
    return value


def _sha256(value: object, label: str, *, allow_zero: bool = False) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise EngineeringError(label)
    if not allow_zero and value == "0" * 64:
        raise EngineeringError(label)
    return value


@dataclass(frozen=True)
class CustodiedKeyBinding:
    role: str
    provider: str
    key_id: str
    algorithm: str
    subject_signing_identity: str
    public_key_digest: str
    attestation_digest: str
    hardware_backed: bool
    external_to_engineering: bool


@dataclass(frozen=True)
class KeyCustodyContinuityReceipt:
    repository: str
    source_sha: str
    merge_sha: str
    rotation_epoch: int
    rotation_state: str
    previous_set_digest: str
    revocation_frontier_digest: str
    external_audit_anchor_digest: str
    current_keys: tuple[CustodiedKeyBinding, ...]
    retiring_keys: tuple[CustodiedKeyBinding, ...]
    dual_window_expires_unix_ns: int
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


def _canonical_keys(
    values: Iterable[CustodiedKeyBinding],
    *,
    required_roles: tuple[str, ...],
    label: str,
) -> tuple[CustodiedKeyBinding, ...]:
    rows = bounded_tuple(values, MAX_CUSTODY_KEYS, label)
    if not rows or len(rows) > MAX_CUSTODY_KEYS:
        raise EngineeringError(label)
    if any(not isinstance(row, CustodiedKeyBinding) for row in rows):
        raise EngineeringError(label)

    by_role: dict[str, CustodiedKeyBinding] = {}
    key_handles: set[tuple[str, str]] = set()
    identities: set[str] = set()
    public_keys: set[str] = set()
    for row in rows:
        role = _identity(row.role, "key_custody_role")
        provider = _identity(row.provider, "key_custody_provider")
        key_id = _identity(row.key_id, "key_custody_key_id")
        algorithm = _identity(row.algorithm, "key_custody_algorithm")
        subject = _identity(
            row.subject_signing_identity,
            "key_custody_subject_identity",
        )
        if algorithm not in _ALLOWED_ALGORITHMS:
            raise EngineeringError("key_custody_algorithm")
        _sha256(row.public_key_digest, "key_custody_public_key_digest")
        _sha256(row.attestation_digest, "key_custody_attestation_digest")
        if row.hardware_backed is not True or row.external_to_engineering is not True:
            raise EngineeringError("key_custody_boundary")
        if role in by_role:
            raise EngineeringError("key_custody_duplicate_role")
        handle = (provider, key_id)
        if (
            handle in key_handles
            or subject in identities
            or row.public_key_digest in public_keys
        ):
            raise EngineeringError("key_custody_role_separation")
        by_role[role] = row
        key_handles.add(handle)
        identities.add(subject)
        public_keys.add(row.public_key_digest)

    if set(by_role) != set(required_roles):
        raise EngineeringError("key_custody_required_roles")
    return tuple(by_role[role] for role in sorted(by_role))


def key_set_digest(
    keys: Iterable[CustodiedKeyBinding],
    *,
    rotation_epoch: int,
) -> str:
    if type(rotation_epoch) is not int or rotation_epoch < 1:
        raise EngineeringError("key_custody_rotation_epoch")
    rows = bounded_tuple(keys, MAX_CUSTODY_KEYS, "key_custody_current_keys")
    if not rows or any(not isinstance(row, CustodiedKeyBinding) for row in rows):
        raise EngineeringError("key_custody_current_keys")
    return semantic_digest(
        {
            "rotationEpoch": rotation_epoch,
            "keys": [asdict(row) for row in sorted(rows, key=lambda item: item.role)],
        }
    )


def verify_key_custody_continuity(
    receipt: KeyCustodyContinuityReceipt,
    trust_store: SignatureTrustStore,
    *,
    expected_repository: str,
    expected_source_sha: str,
    expected_merge_sha: str,
    previous_receipt: KeyCustodyContinuityReceipt | None = None,
    required_roles: tuple[str, ...] = DEFAULT_REQUIRED_ROLES,
    now_ns: int | None = None,
) -> str:
    """Verify one externally signed custody epoch and its predecessor chain."""
    if not isinstance(receipt, KeyCustodyContinuityReceipt):
        raise EngineeringError("key_custody_continuity_receipt_required")
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise EngineeringError("invalid_time")
    if (
        not isinstance(required_roles, tuple)
        or not required_roles
        or len(required_roles) > MAX_CUSTODY_KEYS
        or len(set(required_roles)) != len(required_roles)
    ):
        raise EngineeringError("key_custody_required_roles")
    for role in required_roles:
        _identity(role, "key_custody_required_role")

    if receipt.repository != expected_repository:
        raise EngineeringError("key_custody_repository_mismatch")
    _identity(receipt.repository, "key_custody_repository")
    if receipt.source_sha != _sha1(expected_source_sha, "key_custody_source_sha"):
        raise EngineeringError("key_custody_source_mismatch")
    if receipt.merge_sha != _sha1(expected_merge_sha, "key_custody_merge_sha"):
        raise EngineeringError("key_custody_merge_mismatch")
    if type(receipt.rotation_epoch) is not int or receipt.rotation_epoch < 1:
        raise EngineeringError("key_custody_rotation_epoch")
    if receipt.rotation_state not in {"active", "dual_window"}:
        raise EngineeringError("key_custody_rotation_state")
    _sha256(
        receipt.previous_set_digest,
        "key_custody_previous_set_digest",
        allow_zero=receipt.rotation_epoch == 1,
    )
    _sha256(
        receipt.revocation_frontier_digest,
        "key_custody_revocation_frontier_digest",
    )
    _sha256(
        receipt.external_audit_anchor_digest,
        "key_custody_external_audit_anchor_digest",
    )
    if receipt.issuer != "key_custody_authority":
        raise EngineeringError("key_custody_issuer_role")
    _identity(receipt.signing_identity, "key_custody_signing_identity")
    if (
        type(receipt.observed_unix_ns) is not int
        or type(receipt.expires_unix_ns) is not int
        or not receipt.observed_unix_ns <= now < receipt.expires_unix_ns
    ):
        raise EngineeringError("key_custody_continuity_stale")

    current = _canonical_keys(
        receipt.current_keys,
        required_roles=required_roles,
        label="key_custody_current_keys",
    )
    current_identities = {row.subject_signing_identity for row in current}
    if receipt.signing_identity in current_identities:
        raise EngineeringError("key_custody_attestor_collision")

    if receipt.rotation_epoch == 1:
        if receipt.previous_set_digest != "0" * 64 or previous_receipt is not None:
            raise EngineeringError("key_custody_genesis_predecessor")
    else:
        if previous_receipt is None:
            raise EngineeringError("key_custody_previous_receipt_required")
        if previous_receipt.rotation_epoch + 1 != receipt.rotation_epoch:
            raise EngineeringError("key_custody_rotation_epoch_gap")
        previous_digest = semantic_digest(asdict(previous_receipt))
        if receipt.previous_set_digest != previous_digest:
            raise EngineeringError("key_custody_previous_set_mismatch")
        if previous_receipt.repository != receipt.repository:
            raise EngineeringError("key_custody_previous_repository_mismatch")

    retiring = bounded_tuple(
        receipt.retiring_keys, MAX_CUSTODY_KEYS, "key_custody_retiring_keys"
    )
    if receipt.rotation_state == "active":
        if retiring or receipt.dual_window_expires_unix_ns != 0:
            raise EngineeringError("key_custody_active_window_shape")
    else:
        if previous_receipt is None:
            raise EngineeringError("key_custody_dual_window_predecessor")
        retiring = _canonical_keys(
            retiring,
            required_roles=required_roles,
            label="key_custody_retiring_keys",
        )
        previous_current = tuple(
            sorted(previous_receipt.current_keys, key=lambda item: item.role)
        )
        if retiring != previous_current:
            raise EngineeringError("key_custody_retiring_set_mismatch")
        if not (
            receipt.observed_unix_ns
            < receipt.dual_window_expires_unix_ns
            <= receipt.expires_unix_ns
        ):
            raise EngineeringError("key_custody_dual_window")
        current_handles = {(row.provider, row.key_id) for row in current}
        retiring_handles = {(row.provider, row.key_id) for row in retiring}
        current_subjects = {row.subject_signing_identity for row in current}
        retiring_subjects = {row.subject_signing_identity for row in retiring}
        current_public_keys = {row.public_key_digest for row in current}
        retiring_public_keys = {row.public_key_digest for row in retiring}
        if (
            current_handles & retiring_handles
            or current_subjects & retiring_subjects
            or current_public_keys & retiring_public_keys
        ):
            raise EngineeringError("key_custody_rotation_reuse")

    if not trust_store.verify(
        receipt,
        receipt.issuer,
        receipt.signing_identity,
        receipt.signature,
    ):
        raise EngineeringError("key_custody_continuity_signature")
    return semantic_digest(asdict(receipt))
