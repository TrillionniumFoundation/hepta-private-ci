"""Regression guards for intuition qualification workflow authority and concurrency."""

from pathlib import Path
import re
import os
import subprocess
import textwrap
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
                active = "\n".join(
                    line
                    for line in text.splitlines()
                    if not line.lstrip().startswith("#")
                )
                self.assertRegex(active, r"(?m)^  contents: read$")
                self.assertNotRegex(active, r"(?m)^\s*contents:\s*write\s*$")
                self.assertNotRegex(active, r"(?m)^\s*(push|pull_request|schedule):")
                self.assertNotRegex(
                    active, r"git\s+(push|commit)|persist-credentials:\s*true"
                )
                self.assertNotIn("scripts/intuition_finalize_branch.py", active)
                self.assertNotIn("scripts/intuition_legacy_imports.py", active)
                self.assertIn("exit 1", active)

    def test_qualification_keeps_one_current_candidate_per_pr(self):
        text = (
            ROOT / ".github/workflows/hepta-intuition-qualification.yml"
        ).read_text()
        match = re.search(r"(?m)^  group: (.+)$", text)
        self.assertIsNotNone(match)
        group = match.group(1)
        self.assertIn("github.event.pull_request.number || github.ref", group)
        self.assertNotIn("head.sha", group)
        self.assertNotIn("github.sha", group)
        self.assertRegex(text, r"(?m)^  cancel-in-progress: true$")

    def test_cancelled_candidate_cannot_hold_required_sentinel_open(self):
        text = (
            ROOT / ".github/workflows/hepta-intuition-qualification.yml"
        ).read_text()
        required = text.split("\n  required:\n", 1)[1]
        self.assertRegex(
            required,
            r"(?m)^    if: \$\{\{ always\(\) && !cancelled\(\) \}\}$",
        )
        self.assertNotRegex(required, r"(?m)^    if: always\(\)$")

    def test_actual_required_shell_rejects_each_incomplete_evidence_lane(self):
        workflow = (
            ROOT / ".github/workflows/hepta-intuition-qualification.yml"
        ).read_text()
        required = workflow.split("\n  required:\n", 1)[1]
        script = textwrap.dedent(required.split("        run: |\n", 1)[1])
        names = (
            "EVIDENCE_RESULT",
            "QUALIFICATION_RESULT",
            "INDEPENDENT_RESULT",
            "AGREEMENT_RESULT",
        )
        complete = dict.fromkeys(names, "success")
        cases = [("complete", complete)]
        for name in names:
            for outcome in ("failure", "cancelled", "skipped"):
                cases.append((f"{name}:{outcome}", {**complete, name: outcome}))
        for label, values in cases:
            with self.subTest(case=label):
                result = subprocess.run(
                    ["bash", "-c", script],
                    env={**os.environ, **values},
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(result.returncode == 0, label == "complete")


if __name__ == "__main__":
    unittest.main()
