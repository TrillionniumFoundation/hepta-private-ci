"""Integrated-tree Clippy guards with actual controlled subprocesses."""

import unittest

from ndu_port_integration_test_support import integrate_fixture
from ndu_post_qualification_test_support import PostQualificationFixture


class IntegratedPostQualificationTests(PostQualificationFixture):
    def setUp(self):
        super().setUp()
        self.candidate, self.candidate_sha = integrate_fixture(
            self.root, self.recipe, self.candidate, self.artifact
        )
        self.head = self.candidate["source_commit"]
        self.make_test_receipt("matrix")
        self.test_record.update(
            (key, self.candidate[key])
            for key in ("source_mode", "source_tree", "integration")
        )
        self.write_receipt()
        self.index_before = (self.root / ".git/index").read_bytes()

    def test_exact_committed_tree_replays_and_qualifies_without_source_mutation(self):
        status, receipt, output = self.run_fix()
        self.assertEqual(status, 0)
        self.assertEqual(receipt["status"], "clippy_passed_source_unchanged")
        self.assertEqual(receipt["before_tree"], self.candidate["source_tree"])
        self.assertEqual(receipt["before_tree"], receipt["after_tree"])
        self.assertEqual((output / "fix.patch").read_bytes(), b"")
        self.assertEqual((self.root / ".git/index").read_bytes(), self.index_before)

    def test_mutated_consumer_mode_cannot_inherit_the_integrated_qualification(self):
        self.test_record["source_mode"] = "patched"
        self.write_receipt()
        status, receipt, _output = self.run_fix()
        self.assertEqual(status, 1)
        self.assertIn("source_mode", receipt["error"])
        self.assertFalse(self.stamp.exists())

    def test_source_fix_preserves_locks_but_requires_new_behavioral_qualification(self):
        status, receipt, output = self.run_fix(
            action={"writes": {str(self.root / self.source): "controlled source fix\n"}}
        )
        self.assertEqual(status, 0)
        self.assertEqual(receipt["status"], "clippy_passed_review_required")
        self.assertFalse(
            receipt["prior_behavioral_qualification_applies_to_after_source"]
        )
        self.assertNotEqual((output / "fix.patch").read_bytes(), b"")
        self.assertEqual(receipt["changed_paths"], [self.source])


if __name__ == "__main__":
    unittest.main()
