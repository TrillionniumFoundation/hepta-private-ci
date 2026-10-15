"""Regression: prevent redundant expensive five-arm model jobs on PR events.

GitHub event/ref controls are orthogonal to the model science result.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
PHYSICAL = ROOT / ".github/workflows/hepta-e3-five-arm-original-physical.yml"
CONTRACT = ROOT / ".github/workflows/hepta-e3-five-arm-historical-contract.yml"
CHILD = "research/e3-five-arm-decongest-ci-20261015"

def physical_job(name, text):
    # Match job-level two-space headings, never nested four-space steps.
    marker = re.compile(
        r"(?ms)^  " + re.escape(name) + r":\n(.*?)(?=^  [a-z][a-z0-9-]*:|\Z)"
    )
    matches = marker.findall(text)
    if len(matches) != 1:
        raise ValueError("missing or duplicate workflow job")
    return matches[0]

class ExpensiveWorkGuard(unittest.TestCase):
    def test_physical_model_jobs_run_only_on_push(self):
        raw = PHYSICAL.read_text(encoding="utf-8")
        for job in ("physical-ocr-granite", "physical-native-gemma2", "independent-five-arm-review"):
            part = physical_job(job, raw)
            self.assertTrue(part.startswith("    if: github.event_name == 'push'\n"), part[:140])

    def test_pr_continues_to_run_security_contract(self):
        raw = PHYSICAL.read_text(encoding="utf-8")
        self.assertIn("  pull_request:\n", raw)
        part = physical_job("schema-and-security-contract", raw)
        self.assertIn("github.event_name == 'pull_request'", part)
        self.assertIn("test_e3_source_target_partition.py", raw)

    def test_same_branch_cancels_superseded_sha(self):
        for path, group in ((PHYSICAL, "hepta-e3-five-real"), (CONTRACT, "hepta-e3-five-arm-contract")):
            with self.subTest(path=path):
                raw = path.read_text(encoding="utf-8")
                self.assertIn(f"  group: {group}-${{{{ github.ref }}}}", raw)
                self.assertIn("  cancel-in-progress: true", raw)
                self.assertNotIn(f"  group: {group}-${{{{ github.sha }}}}", raw)
                self.assertIn(CHILD, raw)

    def test_independent_held_target_boundary_not_weakened(self):
        raw = PHYSICAL.read_text(encoding="utf-8")
        header, jobs = raw.split("\njobs:\n", 1)
        self.assertNotIn("HELD_SHA:", header)
        pre, independent = jobs.split("  independent-five-arm-review:\n", 1)
        self.assertNotIn("HELD_SHA:", pre)
        self.assertIn("HELD_SHA:", independent)
        self.assertEqual(raw.count("--predictor-source-only"), 2)
        self.assertEqual(raw.count('rm -rf -- "$RUNNER_TEMP/e3-source-cache"'), 2)

if __name__ == "__main__":
    unittest.main()
