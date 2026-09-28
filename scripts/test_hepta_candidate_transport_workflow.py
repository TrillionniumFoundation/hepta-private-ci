"""Guard ordinary candidate qualification from live permission probes."""
from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hepta-architecture-convergence.yml"


class CandidateTransportWorkflowTests(unittest.TestCase):
    def test_ordinary_qualification_uses_local_contract_tests_only(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        marker = "      - name: Verify candidate transport stays proposal-only\n"
        self.assertIn(marker, workflow)
        block = workflow.split(marker, 1)[1].split("      - name:", 1)[0]
        self.assertIn("scripts.test_hepta_candidate_transport_workflow", block)
        self.assertIn("--minimum-tests 1", block)
        self.assertNotIn("GH_TOKEN", block)
        self.assertNotIn("observe_write_transport_denial", block)
        self.assertNotIn("git-receive-pack", block)
        self.assertNotIn("gh api", block)

    def test_external_repository_observation_remains_activation_only(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("probe-write-denial", workflow)
        self.assertNotIn("service=git-receive-pack", workflow)
        activation = ROOT / ".github/workflows/hepta-self-iteration-activation.yml"
        self.assertTrue(activation.is_file())
        activation_text = activation.read_text(encoding="utf-8")
        self.assertIn("repository", activation_text.lower())
        self.assertIn("activation", activation_text.lower())

    def test_native_and_lifecycle_work_precedes_transport_contract(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        probe = workflow.index("      - name: Verify candidate transport stays proposal-only")
        for name in (
            "Inference owner regressions and streaming digest",
            "Module lifecycle generations and migration rollback",
            "Selected-artifact adoption and explicit rollback",
        ):
            self.assertLess(workflow.index("      - name: " + name), probe)

    def test_required_fan_in_still_rejects_failed_lane(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("needs: qualification", workflow)
        self.assertIn('test "$RESULT" = success', workflow)
        self.assertNotIn("continue-on-error", workflow)


if __name__ == "__main__":
    unittest.main()
