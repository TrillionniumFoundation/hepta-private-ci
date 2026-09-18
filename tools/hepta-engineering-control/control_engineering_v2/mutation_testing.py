"""Evaluator-owned mutation testing for engineering candidates.

The baseline must pass the exact check set and every admitted code mutant must be
killed by that same check set.  Candidate oracle paths are already immutable in
candidate.py, so a mutant cannot weaken the tests that judge it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass

from .candidate import Candidate, CandidateEnvelope
from .control_plane import EngineeringError, bounded_tuple, semantic_digest
from .sandbox_control import SandboxCoordinator

MAX_MUTANTS = 32


@dataclass(frozen=True)
class MutationTestingReceipt:
    baseline_candidate_id: str
    baseline_receipt_digest: str
    mutant_candidate_ids: tuple[str, ...]
    killed_mutant_ids: tuple[str, ...]
    surviving_mutant_ids: tuple[str, ...]
    check_set_digest: str
    passed: bool
    runtime_authority: bool = False
    merge_authority: bool = False
    release_authority: bool = False


def run_mutation_testing(
    repository: str,
    envelope: CandidateEnvelope,
    baseline: Candidate,
    mutants: Iterable[Candidate],
    checks: Iterable[Sequence[str]],
    coordinator: SandboxCoordinator,
) -> MutationTestingReceipt:
    mutant_values = bounded_tuple(mutants, MAX_MUTANTS, "mutation_test_limit_exceeded")
    if not mutant_values:
        raise EngineeringError("mutation_test_empty")
    checks_value = tuple(tuple(item) for item in checks)
    if not checks_value:
        raise EngineeringError("invalid_check")

    baseline_result = coordinator.execute(
        repository, envelope, baseline, checks_value
    )
    if baseline_result.receipt.passed is not True:
        raise EngineeringError("mutation_baseline_failed")

    killed: list[str] = []
    surviving: list[str] = []
    seen: set[str] = set()
    for mutant in mutant_values:
        if mutant.candidate_id == baseline.candidate_id:
            raise EngineeringError("mutation_test_baseline_reused")
        if mutant.candidate_id in seen:
            raise EngineeringError("duplicate_mutant_identity")
        seen.add(mutant.candidate_id)
        result = coordinator.execute(repository, envelope, mutant, checks_value)
        if result.receipt.passed:
            surviving.append(mutant.candidate_id)
        else:
            killed.append(mutant.candidate_id)

    return MutationTestingReceipt(
        baseline.candidate_id,
        semantic_digest(asdict(baseline_result.receipt)),
        tuple(item.candidate_id for item in mutant_values),
        tuple(killed),
        tuple(surviving),
        semantic_digest(checks_value),
        not surviving and len(killed) == len(mutant_values),
    )
