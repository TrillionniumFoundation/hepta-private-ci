"""Fail-closed production-readiness projection for control.engineering.

This module consumes facts that have already been authenticated by the evidence,
seal, CI, reviewer, deployment, and key-custody boundaries.  It deliberately
does not verify external signatures itself and cannot grant merge, deployment,
promotion, release, runtime, or acceptance authority.

Its purpose is narrower: make the repository's `production_implementation`
claim rule executable instead of allowing source presence or fixture success to
be mistaken for production composition.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import re
from typing import Iterable, Mapping

from .control_plane import EngineeringStore, semantic_digest
from .external import (
    AuditAnchorReceipt,
    ExternalFactReceipt,
    KeyCustodyReceipt,
    ReceiptVerifier,
    verify_external_fact_receipts,
    verify_key_custody_set,
    verify_store_audit_anchor,
)

_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _valid_sha1(value: object) -> bool:
    return (
        isinstance(value, str)
        and value != "0" * 40
        and _SHA1.fullmatch(value) is not None
    )


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and value != "0" * 64
        and _SHA256.fullmatch(value) is not None
    )


def _valid_identity(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 256
        and value == value.strip()
        and "\x00" not in value
    )


@dataclass(frozen=True)
class ProductionReadinessFacts:
    repository_full_name: str
    expected_repository_full_name: str
    source_commit: str
    source_tree: str
    source_receipt_digest: str
    candidate_evidence_verified: bool
    native_symbol_mapping_verified: bool
    native_symbol_mapping_digest: str
    product_caller: str
    product_test_receipt_digest: str
    exact_source_ci_passed: bool
    synthetic_merge_ci_passed: bool
    product_tests_passed: bool
    generator_identity: str
    reviewer_identity: str
    independent_review_accepted: bool
    review_receipt_digest: str
    authorized_handoff: bool
    handoff_receipt_digest: str
    external_key_custody: bool
    key_custody_receipt_digest: str
    strong_sandbox_observed: bool
    strong_sandbox_receipt_digest: str
    deployment_target_digest: str
    deployment_observed: bool
    deployment_receipt_digest: str
    rollback_rehearsed: bool
    rollback_receipt_digest: str
    external_audit_anchor: bool = False
    audit_anchor_receipt_digest: str = ""
    distributed_mode: bool = False
    distributed_fencing_verified: bool = False
    distributed_fencing_receipt_digest: str = ""
    authority_delta: bool = False


@dataclass(frozen=True)
class ProductionReadinessDecision:
    production_implementation_ready: bool
    deployment_readiness_ready: bool
    implementation_blockers: tuple[str, ...]
    deployment_blockers: tuple[str, ...]
    evidence_digest: str
    runtime_authority: bool = False
    merge_authority: bool = False
    activation_authority: bool = False
    promotion_authority: bool = False
    release_authority: bool = False


def evaluate_production_readiness(
    facts: ProductionReadinessFacts,
) -> ProductionReadinessDecision:
    """Project already-verified facts into repository and deployment readiness.

    `production_implementation_ready` matches the canonical status-model rule:
    exact source identity, native mapping, a named product caller, executable
    product tests, and exact-source plus synthetic-merge qualification.

    `deployment_readiness_ready` is intentionally stricter.  It additionally
    requires identity-separated independent review, authorized handoff, external
    key custody, a real strong-sandbox observation, an observed target deployment,
    and a rollback rehearsal.  Neither result is authority.
    """
    if not isinstance(facts, ProductionReadinessFacts):
        raise TypeError("ProductionReadinessFacts required")

    implementation: list[str] = []

    if facts.repository_full_name != facts.expected_repository_full_name:
        implementation.append("repository_mismatch")
    if not _valid_identity(facts.repository_full_name) or not _valid_identity(
        facts.expected_repository_full_name
    ):
        implementation.append("repository_identity_invalid")
    if not _valid_sha1(facts.source_commit):
        implementation.append("source_commit_invalid")
    if not _valid_sha1(facts.source_tree):
        implementation.append("source_tree_invalid")
    if not _valid_sha256(facts.source_receipt_digest):
        implementation.append("source_receipt_invalid")
    if facts.candidate_evidence_verified is not True:
        implementation.append("candidate_evidence_not_verified")
    if facts.native_symbol_mapping_verified is not True:
        implementation.append("native_symbol_mapping_not_verified")
    if not _valid_sha256(facts.native_symbol_mapping_digest):
        implementation.append("native_symbol_mapping_receipt_invalid")
    if not _valid_identity(facts.product_caller):
        implementation.append("product_caller_missing")
    if not _valid_sha256(facts.product_test_receipt_digest):
        implementation.append("product_test_receipt_invalid")
    if facts.exact_source_ci_passed is not True:
        implementation.append("exact_source_ci_not_passed")
    if facts.synthetic_merge_ci_passed is not True:
        implementation.append("synthetic_merge_ci_not_passed")
    if facts.product_tests_passed is not True:
        implementation.append("product_tests_not_passed")
    if facts.authority_delta is not False:
        implementation.append("authority_delta")

    deployment = list(implementation)

    if not _valid_identity(facts.generator_identity):
        deployment.append("generator_identity_missing")
    if not _valid_identity(facts.reviewer_identity):
        deployment.append("reviewer_identity_missing")
    elif facts.reviewer_identity == facts.generator_identity:
        deployment.append("reviewer_identity_collision")
    if facts.independent_review_accepted is not True:
        deployment.append("independent_review_not_accepted")
    if not _valid_sha256(facts.review_receipt_digest):
        deployment.append("review_receipt_invalid")
    if facts.authorized_handoff is not True:
        deployment.append("authorized_handoff_missing")
    if not _valid_sha256(facts.handoff_receipt_digest):
        deployment.append("handoff_receipt_invalid")
    if facts.external_key_custody is not True:
        deployment.append("external_key_custody_missing")
    if not _valid_sha256(facts.key_custody_receipt_digest):
        deployment.append("key_custody_receipt_invalid")
    if facts.strong_sandbox_observed is not True:
        deployment.append("strong_sandbox_not_observed")
    if not _valid_sha256(facts.strong_sandbox_receipt_digest):
        deployment.append("strong_sandbox_receipt_invalid")
    if not _valid_sha256(facts.deployment_target_digest):
        deployment.append("deployment_target_invalid")
    if facts.deployment_observed is not True:
        deployment.append("deployment_not_observed")
    if not _valid_sha256(facts.deployment_receipt_digest):
        deployment.append("deployment_receipt_invalid")
    if facts.rollback_rehearsed is not True:
        deployment.append("rollback_not_rehearsed")
    if not _valid_sha256(facts.rollback_receipt_digest):
        deployment.append("rollback_receipt_invalid")
    if facts.external_audit_anchor is not True:
        deployment.append("external_audit_anchor_missing")
    if not _valid_sha256(facts.audit_anchor_receipt_digest):
        deployment.append("audit_anchor_receipt_invalid")
    if facts.distributed_mode:
        if facts.distributed_fencing_verified is not True:
            deployment.append("distributed_fencing_not_verified")
        if not _valid_sha256(facts.distributed_fencing_receipt_digest):
            deployment.append("distributed_fencing_receipt_invalid")

    implementation_blockers = tuple(sorted(set(implementation)))
    deployment_blockers = tuple(sorted(set(deployment)))
    return ProductionReadinessDecision(
        production_implementation_ready=not implementation_blockers,
        deployment_readiness_ready=not deployment_blockers,
        implementation_blockers=implementation_blockers,
        deployment_blockers=deployment_blockers,
        evidence_digest=semantic_digest(asdict(facts)),
    )



def evaluate_authenticated_production_readiness(
    facts: ProductionReadinessFacts,
    *,
    subject_digest: str,
    external_fact_receipts: Iterable[ExternalFactReceipt],
    audit_anchor: AuditAnchorReceipt,
    key_custody_receipts: Iterable[KeyCustodyReceipt],
    required_role_keys: Mapping[str, str],
    verifier: ReceiptVerifier,
    store: EngineeringStore,
    store_identity_digest: str,
    now_ns: int | None = None,
) -> ProductionReadinessDecision:
    """Verify external facts before projecting deployment readiness.

    Caller-provided booleans are ignored for external acceptance/deployment facts.
    A production-ready result therefore requires authenticated receipts from
    independent review, handoff, sandbox, deployment, rollback, audit anchoring
    and (when distributed_mode is true) distributed fencing authorities.
    """
    if not isinstance(facts, ProductionReadinessFacts):
        raise TypeError("ProductionReadinessFacts required")
    fact_digests = verify_external_fact_receipts(
        external_fact_receipts,
        verifier,
        subject_digest=subject_digest,
        now_ns=now_ns,
    )
    audit_digest = verify_store_audit_anchor(
        store,
        audit_anchor,
        verifier,
        store_identity_digest=store_identity_digest,
        now_ns=now_ns,
    )
    required_roles = {"source_authority", "engineering_evidence_binder"}
    if set(required_role_keys) != required_roles:
        raise ValueError("exact source/evidence key identities required")
    custody_digest = verify_key_custody_set(
        key_custody_receipts,
        verifier,
        required_role_keys=required_role_keys,
        now_ns=now_ns,
    )
    distributed_digest = fact_digests.get("distributed_fencing_verified", "")
    verified = replace(
        facts,
        independent_review_accepted="independent_review_accepted" in fact_digests,
        review_receipt_digest=fact_digests.get("independent_review_accepted", ""),
        authorized_handoff="authorized_handoff" in fact_digests,
        handoff_receipt_digest=fact_digests.get("authorized_handoff", ""),
        external_key_custody=True,
        key_custody_receipt_digest=custody_digest,
        strong_sandbox_observed="strong_sandbox_observed" in fact_digests,
        strong_sandbox_receipt_digest=fact_digests.get("strong_sandbox_observed", ""),
        deployment_observed="deployment_observed" in fact_digests,
        deployment_receipt_digest=fact_digests.get("deployment_observed", ""),
        rollback_rehearsed="rollback_rehearsed" in fact_digests,
        rollback_receipt_digest=fact_digests.get("rollback_rehearsed", ""),
        external_audit_anchor=True,
        audit_anchor_receipt_digest=audit_digest,
        distributed_fencing_verified=(
            "distributed_fencing_verified" in fact_digests
            if facts.distributed_mode
            else False
        ),
        distributed_fencing_receipt_digest=distributed_digest,
    )
    return evaluate_production_readiness(verified)
