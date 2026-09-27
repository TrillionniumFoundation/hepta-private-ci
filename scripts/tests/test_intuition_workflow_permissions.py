"""Regression guard for retired intuition source-mutating workflows."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
RETIRED = (
    "intuition-autoformat-once.yml",
    "intuition-serving-compose-once.yml",
    "intuition-source-apply-arm.yml",
)


class ReadOnlyWorkflowTests(unittest.TestCase):
    def test_retired_workflows_cannot_mutate_any_branch(self):
        for name in RETIRED:
            with self.subTest(workflow=name):
                text = (ROOT / ".github/workflows" / name).read_text()
                active = "\n".join(line for line in text.splitlines()
                                   if not line.lstrip().startswith("#"))
                self.assertRegex(active, r"(?m)^  contents: read$")
                self.assertNotRegex(active, r"(?m)^\s*contents:\s*write\s*$")
                self.assertNotRegex(active, r"(?m)^\s*(push|pull_request|schedule):")
                self.assertNotRegex(active, r"git\s+(push|commit)|persist-credentials:\s*true")
                self.assertNotIn("scripts/intuition_finalize_branch.py", active)
                self.assertNotIn("scripts/intuition_legacy_imports.py", active)
                self.assertIn("exit 1", active)


if __name__ == "__main__":
    unittest.main()
