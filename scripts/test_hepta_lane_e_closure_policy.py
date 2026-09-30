#!/usr/bin/env python3
"""Regression tests for the current Lane E source-graph policy."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import hepta_lane_e_closure_policy as policy


class LaneEClosurePolicyTests(unittest.TestCase):
    def test_qualification_feature_items_are_removed_but_product_code_remains(self) -> None:
        source = '''
#[cfg(feature = "qualification-legacy-learning-write")]
use codex_hepta_learning_ledger::DurableLearningJournal;

#[cfg(feature = "qualification-legacy-learning-write")]
pub fn append_legacy() {
    let _ = LedgerEvent::Decision;
}

pub fn product_path() {
    let _ = LedgerEvent::Outcome;
}
'''
        filtered = policy._strip_cfg_feature_items(
            source, policy.QUALIFICATION_LEGACY_FEATURE
        )
        self.assertNotIn("DurableLearningJournal", filtered)
        self.assertNotIn("LedgerEvent::Decision", filtered)
        self.assertIn("LedgerEvent::Outcome", filtered)

    def test_unterminated_cfg_item_stays_visible_and_fails_closed(self) -> None:
        source = '''
#[cfg(feature = "qualification-legacy-learning-write")]
pub fn incomplete() {
    let _ = LedgerEvent::Decision;
'''
        filtered = policy._strip_cfg_feature_items(
            source, policy.QUALIFICATION_LEGACY_FEATURE
        )
        self.assertIn("LedgerEvent::Decision", filtered)

    def test_path_module_resolution_finds_moved_test(self) -> None:
        scripts = policy.ROOT / "scripts"
        with tempfile.TemporaryDirectory(dir=scripts) as directory:
            root = Path(directory)
            parent = root / "parent.rs"
            child = root / "child.rs"
            parent.write_text('#[path = "child.rs"]\nmod child;\n', encoding="utf-8")
            child.write_text(
                '#[test]\nfn moved_regression_test() {}\n', encoding="utf-8"
            )
            self.assertTrue(
                policy._test_function_exists(parent, "moved_regression_test")
            )
            self.assertFalse(policy._test_function_exists(parent, "missing_test"))

    def test_policy_tracks_expanded_operator_and_case_sets(self) -> None:
        self.assertIn("OP-06", policy._base.EXPECTED_CASES)
        self.assertIn(
            "fit_transition_model_verified_v2",
            policy._base.EXPECTED_OPERATIONS["learning.operator"],
        )
        self.assertEqual(policy._base.COVERAGE_TOOL_PIN, "cargo-llvm-cov@0.9.0")


if __name__ == "__main__":
    unittest.main()
