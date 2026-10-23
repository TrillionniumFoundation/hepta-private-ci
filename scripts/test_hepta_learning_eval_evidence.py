#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


AGGREGATE = load("aggregate", "hepta-learning-eval-aggregate.py")
EXACT = load("exact_summary", "hepta-learning-eval-exact-summary.py")
PR = load("pr_status", "hepta-learning-eval-pr-status.py")


class EvidenceTests(unittest.TestCase):
    def source(self, result: str = "success"):
        jobs = {name: result for name in AGGREGATE.REQUIRED_JOBS}
        return AGGREGATE.build(
            "1" * 40, "2" * 40, "owner/repo", "9", "1", jobs
        )

    def test_source_summary_uses_scoped_claims_and_valid_digest(self):
        value = self.source()
        AGGREGATE.validate(value)
        self.assertTrue(value["claims"]["sourceQualifiedByThisRun"])
        self.assertFalse(value["claims"]["exactHeadExecuted"])
        self.assertEqual(value["authority"], "DENY_ALL")
        self.assertEqual(value["releasePosture"], "NO_GO")

    def test_failed_job_cannot_claim_source_qualification(self):
        value = self.source("failure")
        AGGREGATE.validate(value)
        self.assertFalse(value["claims"]["sourceQualifiedByThisRun"])

    def test_exact_pull_request_requires_both_matrix_rows(self):
        value = EXACT.build(
            "1" * 40, "2" * 40, "3" * 40, "4" * 40,
            "pull_request", "success", "owner/repo", "9", "1",
        )
        EXACT.validate(value)
        self.assertTrue(value["claims"]["exactHeadExecuted"])
        self.assertTrue(value["claims"]["orderedParentSyntheticMergeExecuted"])

    def test_marker_replacement_preserves_human_text_and_migrates_legacy(self):
        legacy = (
            "Human introduction\n\n"
            "<!-- learning.eval qualification:start -->\nold\n"
            "<!-- learning.eval qualification:end -->\n\nHuman tail\n"
        )
        block = PR.render(self.source(), "source")
        updated = PR.replace_marker(legacy, block, "source")
        self.assertIn("Human introduction", updated)
        self.assertIn("Human tail", updated)
        self.assertNotIn("\nold\n", updated)
        self.assertEqual(updated.count(PR.MARKERS["source"][0]), 1)

    def test_pr_status_refuses_external_self_acceptance(self):
        value = self.source()
        value["claims"]["targetHostQualified"] = True
        with self.assertRaises(ValueError):
            PR.render(value, "source")


if __name__ == "__main__":
    unittest.main()
