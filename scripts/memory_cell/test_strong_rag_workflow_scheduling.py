"""Research execution is triggered by changed source, not the entire PR diff.

This is a workflow scheduling contract, not an inference or production result.
"""

from pathlib import Path
import unittest


WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github/workflows/hepta-memory-strong-rag.yml"
)
BRANCH = "codex/memory-cell-evidence-20261008"


class ScopedResearchWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.trigger = cls.text.split("\npermissions:\n", 1)[0]

    def test_branch_push_does_not_retrigger_on_pr_synchronize(self):
        self.assertIn("\n  push:\n", self.trigger)
        self.assertIn(f"\n      - {BRANCH}\n", self.trigger)
        self.assertNotIn("pull_request:", self.trigger)
        self.assertNotIn("github.event.pull_request", self.text)

    def test_path_filter_excludes_concurrent_stem_work(self):
        for path in (
            '"scripts/memory_cell/strong_rag_trial.py"',
            '"scripts/memory_cell/strong_rag_receipt.py"',
            '"scripts/memory_cell/strong_rag_repeatability.py"',
            '"scripts/memory_cell/strong_rag_stability.py"',
            '"scripts/memory_cell/test_strong_rag_workflow_scheduling.py"',
            '".github/workflows/hepta-memory-strong-rag.yml"',
        ):
            self.assertIn(path, self.trigger)
        self.assertNotIn("stem_cell", self.trigger)

    def test_same_push_sha_binds_generating_and_review_jobs(self):
        self.assertIn("HEPTA_MEMORY_TESTED_COMMIT: ${{ github.sha }}", self.text)
        self.assertIn("GENERATING_COMMIT: ${{ github.sha }}", self.text)
        self.assertGreaterEqual(self.text.count("ref: ${{ github.sha }}"), 4)

    def test_real_reader_runs_only_after_scoped_preflight(self):
        self.assertIn("  experiment-format:\n", self.text)
        self.assertIn("  reader:\n    needs: experiment-format\n", self.text)
        self.assertIn("  independent-replay:\n    needs: reader\n", self.text)
        self.assertIn("test_strong_rag_workflow_scheduling.py' -v", self.text)

    def test_global_format_remains_separately_observable(self):
        self.assertIn("  format:\n", self.text)
        self.assertIn('BASE_COMMIT="$(git rev-parse FETCH_HEAD)"', self.text)
        self.assertIn('just fmt --check --base "$BASE_COMMIT"', self.text)
        self.assertIn("cancel-in-progress: false", self.text)
        self.assertIn("group: memorycell-strong-rag-${{ github.ref }}", self.text)


if __name__ == "__main__":
    unittest.main()
