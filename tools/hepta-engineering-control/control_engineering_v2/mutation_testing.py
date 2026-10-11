"""Evaluator-owned mutation testing for engineering candidates.

The baseline must pass the exact evaluator-owned check set in a strong sandbox.
Every admitted code mutant must be executed under the same sandbox policy and
check-set digest and must be killed by that check set. Candidate oracle paths are
immutable in candidate.py, so a mutant cannot weaken the tests that judge it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass

from .candidate import Candidate, CandidateEnvelope
from .control_plane import (
    EngineeringError,
    bounded_tuple,
    checked_sha256,
    semantic_digest,
)
from .sandbox_control import SandboxCoordinator, SandboxExecutionResult

MAX_MUTANTS = 32
_STRONG_ADAPTER = "bubblewrap-unshare-all-ro-workspace-v2"


@dataclass(frozen=True)
class MutationTestingReceipt:
    baseline_candidate_id: str
    baseline_receipt_digest: str
    baseline_attempts: int
    mutant_candidate_ids: tuple[str, ...]
    mutant_execution_receipts: tuple[tuple[str, str, int], ...]
    killed_mutant_ids: tuple[str, ...]
    surviving_mutant_ids: tuple[str, ...]
    check_set_digest: str
    sandbox_policy_digest: str
    passed: bool
    runtime_authority: bool = False
    merge_authority: bool = False
    release_authority: bool = False


def _verify_execution(
    candidate: Candidate,
    result: SandboxExecutionResult,
    expected_check_digest: str,
) -> str:
    if not isinstance(result, SandboxExecutionResult):
        raise EngineeringError("mutation_execution_result")
    receipt = result.receipt
    tested = result.candidate
    if (
        tested.candidate_id != candidate.candidate_id
        or tested.envelope_id != candidate.envelope_id
        or tested.base_commit != candidate.base_commit
        or tested.semantic_digest != candidate.semantic_digest
        or tested.changed_paths != candidate.changed_paths
        or receipt.candidate_id != candidate.candidate_id
        or receipt.base_commit != candidate.base_commit
    ):
        raise EngineeringError("mutation_execution_binding")
    if receipt.check_set_digest != expected_check_digest:
        raise EngineeringError("mutation_check_set_mismatch")
    if (
        receipt.filesystem_isolated is not True
        or receipt.network_isolated is not True
        or receipt.isolation_adapter != _STRONG_ADAPTER
        or receipt.credential_environment_count != 0
        or not receipt.check_results
    ):
        raise EngineeringError("mutation_strong_sandbox_required")
    if (
        receipt.candidate_state_digest_before
        != receipt.candidate_state_digest_after
        or receipt.source_worktree_digest_before
        != receipt.source_worktree_digest_after
    ):
        raise EngineeringError("mutation_execution_drift")
    for value, label in (
        (receipt.check_set_digest, "mutation_check_set_digest"),
        (receipt.candidate_state_digest_before, "mutation_candidate_state_digest"),
        (receipt.source_worktree_digest_before, "mutation_source_state_digest"),
        (result.policy_digest, "mutation_sandbox_policy_digest"),
    ):
        checked_sha256(value, label)
        if value == "0" * 64:
            raise EngineeringError("mutation_execution_digest")
    if (
        type(result.attempts) is not int
        or not 1 <= result.attempts <= 3
    ):
        raise EngineeringError("mutation_execution_attempts")
    receipt_digest = semantic_digest(asdict(receipt))
    if tested.sandbox_receipt_digest != receipt_digest:
        raise EngineeringError("mutation_execution_receipt_binding")
    if receipt.passed is True:
        if (
            tested.state != "sandbox_tested"
            or any(type(code) is not int or code != 0 for _, code in receipt.check_results)
        ):
            raise EngineeringError("mutation_execution_state")
    else:
        if tested.state != "rejected" or all(
            type(code) is int and code == 0 for _, code in receipt.check_results
        ):
            raise EngineeringError("mutation_execution_state")
    return receipt_digest


def run_mutation_testing(
    repository: str,
    envelope: CandidateEnvelope,
    baseline: Candidate,
    mutants: Iterable[Candidate],
    checks: Iterable[Sequence[str]],
    coordinator: SandboxCoordinator,
) -> MutationTestingReceipt:
    mutant_values = bounded_tuple(
        mutants,
        MAX_MUTANTS,
        "mutation_test_limit_exceeded",
    )
    if not mutant_values:
        raise EngineeringError("mutation_test_empty")
    checks_value = tuple(tuple(item) for item in checks)
    if not checks_value:
        raise EngineeringError("invalid_check")
    check_set_digest = semantic_digest(checks_value)

    if (
        baseline.envelope_id != envelope.envelope_id
        or baseline.base_commit != envelope.base_commit
        or baseline.state != "no_change"
        or baseline.changed_paths
        or getattr(baseline.mutation, "operation", None) != "no_change"
    ):
        raise EngineeringError("mutation_baseline_invalid")

    baseline_result = coordinator.execute(
        repository,
        envelope,
        baseline,
        checks_value,
    )
    baseline_receipt_digest = _verify_execution(
        baseline,
        baseline_result,
        check_set_digest,
    )
    if baseline_result.receipt.passed is not True:
        raise EngineeringError("mutation_baseline_failed")
    policy_digest = baseline_result.policy_digest

    killed: list[str] = []
    surviving: list[str] = []
    execution_receipts: list[tuple[str, str, int]] = []
    seen: set[str] = set()
    for mutant in mutant_values:
        if not isinstance(mutant, Candidate):
            raise EngineeringError("invalid_mutant")
        if mutant.candidate_id == baseline.candidate_id:
            raise EngineeringError("mutation_test_baseline_reused")
        if mutant.candidate_id in seen:
            raise EngineeringError("duplicate_mutant_identity")
        if (
            mutant.envelope_id != envelope.envelope_id
            or mutant.base_commit != envelope.base_commit
            or mutant.state != "drafted"
            or not mutant.changed_paths
            or getattr(mutant.mutation, "operation", None) == "no_change"
        ):
            raise EngineeringError("invalid_mutant")
        seen.add(mutant.candidate_id)

        result = coordinator.execute(
            repository,
            envelope,
            mutant,
            checks_value,
        )
        receipt_digest = _verify_execution(
            mutant,
            result,
            check_set_digest,
        )
        if result.policy_digest != policy_digest:
            raise EngineeringError("mutation_execution_policy_mismatch")
        execution_receipts.append(
            (mutant.candidate_id, receipt_digest, result.attempts)
        )
        if result.receipt.passed:
            surviving.append(mutant.candidate_id)
        else:
            killed.append(mutant.candidate_id)

    return MutationTestingReceipt(
        baseline_candidate_id=baseline.candidate_id,
        baseline_receipt_digest=baseline_receipt_digest,
        baseline_attempts=baseline_result.attempts,
        mutant_candidate_ids=tuple(item.candidate_id for item in mutant_values),
        mutant_execution_receipts=tuple(execution_receipts),
        killed_mutant_ids=tuple(killed),
        surviving_mutant_ids=tuple(surviving),
        check_set_digest=check_set_digest,
        sandbox_policy_digest=policy_digest,
        passed=not surviving and len(killed) == len(mutant_values),
    )
