import unittest

from hepta_engineering_control import (
    IntegrationEvidence,
    PathLease,
    WorkPackage,
    decide_integration,
    schedule,
)


class EngineeringControlTests(unittest.TestCase):
    def test_schedule_is_predecessor_and_path_lease_aware(self) -> None:
        packages = [
            WorkPackage(1, "B", ("A",), ("codex-rs/hepta-b/**",)),
            WorkPackage(0, "A", (), ("codex-rs/hepta-a/**",)),
            WorkPackage(2, "C", (), ("codex-rs/hepta-b/src/**",)),
        ]
        receipt = schedule(
            packages,
            completed={"A"},
            active_leases=[PathLease("external", ("codex-rs/hepta-b/**",))],
        )
        self.assertEqual(receipt.assigned, ("A",))
        self.assertIn(("B", "active_path_lease"), receipt.blocked)
        self.assertIn(("C", "active_path_lease"), receipt.blocked)
        self.assertFalse(receipt.runtime_authority)
        self.assertFalse(receipt.merge_authority)

    def test_batch_conflicts_are_deterministic(self) -> None:
        packages = [
            WorkPackage(0, "A", (), ("codex-rs/shared/**",)),
            WorkPackage(1, "B", (), ("codex-rs/shared/subtree/**",)),
        ]
        receipt = schedule(packages, completed=(), active_leases=())
        self.assertEqual(receipt.assigned, ("A",))
        self.assertEqual(receipt.blocked, (("B", "batch_path_conflict"),))

    def test_integration_eligibility_grants_no_merge_authority(self) -> None:
        evidence = IntegrationEvidence(
            candidate_head="a" * 40,
            exact_head="a" * 40,
            merge_candidate_head="c" * 40,
            base_head="b" * 40,
            source_tree="d" * 40,
            exact_head_tree="d" * 40,
            merge_candidate_tree="e" * 40,
            expected_merge_tree="e" * 40,
            merge_candidate_parents=("b" * 40, "a" * 40),
            source_execution_ok=True,
            merge_execution_ok=True,
            source_inventory_ok=True,
            static_verification_ok=True,
            focused_tests_ok=True,
            package_tests_ok=True,
            all_target_check_ok=True,
            strict_lint_ok=True,
            clean_worktree_ok=True,
            authority_delta=False,
        )
        decision = decide_integration(evidence)
        self.assertTrue(decision.eligible_for_independent_review)
        self.assertFalse(decision.merge_authority)
        self.assertFalse(decision.release_authority)

    def test_authority_delta_fails_closed(self) -> None:
        evidence = IntegrationEvidence(
            candidate_head="a" * 40,
            exact_head="a" * 40,
            merge_candidate_head="c" * 40,
            base_head="b" * 40,
            source_tree="d" * 40,
            exact_head_tree="d" * 40,
            merge_candidate_tree="e" * 40,
            expected_merge_tree="e" * 40,
            merge_candidate_parents=("b" * 40, "a" * 40),
            source_execution_ok=True,
            merge_execution_ok=True,
            source_inventory_ok=True,
            static_verification_ok=True,
            focused_tests_ok=True,
            package_tests_ok=True,
            all_target_check_ok=True,
            strict_lint_ok=True,
            clean_worktree_ok=True,
            authority_delta=True,
        )
        decision = decide_integration(evidence)
        self.assertFalse(decision.eligible_for_independent_review)
        self.assertIn("authority_delta", decision.reasons)

    def test_invalid_write_path_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            schedule(
                [WorkPackage(0, "A", (), ("../escape/**",))],
                completed=(),
                active_leases=(),
            )


if __name__ == "__main__":
    unittest.main()
