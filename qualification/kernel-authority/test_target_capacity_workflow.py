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
        self.assertIn(
            "runs-on: [self-hosted, kernel-authority-target]",
            self.workflow,
        )
        self.assertIn("cancel-in-progress: false", self.workflow)
        self.assertIn("persist-credentials: false", self.workflow)

    def test_driver_is_fixed_and_content_addressed(self) -> None:
        self.assertIn(
            "DRIVER: /opt/hepta/bin/kernel-authority-capacity-driver",
            self.workflow,
        )
        self.assertIn('sha256sum "$DRIVER"', self.workflow)
        self.assertIn(
            'test "$observed_driver_sha256" = "$EXPECTED_DRIVER_SHA256"',
            self.workflow,
        )
        self.assertNotIn("--driver ${{", self.workflow)
        self.assertIn("expected SHA-256", self.runbook)

    def test_exact_plan_collection_and_revalidation_are_required(self) -> None:
        plan = self.workflow.index("capacity_matrix.py plan")
        collect = self.workflow.index("capacity_matrix.py collect")
        validate = self.workflow.index("capacity_matrix.py validate")
        self.assertLess(plan, collect)
        self.assertLess(collect, validate)
        self.assertIn('test "$(git rev-parse HEAD)" = "$CANDIDATE_SHA"', self.workflow)
        self.assertIn("55 measurement rows", self.workflow)
        self.assertIn("eight fault rows", self.workflow)
        self.assertIn("25 diagnostics", self.workflow)
        self.assertIn("if: always()", self.workflow)
        self.assertIn("actions/upload-artifact@", self.workflow)

    def test_workflow_cannot_promote_collection_to_authority(self) -> None:
        for field in (
            "productionEvidenceAdmissible",
            "productionSloGranted",
            "independentAcceptance",
            "activationGranted",
            "releaseGranted",
        ):
            self.assertIn(field, self.workflow)
            self.assertRegex(
                self.runbook,
                re.escape(field),
            )
        self.assertIn("not production acceptance", self.runbook)
        self.assertIn("must not create a second", self.runbook)
        self.assertIn("unknown provider result", self.runbook)


if __name__ == "__main__":
    unittest.main()
