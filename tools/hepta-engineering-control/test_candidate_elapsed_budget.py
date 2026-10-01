"""One elapsed envelope covers source admission, execution and receipt formation."""

from dataclasses import replace
import sys
import unittest
from unittest.mock import patch

from control_engineering_v2 import candidate, EngineeringError
from control_engineering_v2.facade import execute_candidate_sandbox
import test_candidate_sandbox_hardening as fixtures


class CandidateElapsedBudgetTests(unittest.TestCase):
    setUp = fixtures.CandidateSandboxFixture.setUp
    tearDown = fixtures.CandidateSandboxFixture.tearDown
    _git = fixtures.CandidateSandboxFixture._git

    def inputs(self):
        envelope = replace(fixtures.CandidateSandboxFixture.envelope(self), wall_time_seconds=1)
        value = candidate.generate_candidates(envelope, ())[0]
        return envelope, value

    def execute(self, envelope, value):
        return execute_candidate_sandbox(
            self.root, envelope, value, ((sys.executable, "-I", "-c", "pass"),)
        )

    def test_source_admission_consumes_one_decreasing_git_budget(self):
        envelope, value = self.inputs()
        now = [0]
        timeouts = []
        reader = candidate.run_git_bytes

        def elapsed_read(*args, **kwargs):
            timeouts.append(kwargs["timeout_seconds"])
            result = reader(*args, **kwargs)
            now[0] += 250_000_000
            return result

        with (
            patch.object(candidate.time, "monotonic_ns", side_effect=lambda: now[0]),
            patch.object(candidate, "run_git_bytes", side_effect=elapsed_read),
            patch.object(candidate, "_materialize_exact_tree") as materialize,
            patch.object(candidate, "_run_bounded") as run,
        ):
            with self.assertRaisesRegex(EngineeringError, "sandbox_time_budget_exceeded"):
                self.execute(envelope, value)
        self.assertEqual(timeouts, [1.0, 0.75, 0.5, 0.25])
        materialize.assert_not_called()
        run.assert_not_called()

    def test_successful_check_cannot_outlive_final_source_verification(self):
        envelope, value = self.inputs()
        now = [0]
        reader = candidate._git
        tree_reads = [0]

        def final_source_elapsed(root, *args, **kwargs):
            result = reader(root, *args, **kwargs)
            if args == ("rev-parse", f"{self.base_commit}^{{tree}}"):
                tree_reads[0] += 1
                if tree_reads[0] == 2:
                    now[0] = 1_100_000_000
            return result

        with (
            patch.object(candidate.time, "monotonic_ns", side_effect=lambda: now[0]),
            patch.object(candidate, "_git", side_effect=final_source_elapsed),
        ):
            with self.assertRaisesRegex(EngineeringError, "sandbox_time_budget_exceeded"):
                self.execute(envelope, value)
        self.assertEqual(tree_reads[0], 2)

    def test_receipt_digest_formation_is_inside_elapsed_boundary(self):
        envelope, value = self.inputs()
        now = [0]
        digest = candidate.semantic_digest

        def receipt_elapsed(item):
            result = digest(item)
            if isinstance(item, dict) and "duration_millis" in item:
                now[0] = 1_100_000_000
            return result

        with (
            patch.object(candidate.time, "monotonic_ns", side_effect=lambda: now[0]),
            patch.object(candidate, "semantic_digest", side_effect=receipt_elapsed),
        ):
            with self.assertRaisesRegex(EngineeringError, "sandbox_time_budget_exceeded"):
                self.execute(envelope, value)

    def test_real_temporary_directory_cleanup_is_inside_elapsed_boundary(self):
        envelope, value = self.inputs()
        now = [0]
        directory_type = candidate.tempfile.TemporaryDirectory
        removed = []

        class ElapsedCleanup(directory_type):
            def cleanup(self):
                super().cleanup()
                removed.append(self.name)
                now[0] = 1_100_000_000

        with (
            patch.object(candidate.time, "monotonic_ns", side_effect=lambda: now[0]),
            patch.object(candidate.tempfile, "TemporaryDirectory", ElapsedCleanup),
        ):
            with self.assertRaisesRegex(EngineeringError, "sandbox_time_budget_exceeded"):
                self.execute(envelope, value)
        self.assertEqual(len(removed), 1)
        self.assertTrue(all(not candidate.Path(path).exists() for path in removed))

    def test_receipt_duration_and_digest_include_successful_cleanup(self):
        envelope, value = self.inputs()
        now = [0]
        directory_type = candidate.tempfile.TemporaryDirectory

        class ElapsedCleanup(directory_type):
            def cleanup(self):
                super().cleanup()
                now[0] = 750_000_000

        with (
            patch.object(candidate.time, "monotonic_ns", side_effect=lambda: now[0]),
            patch.object(candidate.tempfile, "TemporaryDirectory", ElapsedCleanup),
        ):
            tested, receipt = self.execute(envelope, value)
        self.assertTrue(receipt.passed)
        self.assertEqual(receipt.duration_millis, 750)
        self.assertEqual(
            tested.sandbox_receipt_digest,
            candidate.semantic_digest(candidate.asdict(receipt)),
        )

    def test_real_git_execution_can_still_finish_within_one_budget(self):
        envelope, value = self.inputs()
        with patch.object(candidate.time, "monotonic_ns", return_value=0):
            tested, receipt = self.execute(envelope, value)
        self.assertEqual(tested.state, "fixture_tested")
        self.assertTrue(receipt.passed)
        self.assertEqual(receipt.duration_millis, 0)


if __name__ == "__main__":
    unittest.main()
