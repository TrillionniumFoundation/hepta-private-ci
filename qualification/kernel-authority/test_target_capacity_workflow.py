from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/kernel-authority-target-capacity.yml"
RUNBOOK = ROOT / "docs/modules/kernel.authority/TARGET_CAPACITY_RUNBOOK.md"


class TargetCapacityWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = WORKFLOW.read_text(encoding="utf-8")
        self.runbook = RUNBOOK.read_text(encoding="utf-8")

    def test_workflow_is_manual_read_only_and_target_labeled(self) -> None:
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertNotRegex(self.workflow, r"(?m)^\s{2}(push|pull_request):")
        self.assertIn("permissions:\n  contents: read", self.workflow)
        self.assertNotIn("contents: write", self.workflow)
        self.assertIn("if: github.ref == 'refs/heads/main'", self.workflow)
        self.assertIn("environment: kernel-authority-target", self.workflow)
        self.assertIn(
            "runs-on: [self-hosted, kernel-authority-target]",
            self.workflow,
        )
        self.assertIn("timeout-minutes: 360", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)
        self.assertEqual(self.workflow.count("persist-credentials: false"), 2)

    def test_candidate_checkout_is_identity_only(self) -> None:
        self.assertIn("path: control", self.workflow)
        self.assertIn("path: subject", self.workflow)
        self.assertIn(
            "Checkout candidate as a non-executed identity subject",
            self.workflow,
        )
        trusted_collector = (
            'python3 "$GITHUB_WORKSPACE/control/qualification/'
            'kernel-authority/capacity_matrix.py"'
        )
        trusted_gate = (
            'python3 "$GITHUB_WORKSPACE/control/qualification/'
            'kernel-authority/hot_path_gate.py"'
        )
        self.assertEqual(self.workflow.count(trusted_collector), 3)
        self.assertEqual(self.workflow.count(trusted_gate), 1)
        self.assertNotIn("subject/qualification/kernel-authority", self.workflow)
        self.assertIn("No script, action, build hook, or binary from `subject`", self.runbook)

    def test_driver_and_policy_are_fixed_and_content_addressed(self) -> None:
        self.assertIn(
            "DRIVER: /opt/hepta/bin/kernel-authority-capacity-driver",
            self.workflow,
        )
        self.assertIn(
            "POLICY: /opt/hepta/policies/kernel-authority-hot-path-policy.json",
            self.workflow,
        )
        self.assertIn("hashlib.sha256", self.workflow)
        self.assertIn(
            'test "$observed_driver_sha256" = "$EXPECTED_DRIVER_SHA256"',
            self.workflow,
        )
        self.assertIn(
            'test "$observed_policy_sha256" = "$EXPECTED_POLICY_SHA256"',
            self.workflow,
        )
        self.assertNotIn("--driver ${{", self.workflow)
        self.assertNotIn("--policy ${{", self.workflow)
        self.assertIn("expected SHA-256", self.runbook)
        self.assertIn("independently reviewed site policy", self.runbook)

    def test_exact_plan_collection_policy_and_revalidation_are_required(self) -> None:
        plan = self.workflow.index("capacity_matrix.py\" plan")
        collect = self.workflow.index("capacity_matrix.py\" collect")
        validate = self.workflow.index("capacity_matrix.py\" validate")
        gate = self.workflow.index("hot_path_gate.py\"")
        self.assertLess(plan, collect)
        self.assertLess(collect, validate)
        self.assertLess(validate, gate)
        self.assertIn(
            'test "$(git -C "$subject" rev-parse HEAD)" = "$CANDIDATE_SHA"',
            self.workflow,
        )
        self.assertIn("55 measurement rows", self.workflow)
        self.assertIn("eight fault rows", self.workflow)
        self.assertIn("25 diagnostics", self.workflow)
        self.assertIn("five metrics", self.workflow)
        self.assertIn("if: always()", self.workflow)
        self.assertIn("actions/upload-artifact@", self.workflow)

    def test_workflow_cannot_promote_collection_to_authority(self) -> None:
        for field in (
            "runtimeOptimizationAuthorized",
            "productionEvidenceAdmissible",
            "productionSloGranted",
            "independentAcceptance",
            "activationGranted",
            "releaseGranted",
        ):
            self.assertIn(field, self.workflow)
            self.assertRegex(self.runbook, re.escape(field))
        self.assertIn("not production acceptance", self.runbook)
        self.assertIn("must not:", self.runbook)
        self.assertIn("unknown provider result", self.runbook)


if __name__ == "__main__":
    unittest.main()
