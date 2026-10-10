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

from dataclasses import asdict, dataclass
import re

from .control_plane import semantic_digest

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
    authority_delta: bool = False
    source_product_receipt_digest: str = ""
    merge_product_receipt_digest: str = ""
    orchestration_product_receipt_digest: str = ""
    sandbox_controller_verified: bool = False
    sandbox_controller_receipt_digest: str = ""
    generated_test_mutation_gate_verified: bool = False
    generated_test_mutation_receipt_digest: str = ""
    distributed_fencing_verified: bool = False
    distributed_fencing_receipt_digest: str = ""
    external_audit_anchor_verified: bool = False
    external_audit_anchor_receipt_digest: str = ""


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
    key custody, a real strong-sandbox observation, distributed fencing, an
    externally retained audit anchor, an observed target deployment, and a
    rollback rehearsal.  Neither result is authority.
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
    source_product_valid = _valid_sha256(facts.source_product_receipt_digest)
    merge_product_valid = _valid_sha256(facts.merge_product_receipt_digest)
    if not source_product_valid:
        implementation.append("source_product_receipt_invalid")
    if not merge_product_valid:
        implementation.append("merge_product_receipt_invalid")
    if not _valid_sha256(facts.orchestration_product_receipt_digest):
        implementation.append("orchestration_product_receipt_invalid")
    elif source_product_valid and merge_product_valid:
        expected_product_set_digest = semantic_digest(
            {
                "sourceHead": facts.source_product_receipt_digest,
                "baseMerge": facts.merge_product_receipt_digest,
            }
        )
        if facts.orchestration_product_receipt_digest != expected_product_set_digest:
            implementation.append("orchestration_product_receipt_set_mismatch")
    if facts.sandbox_controller_verified is not True:
        implementation.append("sandbox_controller_not_verified")
    if not _valid_sha256(facts.sandbox_controller_receipt_digest):
        implementation.append("sandbox_controller_receipt_invalid")
    if facts.generated_test_mutation_gate_verified is not True:
        implementation.append("generated_test_mutation_gate_not_verified")
    if not _valid_sha256(facts.generated_test_mutation_receipt_digest):
        implementation.append("generated_test_mutation_receipt_invalid")
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
    if facts.distributed_fencing_verified is not True:
        deployment.append("distributed_fencing_not_verified")
    if not _valid_sha256(facts.distributed_fencing_receipt_digest):
        deployment.append("distributed_fencing_receipt_invalid")
    if facts.external_audit_anchor_verified is not True:
        deployment.append("external_audit_anchor_not_verified")
    if not _valid_sha256(facts.external_audit_anchor_receipt_digest):
        deployment.append("external_audit_anchor_receipt_invalid")

    implementation_blockers = tuple(sorted(set(implementation)))
    deployment_blockers = tuple(sorted(set(deployment)))
    return ProductionReadinessDecision(
        production_implementation_ready=not implementation_blockers,
        deployment_readiness_ready=not deployment_blockers,
        implementation_blockers=implementation_blockers,
        deployment_blockers=deployment_blockers,
        evidence_digest=semantic_digest(asdict(facts)),
    )
