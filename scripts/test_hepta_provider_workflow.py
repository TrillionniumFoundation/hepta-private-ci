"""Check provider qualification routing and independent command admission.

This is workflow wiring coverage, not hosted Rust or default-daemon evidence.
"""

from pathlib import Path
import re
import unittest

from hepta_workflow_commands import workflow_commands

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/intelligence-provider-qualification.yml"


class ProviderWorkflowTests(unittest.TestCase):
    def test_candidate_number_does_not_bypass_provider_qualification(self):
        text = WORKFLOW.read_text()
        self.assertNotRegex(text, r"pull_request\.number\s*==")
        self.assertIn(
            "codex-rs/hepta-agentd/src/intelligence_invocation_owner_tests.rs", text
        )
        self.assertIn("codex-rs/hepta-agentd/src/objective_runtime.rs", text)
        self.assertIn("lane: [source-head, base-merge]", text)
        self.assertIn("contents: read", text)
        self.assertIn(
            ["python3", "scripts/test_hepta_provider_workflow.py"],
            workflow_commands(text),
        )
        self.assertIn("persist-credentials: false", text)

    def test_behavioral_tests_and_lint_remain_independent(self):
        text = WORKFLOW.read_text()
        steps = re.split(r"(?m)^      - name: ", text)
        recorded = [step for step in steps if "../scripts/hepta_ci_exec.py" in step]
        self.assertEqual(len(recorded), 3)
        for step in recorded:
            with self.subTest(step=step.splitlines()[0]):
                self.assertIn("!cancelled()", step)
                self.assertIn("steps.identity.outcome == 'success'", step)
                self.assertNotIn("steps.clippy.outcome", step)
                self.assertNotIn("steps.tests.outcome", step)
        commands = [" ".join(command) for command in workflow_commands(text)]
        test_commands = [cmd for cmd in commands if "-- just test " in cmd]
        self.assertEqual(len(test_commands), 1)
        self.assertIn("--minimum-tests 4", test_commands[0])
        self.assertIn("--retries 0", test_commands[0])
        self.assertIn("test(intelligence_ingress)", test_commands[0])
        self.assertTrue(
            any(
                "-- cargo clippy --locked" in cmd and "-D warnings" in cmd
                for cmd in commands
            )
        )
        self.assertNotIn("cargo clippy --fix", text)
        self.assertNotIn("git push", text)


if __name__ == "__main__":
    unittest.main()
