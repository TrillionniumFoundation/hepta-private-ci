import unittest
from unittest import mock

from control_engineering_v2 import Candidate, CandidateEnvelope, Mutation
from control_engineering_v2.candidate import SandboxReceipt
from control_engineering_v2.mutation_testing import run_mutation_testing
from control_engineering_v2.sandbox_control import SandboxExecutionResult


def candidate(identity: str, operation: str = "no_change") -> Candidate:
    mutation = Mutation(operation, "src/a.py" if operation != "no_change" else "", expected_text="x" if operation == "replace_text" else "", replacement_text="y" if operation == "replace_text" else "")
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


def result(value: Candidate, passed: bool) -> SandboxExecutionResult:
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
        "1" * 64,
        "2" * 64,
        "2" * 64,
        "3" * 64,
        "3" * 64,
    )
    tested = Candidate(
        value.candidate_id,
        value.envelope_id,
        value.base_commit,
        value.mutation,
        value.semantic_digest,
        "sandbox_tested" if passed else "rejected",
        value.changed_paths,
        "4" * 64,
    )
    return SandboxExecutionResult(tested, receipt, 1, "5" * 64)


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
            (("python3", "-m", "pytest"),),
            coordinator,
        )
        self.assertTrue(receipt.passed)
        self.assertEqual(receipt.surviving_mutant_ids, ())
        self.assertEqual(receipt.killed_mutant_ids, ("mutant-a", "mutant-b"))

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
            (("python3", "-m", "pytest"),),
            coordinator,
        )
        self.assertFalse(receipt.passed)
        self.assertEqual(receipt.surviving_mutant_ids, ("mutant",))


if __name__ == "__main__":
    unittest.main()
