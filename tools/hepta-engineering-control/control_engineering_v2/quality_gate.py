"""Fail-closed quality evidence for ``control.engineering``.

The gate consumes retained reports produced by independent CI commands. It does
not infer coverage, typing, lint, API compatibility, mutation score, or soak
success from a process exit code alone, and it never grants merge or release
authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re

from .clock_policy import ClockSkewPolicy, validate_receipt_window
from .control_plane import EngineeringError, checked_id, checked_sha256, semantic_digest
from .evidence import SignatureTrustStore

_SHA1 = re.compile(r"[0-9a-f]{40}\Z")


def _git_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA1.fullmatch(value) is None:
        raise EngineeringError("invalid_" + label)
    return value


@dataclass(frozen=True)
class QualityGatePolicy:
    minimum_line_coverage_q16: int = 58_982
    minimum_branch_coverage_q16: int = 52_429
    minimum_mutation_score_q16: int = 55_706
    minimum_test_count: int = 1
    minimum_soak_iterations: int = 25

    def __post_init__(self) -> None:
        ratios = (
            self.minimum_line_coverage_q16,
            self.minimum_branch_coverage_q16,
            self.minimum_mutation_score_q16,
        )
        if any(type(value) is not int or not 0 <= value <= 65_536 for value in ratios):
            raise EngineeringError("invalid_quality_gate_policy")
        if (
            type(self.minimum_test_count) is not int
            or self.minimum_test_count < 1
            or type(self.minimum_soak_iterations) is not int
            or self.minimum_soak_iterations < 1
        ):
            raise EngineeringError("invalid_quality_gate_policy")


@dataclass(frozen=True)
class QualityGateReceipt:
    repository: str
    source_commit: str
    source_tree: str
    test_count: int
    line_coverage_q16: int
    branch_coverage_q16: int
    mutation_score_q16: int
    soak_iterations: int
    unit_test_report_digest: str
    coverage_report_digest: str
    type_check_report_digest: str
    lint_report_digest: str
    api_compatibility_report_digest: str
    mutation_report_digest: str
    soak_report_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class QualityGateDecision:
    qualified: bool
    blockers: tuple[str, ...]
    receipt_digest: str
    runtime_authority: bool = False
    merge_authority: bool = False
    release_authority: bool = False


def verify_quality_gate(
    receipt: QualityGateReceipt,
    trust_store: SignatureTrustStore,
    *,
    expected_repository: str,
    expected_source_commit: str,
    expected_source_tree: str,
    policy: QualityGatePolicy = QualityGatePolicy(),
    clock_policy: ClockSkewPolicy = ClockSkewPolicy(),
    now_ns: int,
) -> QualityGateDecision:
    if not isinstance(receipt, QualityGateReceipt):
        raise EngineeringError("quality_gate_receipt_required")
    if not isinstance(policy, QualityGatePolicy):
        raise EngineeringError("quality_gate_policy_required")
    checked_id(receipt.repository, "quality_repository")
    checked_id(expected_repository, "expected_quality_repository")
    _git_sha(receipt.source_commit, "quality_source_commit")
    _git_sha(receipt.source_tree, "quality_source_tree")
    _git_sha(expected_source_commit, "expected_quality_source_commit")
    _git_sha(expected_source_tree, "expected_quality_source_tree")
    checked_id(receipt.issuer, "quality_issuer")
    checked_id(receipt.signing_identity, "quality_signing_identity")
    if receipt.issuer != "ci_executor":
        raise EngineeringError("quality_gate_issuer_role")
    validate_receipt_window(
        receipt.observed_unix_ns,
        receipt.expires_unix_ns,
        now_ns=now_ns,
        policy=clock_policy,
    )
    for value, label in (
        (receipt.unit_test_report_digest, "unit_test_report_digest"),
        (receipt.coverage_report_digest, "coverage_report_digest"),
        (receipt.type_check_report_digest, "type_check_report_digest"),
        (receipt.lint_report_digest, "lint_report_digest"),
        (receipt.api_compatibility_report_digest, "api_compatibility_report_digest"),
        (receipt.mutation_report_digest, "mutation_report_digest"),
        (receipt.soak_report_digest, "soak_report_digest"),
    ):
        checked_sha256(value, label)
        if value == "0" * 64:
            raise EngineeringError("quality_gate_empty_report_digest")
    if not trust_store.verify(
        receipt,
        receipt.issuer,
        receipt.signing_identity,
        receipt.signature,
    ):
        raise EngineeringError("quality_gate_signature")

    blockers: list[str] = []
    if receipt.repository != expected_repository:
        blockers.append("quality_repository_mismatch")
    if receipt.source_commit != expected_source_commit:
        blockers.append("quality_source_commit_mismatch")
    if receipt.source_tree != expected_source_tree:
        blockers.append("quality_source_tree_mismatch")
    for name, value, minimum in (
        ("line_coverage", receipt.line_coverage_q16, policy.minimum_line_coverage_q16),
        ("branch_coverage", receipt.branch_coverage_q16, policy.minimum_branch_coverage_q16),
        ("mutation_score", receipt.mutation_score_q16, policy.minimum_mutation_score_q16),
    ):
        if type(value) is not int or not 0 <= value <= 65_536:
            raise EngineeringError("quality_gate_ratio_invalid")
        if value < minimum:
            blockers.append(name + "_below_threshold")
    if type(receipt.test_count) is not int or receipt.test_count < policy.minimum_test_count:
        blockers.append("test_count_below_threshold")
    if (
        type(receipt.soak_iterations) is not int
        or receipt.soak_iterations < policy.minimum_soak_iterations
    ):
        blockers.append("soak_iterations_below_threshold")
    return QualityGateDecision(
        not blockers,
        tuple(sorted(set(blockers))),
        semantic_digest(asdict(receipt)),
    )
