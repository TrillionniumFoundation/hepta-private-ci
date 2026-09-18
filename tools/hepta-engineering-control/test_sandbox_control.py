import unittest
from unittest import mock

from control_engineering_v2.candidate import Candidate, CandidateEnvelope, Mutation, SandboxReceipt
from control_engineering_v2.control_plane import EngineeringError
from control_engineering_v2.sandbox_control import SandboxCoordinator, SandboxExecutionPolicy


class SandboxCoordinatorTests(unittest.TestCase):
    def candidate(self):
        mutation = Mutation("no_change")
        return Candidate(
            "c" * 32,
            "env",
            "a" * 40,
            mutation,
            "d" * 64,
            "no_change",
            (),
            None,
        )

    def receipt(self):
        return SandboxReceipt(
            "c" * 32,
            "a" * 40,
            "b" * 40,
            "b" * 40,
            (("check", 0),),
            0,
            True,
            1,
            True,
            False,
            True,
            "bubblewrap-unshare-all-ro-workspace-v2",
            "1" * 64,
            "2" * 64,
            "2" * 64,
            "3" * 64,
            "3" * 64,
        )

    def test_infrastructure_failure_retries_at_most_twice(self):
        coordinator = SandboxCoordinator(SandboxExecutionPolicy(8, 2))
        with mock.patch(
            "control_engineering_v2.sandbox_control.sandbox_candidate",
            side_effect=[
                EngineeringError("git_operation_failed"),
                EngineeringError("network_isolation_unavailable"),
                (self.candidate(), self.receipt()),
            ],
        ) as runner:
            result = coordinator.execute(
                "/repo",
                CandidateEnvelope("env", "a" * 40, ("src",)),
                self.candidate(),
                (("true",),),
            )
        self.assertEqual(result.attempts, 3)
        self.assertEqual(runner.call_count, 3)

    def test_semantic_failure_is_never_retried(self):
        coordinator = SandboxCoordinator()
        with mock.patch(
            "control_engineering_v2.sandbox_control.sandbox_candidate",
            side_effect=EngineeringError("protected_path"),
        ) as runner:
            with self.assertRaisesRegex(EngineeringError, "protected_path"):
                coordinator.execute(
                    "/repo",
                    CandidateEnvelope("env", "a" * 40, ("src",)),
                    self.candidate(),
                    (("true",),),
                )
        self.assertEqual(runner.call_count, 1)

    def test_policy_cannot_exceed_dossier_ceiling(self):
        with self.assertRaisesRegex(EngineeringError, "invalid_sandbox_execution_policy"):
            SandboxCoordinator(SandboxExecutionPolicy(9, 2))
        with self.assertRaisesRegex(EngineeringError, "invalid_sandbox_execution_policy"):
            SandboxCoordinator(SandboxExecutionPolicy(8, 3))


if __name__ == "__main__":
    unittest.main()
