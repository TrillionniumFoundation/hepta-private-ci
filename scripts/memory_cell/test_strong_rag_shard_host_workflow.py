"""Sharded frozen Qwen must qualify its actual CPU before staging weights.

Static workflow checks are not evidence of model accuracy or hardware admission.
"""

from pathlib import Path
import unittest


WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github/workflows/hepta-memory-strong-rag-cpu-shards.yml"
)


def job(text, name, following):
    begin = text.index(f"  {name}:\n")
    end = text.index(f"  {following}:\n", begin)
    return text[begin:end]


class ShardedHostedCpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = WORKFLOW.read_text(encoding="utf-8")
        cls.calibration = job(text, "calibration-shards", "calibration-collect")
        cls.evaluation = job(text, "evaluation-shards", "evaluation-collect")
        cls.prepare = job(text, "prepare", "calibration-shards")
        cls.all_jobs = (cls.calibration, cls.evaluation)

    def test_real_model_hosts_use_same_pinned_python_profile(self):
        for section in self.all_jobs:
            with self.subTest(section=section[:45]):
                self.assertIn("runs-on: ubuntu-22.04", section)
                self.assertIn("actions/setup-python@", section)
                self.assertIn('python-version: "3.12"', section)
                self.assertIn("timeout-minutes: 360", section)

    def test_actual_bf16_isa_gate_precedes_any_model_staging(self):
        for section in self.all_jobs:
            self.assertIn(
                "scripts/memory_cell/strong_rag_host_gate.py --output",
                section,
            )
            self.assertLess(
                section.index("strong_rag_host_gate.py --output"),
                section.index("reader_reference.py stage qwen-3b"),
            )

    def test_failed_host_checks_retain_exact_source_and_verdict(self):
        for stage, section in (
            ("calibration", self.calibration),
            ("evaluation", self.evaluation),
        ):
            self.assertIn("host-qualification.json", section)
            self.assertIn("tested-commit.txt", section)
            self.assertIn("if: always()", section)
            self.assertIn(f"name: memory-{stage}-host-", section)

    def test_original_calibration_and_evaluation_populations_preserved(self):
        for section in self.all_jobs:
            self.assertIn("case: [0, 1, 2, 3, 4, 5, 6, 7]", section)
            self.assertIn("part: [0, 1]", section)
            self.assertIn("fail-fast: false", section)
            self.assertIn("HEPTA_MEMORY_TESTED_COMMIT:", section)
            self.assertIn("if-no-files-found: warn", section)
        self.assertIn("strong_rag_trial.py prepare", self.prepare)

    def test_preparation_runs_host_workflow_contract_before_downloads(self):
        self.assertIn("test_strong_rag_shard_host_workflow.py", self.prepare)
        self.assertLess(
            self.prepare.index("test_strong_rag_shard_host_workflow.py"),
            self.prepare.index("gh api repos/"),
        )


if __name__ == "__main__":
    unittest.main()
