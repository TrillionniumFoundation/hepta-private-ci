"""Source qualification and synthetic-merge qualification must bind real identities."""
from dataclasses import replace
import unittest

from hepta_engineering_control import IntegrationEvidence, decide_integration


class IntegrationIdentityTests(unittest.TestCase):
    def setUp(self):
        self.evidence = IntegrationEvidence(
            candidate_head="a" * 40, exact_head="a" * 40,
            merge_candidate_head="c" * 40, base_head="b" * 40,
            source_tree="d" * 40, exact_head_tree="d" * 40,
            merge_candidate_tree="e" * 40, expected_merge_tree="e" * 40,
            merge_candidate_parents=("b" * 40, "a" * 40),
            source_execution_ok=True, merge_execution_ok=True,
            source_inventory_ok=True, static_verification_ok=True,
            focused_tests_ok=True, package_tests_ok=True,
            all_target_check_ok=True, strict_lint_ok=True,
            clean_worktree_ok=True, authority_delta=False,
        )

    def test_distinct_source_and_merge_commit_are_eligible_only_for_review(self):
        decision = decide_integration(self.evidence)
        self.assertTrue(decision.eligible_for_independent_review)
        self.assertEqual(decision.reasons, ())
        self.assertFalse(any((decision.runtime_authority, decision.merge_authority,
                              decision.promotion_authority, decision.release_authority)))

    def test_source_tree_and_merge_tree_mismatches_fail_closed(self):
        for field, reason in [("exact_head_tree", "source_tree_mismatch"),
                              ("merge_candidate_tree", "merge_tree_mismatch")]:
            with self.subTest(field=field):
                result = decide_integration(replace(self.evidence, **{field: "f" * 40}))
                self.assertFalse(result.eligible_for_independent_review)
                self.assertIn(reason, result.reasons)

    def test_exact_head_drift_is_rejected(self):
        self.assertIn("exact_head_mismatch", decide_integration(replace(
            self.evidence, exact_head="f" * 40)).reasons)

    def test_reversed_missing_or_extra_merge_parents_are_rejected(self):
        for parents in [("a" * 40, "b" * 40), (), ("b" * 40, "a" * 40, "f" * 40)]:
            with self.subTest(parents=parents):
                self.assertIn("merge_parent_mismatch", decide_integration(replace(
                    self.evidence, merge_candidate_parents=parents)).reasons)

    def test_source_head_cannot_stand_in_for_synthetic_merge(self):
        self.assertIn("synthetic_merge_not_distinct", decide_integration(replace(
            self.evidence, merge_candidate_head=self.evidence.candidate_head)).reasons)

    def test_both_execution_lanes_are_required(self):
        for field, reason in [("source_execution_ok", "source_execution"),
                              ("merge_execution_ok", "merge_execution")]:
            with self.subTest(field=field):
                self.assertIn(reason, decide_integration(replace(self.evidence, **{field: False})).reasons)

    def test_malformed_or_null_git_objects_are_rejected(self):
        for value in ["abc", "0" * 40, "g" * 40, None]:
            with self.subTest(value=value):
                self.assertIn("invalid_git_identity", decide_integration(replace(
                    self.evidence, source_tree=value)).reasons)

    def test_string_and_numeric_booleans_are_not_evidence(self):
        self.assertIn("focused_tests", decide_integration(replace(
            self.evidence, focused_tests_ok="true")).reasons)
        self.assertIn("authority_delta", decide_integration(replace(
            self.evidence, authority_delta=0)).reasons)


if __name__ == "__main__":
    unittest.main()
