from dataclasses import asdict, replace
import unittest
from unittest import mock

from control_engineering_v2 import Candidate, CandidateEnvelope, Mutation
from control_engineering_v2.candidate import SandboxReceipt
from control_engineering_v2.control_plane import semantic_digest
from control_engineering_v2.mutation_testing import run_mutation_testing
from control_engineering_v2.sandbox_control import SandboxExecutionResult

CHECKS = (("python3", "-m", "pytest"),)


def candidate(identity: str, operation: str = "no_change") -> Candidate:
    mutation = Mutation(
        operation,
        "src/a.py" if operation != "no_change" else "",
        expected_text="x" if operation == "replace_text" else "",
        replacement_text="y" if operation == "replace_text" else "",
    )
    return Candidate(
        identity,
        "env",
        "a" * 40,
        mutation,
        "d" * 64,
        "no_change" if operation == "no_change" else "drafted",
        () if operation == "no_change" else ("src/a.py",),
        None,
    )


def result(
    value: Candidate,
    passed: bool,
    *,
    checks=CHECKS,
    policy_digest: str = "5" * 64,
    attempts: int = 1,
) -> SandboxExecutionResult:
    receipt = SandboxReceipt(
        value.candidate_id,
        value.base_commit,
        "b" * 40,
        "b" * 40,
        (("check", 0 if passed else 1),),
        0,
        True,
        1,
        passed,
        False,
        True,
        "bubblewrap-unshare-all-ro-workspace-v2",
        semantic_digest(checks),
        "2" * 64,
        "2" * 64,
        "3" * 64,
        "3" * 64,
    )
    receipt_digest = semantic_digest(asdict(receipt))
    tested = Candidate(
        value.candidate_id,
        value.envelope_id,
        value.base_commit,
        value.mutation,
        value.semantic_digest,
        "sandbox_tested" if passed else "rejected",
        value.changed_paths,
        receipt_digest,
    )
    return SandboxExecutionResult(
        tested,
        receipt,
        attempts,
        policy_digest,
    )


class MutationTestingTests(unittest.TestCase):
    def test_baseline_passes_and_all_mutants_must_be_killed(self):
        baseline = candidate("baseline")
        mutants = (
            candidate("mutant-a", "replace_text"),
            candidate("mutant-b", "replace_text"),
        )
        coordinator = mock.Mock()
        coordinator.execute.side_effect = (
            result(baseline, True),
            result(mutants[0], False),
            result(mutants[1], False),
        )
        receipt = run_mutation_testing(
            "/repo",
            CandidateEnvelope("env", "a" * 40, ("src",)),
            baseline,
            mutants,
            CHECKS,
            coordinator,
        )
        self.assertTrue(receipt.passed)
        self.assertEqual(receipt.surviving_mutant_ids, ())
        self.assertEqual(receipt.killed_mutant_ids, ("mutant-a", "mutant-b"))
        self.assertEqual(receipt.check_set_digest, semantic_digest(CHECKS))
        self.assertEqual(receipt.sandbox_policy_digest, "5" * 64)
        self.assertEqual(
            tuple(row[0] for row in receipt.mutant_execution_receipts),
            ("mutant-a", "mutant-b"),
        )
        self.assertTrue(
            all(len(row[1]) == 64 for row in receipt.mutant_execution_receipts)
        )

    def test_surviving_mutant_fails_gate(self):
        baseline = candidate("baseline")
        mutant = candidate("mutant", "replace_text")
        coordinator = mock.Mock()
        coordinator.execute.side_effect = (
            result(baseline, True),
            result(mutant, True),
        )
        receipt = run_mutation_testing(
            "/repo",
            CandidateEnvelope("env", "a" * 40, ("src",)),
            baseline,
            (mutant,),
            CHECKS,
            coordinator,
        )
        self.assertFalse(receipt.passed)
        self.assertEqual(receipt.surviving_mutant_ids, ("mutant",))

    def test_baseline_must_be_exact_no_change_candidate(self):
        bad_baseline = candidate("baseline", "replace_text")
        coordinator = mock.Mock()
        with self.assertRaisesRegex(ValueError, "mutation_baseline_invalid"):
            run_mutation_testing(
                "/repo",
                CandidateEnvelope("env", "a" * 40, ("src",)),
                bad_baseline,
                (candidate("mutant", "replace_text"),),
                CHECKS,
                coordinator,
            )
        coordinator.execute.assert_not_called()

    def test_weak_or_mismatched_sandbox_evidence_fails_closed(self):
        baseline = candidate("baseline")
        mutant = candidate("mutant", "replace_text")
        weak = result(baseline, True)
        weak_receipt = replace(weak.receipt, network_isolated=False)
        weak = replace(
            weak,
            receipt=weak_receipt,
            candidate=replace(
                weak.candidate,
                sandbox_receipt_digest=semantic_digest(asdict(weak_receipt)),
            ),
        )
        coordinator = mock.Mock()
        coordinator.execute.side_effect = (weak,)
        with self.assertRaisesRegex(ValueError, "mutation_strong_sandbox_required"):
            run_mutation_testing(
                "/repo",
                CandidateEnvelope("env", "a" * 40, ("src",)),
                baseline,
                (mutant,),
                CHECKS,
                coordinator,
            )

    def test_mutants_must_use_same_coordinator_policy(self):
        baseline = candidate("baseline")
        mutant = candidate("mutant", "replace_text")
        coordinator = mock.Mock()
        coordinator.execute.side_effect = (
            result(baseline, True, policy_digest="5" * 64),
            result(mutant, False, policy_digest="6" * 64),
        )
        with self.assertRaisesRegex(ValueError, "mutation_execution_policy_mismatch"):
            run_mutation_testing(
                "/repo",
                CandidateEnvelope("env", "a" * 40, ("src",)),
                baseline,
                (mutant,),
                CHECKS,
                coordinator,
            )


if __name__ == "__main__":
    unittest.main()
