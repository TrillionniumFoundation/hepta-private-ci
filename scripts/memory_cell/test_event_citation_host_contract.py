"""Source-only contract for the actual frozen BF16 Qwen premise-citation run.

The GitHub OS label is only a scheduler hint. A real CPU ISA check must
run on the selected VM *before* downloading a Qwen checkpoint or executing a
single Reader answer. No change to model family, precision or decoded answer
is permitted as a workaround for a failing hardware check.
"""

from pathlib import Path
import unittest


WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github/workflows/hepta-memory-citation-premises-trial.yml"
)


class ActualPremiseReaderHostContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.reader = cls.workflow.split("  actual-frozen-reader:\n", 1)[1]

    def test_actual_runner_requires_live_hardware_gate(self):
        job = self.reader
        self.assertIn("runs-on: ubuntu-22.04", job)
        self.assertIn("Check actual x86_64 BF16 hardware before downloads", job)
        self.assertIn(
            "strong_rag_host_gate.py --output "
            "/tmp/premise-result/host-qualification.json",
            job,
        )
        self.assertLess(
            job.index("strong_rag_host_gate.py --output"),
            job.index("gh api repos/TrillionniumFoundation/"),
        )
        self.assertLess(
            job.index("strong_rag_host_gate.py --output"),
            job.index("reader_reference.py stage qwen-3b"),
        )

    def test_python_312_and_original_qwen_precision_are_not_substituted(self):
        job = self.reader
        self.assertIn(
            "actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405",
            job,
        )
        self.assertIn('python-version: "3.12"', job)
        self.assertIn("pip install torch==2.5.1", job)
        self.assertIn("pip install -r /tmp/premise-input/environment.txt", job)
        self.assertIn("diff -u /tmp/premise-input/environment.txt", job)
        self.assertIn("reader_reference.py stage qwen-3b", job)
        self.assertIn("HF_HUB_OFFLINE:", job)
        self.assertNotIn("torch_dtype=torch.float32", job)
        self.assertNotIn("quantization_config", job)

    def test_rejected_vm_still_archives_unmodified_source_and_gate(self):
        job = self.reader
        self.assertIn("mkdir -p /tmp/premise-result", job)
        self.assertIn("if: always()", job)
        self.assertIn("name: memory-frozen-citation-premises-paired", job)
        self.assertIn("path: /tmp/premise-result", job)
        self.assertIn("git rev-parse HEAD > /tmp/premise-result/tested-commit.txt", job)
        self.assertIn("SHA256SUMS", job)

    def test_original_plan_and_experiment_arms_are_not_waived(self):
        job = self.reader
        self.assertIn("original plan, scopes, frozen candidate pools: verified", job)
        plan_pin = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
        self.assertIn("--plan-sha " + plan_pin, job)
        self.assertIn("event_citation_prompt_trial.py", job)
        self.assertIn("--stage-sha", job)
        self.assertIn("test_event_citation_prompt_trial.py", self.workflow)


if __name__ == "__main__":
    unittest.main()
