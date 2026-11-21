"""Tests for the metadata-only branch-policy path repair."""

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/hcsn-currentstate-n256-signed-batch-candidate.yml"
PACKAGE_PREFIX = "qualification/hcsn_currentstate_n256_signed_batch_candidate/"
EXPECTED_FILES = {
    "README.md",
    "REQUEST.json",
    "REVIEW.json",
    "SOURCE_FREEZE.json",
    "__init__.py",
    "batch_candidate.py",
    "test_batch_candidate.py",
    "verify_source.py",
}


class PolicyFixTest(unittest.TestCase):
    def test_repaired_workflow_has_no_deprecated_pattern(self):
        text = WORKFLOW.read_text()
        policy = json.loads((ROOT / "docs/branch-policy.json").read_text())
        self.assertFalse([token for token in policy["deprecatedPatterns"] if token in text])

    def test_repaired_workflow_names_exact_frozen_files(self):
        text = WORKFLOW.read_text()
        observed = {
            line.split(PACKAGE_PREFIX, 1)[1].split('"', 1)[0]
            for line in text.splitlines()
            if line.lstrip().startswith(f'- "{PACKAGE_PREFIX}')
        }
        self.assertEqual(observed, EXPECTED_FILES)

    def test_original_freeze_remains_fail_closed(self):
        original = json.loads(
            (Path(__file__).with_name("ORIGINAL_6918_SOURCE_FREEZE.json")).read_text()
        )
        self.assertFalse(original["n256_qualified"])
        self.assertFalse(original["resource_gate_closed"])
        self.assertTrue(original["historical_negative_and_unknown_preserved"])


if __name__ == "__main__":
    unittest.main()
