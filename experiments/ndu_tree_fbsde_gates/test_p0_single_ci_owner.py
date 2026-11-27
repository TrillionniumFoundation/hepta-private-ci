"""Prevent two PR workflows from executing/cancelling the same real P0 trial.

This is a static safety regression, not evidence of model execution.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
CALLER = ROOT / ".github/workflows/hepta-p0-compact-pr-trigger.yml"
RUNNER = ROOT / ".github/workflows/hepta-p0-compact-physical.yml"
MAIN = ROOT / ".github/workflows/hepta-ndu-tree-fbsde-gates.yml"


class SingleP0ExecutionOwner(unittest.TestCase):
    def test_single_pr_dispatch_owner(self):
        caller = CALLER.read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")
        main = MAIN.read_text(encoding="utf-8")
        self.assertIn("  pull_request:", caller)
        self.assertIn("  workflow_call:", runner)
        self.assertNotIn("  pull_request:", runner)
        self.assertEqual(
            len(re.findall(
                r"^\s{4}uses: \./\.github/workflows/hepta-p0-compact-physical\.yml\s*$",
                caller, flags=re.MULTILINE,
            )),
            1,
        )
        self.assertNotIn("  p0-real-compact:", main)
        self.assertNotIn("uses: ./.github/workflows/hepta-p0-compact-physical.yml", main)
        self.assertIn("    paths:", caller)
        for path in (
            "p0_compact_paired.py",
            "p0_compact_score.py",
            "test_p0_compact_paired.py",
            "hepta-p0-compact-physical.yml",
            "hepta-p0-compact-pr-trigger.yml",
        ):
            self.assertIn(path, caller)

    def test_reusable_job_is_read_only_and_keeps_raw_failures(self):
        caller = CALLER.read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")
        for workflow in (caller, runner):
            self.assertIn("  contents: read", workflow)
            self.assertIn("  actions: read", workflow)
            self.assertNotIn("  contents: write", workflow)
            self.assertNotIn("  actions: write", workflow)
        self.assertIn("pre-score-seals.sha256", runner)
        self.assertIn("p0_compact_score.py", runner)
        self.assertIn("if: always()", runner)
        self.assertIn("DENY_ALL", runner)


if __name__ == "__main__":
    unittest.main()
