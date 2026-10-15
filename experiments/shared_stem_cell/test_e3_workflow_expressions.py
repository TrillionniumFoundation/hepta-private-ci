"""Source-only regression for invalid escaped GitHub Actions expressions.

A literal backslash before github.sha reached git as a malformed refspec.
These tests validate workflow source, not real-model execution or efficacy.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = (
    ROOT / ".github/workflows/hepta-e3-five-arm-historical-contract.yml",
    ROOT / ".github/workflows/hepta-e3-five-arm-original-physical.yml",
)


class E3GitHubActionsExpressionTests(unittest.TestCase):
    def test_no_escaped_expressions_or_weakened_posture(self):
        for workflow in WORKFLOWS:
            with self.subTest(workflow=workflow.name):
                raw = workflow.read_text(encoding="utf-8")
                self.assertNotIn("\\" + "${{", raw)
                self.assertIn("persist-credentials: false", raw)
                self.assertIn("DENY_ALL", raw)

    def test_exact_sha_checkout_is_evaluated(self):
        for workflow in WORKFLOWS:
            with self.subTest(workflow=workflow.name):
                raw = workflow.read_text(encoding="utf-8")
                refs = re.findall(r"^\s*ref:\s*([^\n#]+)", raw, re.MULTILINE)
                sha_refs = [ref.strip() for ref in refs if "github.sha" in ref]
                self.assertTrue(sha_refs, "missing exact-head checkout")
                self.assertTrue(all(ref == "${{ github.sha }}" for ref in sha_refs))

    def test_concurrency_uses_real_run_identity(self):
        for workflow in WORKFLOWS:
            with self.subTest(workflow=workflow.name):
                raw = workflow.read_text(encoding="utf-8")
                self.assertRegex(raw, r"(?m)^  group: [^\n]*\$\{\{ github\.sha \}\}")


if __name__ == "__main__":
    unittest.main()
