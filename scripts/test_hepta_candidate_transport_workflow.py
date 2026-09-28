"""Guard ordinary candidate qualification from live permission probes."""

from __future__ import annotations

from pathlib import Path
import itertools
import os
import subprocess
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
        probe = workflow.index(
            "      - name: Verify candidate transport stays proposal-only"
        )
        for name in (
            "Inference owner regressions and streaming digest",
            "Module lifecycle generations and migration rollback",
            "Selected-artifact adoption and explicit rollback",
        ):
            self.assertLess(workflow.index("      - name: " + name), probe)

    def test_required_fan_in_still_rejects_every_unsuccessful_lane(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        required = workflow.split("  required:\n", 1)[1]
        self.assertIn("needs: [plan, qualification]", required)
        self.assertIn("PLAN_RESULT: ${{ needs.plan.result }}", required)
        self.assertIn(
            "QUALIFICATION_RESULT: ${{ needs.qualification.result }}", required
        )
        self.assertNotIn("continue-on-error", required)
        script = required.split("        run: |\n", 1)[1]
        script = "\n".join(line[10:] for line in script.splitlines() if line.strip())
        states = (
            "success",
            "failure",
            "skipped",
            "cancelled",
            "timed_out",
            "action_required",
        )
        for plan, qualification in itertools.product(states, repeat=2):
            with self.subTest(plan=plan, qualification=qualification):
                process = subprocess.run(
                    ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
                    env={
                        **os.environ,
                        "PLAN_RESULT": plan,
                        "QUALIFICATION_RESULT": qualification,
                        "RISK": "ordinary",
                        "LANES": "source-head",
                    },
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(
                    process.returncode == 0, plan == qualification == "success"
                )


if __name__ == "__main__":
    unittest.main()
