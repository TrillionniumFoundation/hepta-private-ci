"""Bounded mutation testing for evaluator-owned test suites."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from .candidate import (
    CandidateEnvelope,
    Mutation,
    generate_candidates,
    sandbox_candidate,
)
from .control_plane import EngineeringError, bounded_tuple, semantic_digest

MAX_MUTATION_PROBES = 31


@dataclass(frozen=True)
class MutationTestingReceipt:
    envelope_id: str
    base_commit: str
    killed_candidates: tuple[str, ...]
    surviving_candidates: tuple[str, ...]
    sandbox_receipt_digests: tuple[str, ...]
    passed: bool
    evidence_digest: str
    runtime_authority: bool = False
    merge_authority: bool = False
    acceptance_authority: bool = False


def run_mutation_testing(
    repository: str | Path,
    envelope: CandidateEnvelope,
    mutations: Iterable[Mutation],
    checks: Iterable[Sequence[str]],
) -> MutationTestingReceipt:
    """Require evaluator-owned checks to kill every admitted source mutant.

    Mutations target product source only; candidate/oracle policy independently
    forbids modifying tests, fixtures, evaluation policy or qualification code.
    A mutant is "killed" only when the sandbox executes the full bound check set
    and returns a non-passing candidate. Infrastructure exceptions fail closed.
    """
    values = bounded_tuple(
        mutations, MAX_MUTATION_PROBES, "mutation_probe_limit_exceeded"
    )
    if not values:
        raise EngineeringError("mutation_probe_required")
    if any(
        not isinstance(value, Mutation) or value.operation == "no_change"
        for value in values
    ):
        raise EngineeringError("invalid_mutation_probe")
    candidates = generate_candidates(envelope, values)
    mutants = tuple(
        candidate for candidate in candidates if candidate.mutation.operation != "no_change"
    )
    if len(mutants) != len(values):
        raise EngineeringError("mutation_probe_deduplicated")

    check_values = tuple(tuple(item for item in check) for check in checks)
    if not check_values:
        raise EngineeringError("invalid_check")
    killed: list[str] = []
    survived: list[str] = []
    receipt_digests: list[str] = []
    for mutant in mutants:
        tested, receipt = sandbox_candidate(
            repository,
            envelope,
            mutant,
            check_values,
        )
        if tested.sandbox_receipt_digest is None:
            raise EngineeringError("mutation_testing_receipt_missing")
        receipt_digests.append(tested.sandbox_receipt_digest)
        if receipt.passed:
            survived.append(mutant.candidate_id)
        else:
            killed.append(mutant.candidate_id)

    body = {
        "envelopeId": envelope.envelope_id,
        "baseCommit": envelope.base_commit,
        "killedCandidates": killed,
        "survivingCandidates": survived,
        "sandboxReceiptDigests": receipt_digests,
    }
    return MutationTestingReceipt(
        envelope.envelope_id,
        envelope.base_commit,
        tuple(killed),
        tuple(survived),
        tuple(receipt_digests),
        not survived and len(killed) == len(mutants),
        semantic_digest(body),
    )
