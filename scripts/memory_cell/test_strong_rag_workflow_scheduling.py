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
            '"scripts/memory_cell/strong_rag_shards.py"',
            '"scripts/memory_cell/test_strong_rag_shards.py"',
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
        # The workflow has exactly three jobs with checkouts. Calibration and
        # evaluation are separate processes within the same pinned reader job.
        # Validate each job, not an unrelated count of string occurrences.
        jobs = ("experiment-format", "reader", "independent-replay")
        for index, name in enumerate(jobs):
            block = self.text.split(f"\n  {name}:\n", 1)[1]
            if index + 1 < len(jobs):
                block = block.split(f"\n  {jobs[index + 1]}:\n", 1)[0]
            with self.subTest(job=name):
                self.assertEqual(block.count("ref: ${{ github.sha }}"), 1)
                self.assertIn("persist-credentials: false", block)
        self.assertEqual(self.text.count("ref: ${{ github.sha }}"), len(jobs))

    def test_real_reader_runs_only_after_scoped_preflight(self):
        self.assertIn("  experiment-format:\n", self.text)
        self.assertIn("  reader:\n    needs: experiment-format\n", self.text)
        self.assertIn("  independent-replay:\n    needs: reader\n", self.text)
        self.assertIn("test_strong_rag_workflow_scheduling.py' -v", self.text)

    def test_concurrent_commits_do_not_wait_on_old_branch_run(self):
        self.assertIn("group: memorycell-strong-rag-${{ github.sha }}", self.text)
        self.assertNotIn("group: memorycell-strong-rag-${{ github.ref }}", self.text)
        self.assertIn("cancel-in-progress: false", self.text)

    def test_calibration_checkpoint_is_source_bound_and_precedes_evaluation(self):
        program = self.text
        calibration = program.index("      - name: Real reader calibration only")
        checkpoint = program.index("      - name: Seal calibration-only checkpoint")
        evaluate = program.index("      - name: Different process, frozen top-k")
        self.assertLess(calibration, checkpoint)
        self.assertLess(checkpoint, evaluate)
        self.assertIn("id: calibration_generation", program)
        self.assertIn("name: memory-strong-rag-calibration-checkpoint", program)
        self.assertIn("steps.calibration_generation.outcome", program)
        self.assertIn('"$HEPTA_MEMORY_TESTED_COMMIT"', program)
        self.assertIn("> SHA256SUMS", program)
        self.assertIn("if-no-files-found: error", program)
        self.assertIn("  reader:\n    needs: experiment-format", program)
        self.assertIn("  independent-replay:\n    needs: reader", program)

    def test_reader_long_census_has_bounded_timeout_and_checkpoint(self):
        reader = self.text.split("\n  reader:\n", 1)[1].split(
            "\n  independent-replay:\n", 1
        )[0]
        self.assertIn("timeout-minutes: 360", reader)
        self.assertIn("name: memory-strong-rag-calibration-checkpoint", reader)
        self.assertIn("name: memory-strong-rag-calibrated-reader", reader)
        self.assertLess(
            reader.index("name: memory-strong-rag-calibration-checkpoint"),
            reader.index("name: Different process, frozen top-k"),
        )
        self.assertIn('test -z "$(find "$checkpoint" -type l -print -quit)"', reader)
        self.assertIn("SHA256SUMS", reader)

    def test_reader_targets_observed_bf16_candidate_with_pinned_python(self):
        reader = self.text.split("\n  reader:\n", 1)[1].split(
            "\n  independent-replay:\n", 1
        )[0]
        self.assertIn("runs-on: ubuntu-22.04", reader)
        self.assertIn(
            "actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405",
            reader,
        )
        self.assertIn('python-version: "3.12"', reader)
        self.assertLess(
            reader.index("actions/setup-python@"),
            reader.index("Verify BF16 CPU hardware before model downloads"),
        )
        self.assertIn("strong_rag_host_gate.py", reader)
        self.assertIn("host-qualification.json", reader)

    def test_bf16_eligibility_checked_on_actual_reader_runner(self):
        reader = self.text.split("\n  reader:\n", 1)[1].split(
            "\n  independent-replay:\n", 1
        )[0]
        eligible = reader.index("Verify BF16 CPU hardware before model downloads")
        staging = reader.index("Stage pinned research-only Qwen reader")
        self.assertLess(eligible, staging)
        self.assertIn("host-qualification.json", reader)
        self.assertIn("scripts/memory_cell/strong_rag_host_gate.py", reader)
        self.assertIn("scripts/memory_cell/test_strong_rag_host_gate.py", reader)
        self.assertIn("if: always()", reader)

    def test_global_format_remains_separately_observable(self):
        self.assertNotIn("\n  format:\n", self.text)
        standalone = WORKFLOW.with_name("hepta-memory-review-format-final.yml")
        self.assertTrue(standalone.is_file())
        gate = standalone.read_text(encoding="utf-8")
        self.assertIn("  pull_request:\n", gate)
        self.assertIn('just fmt --check --base "$BASE"', gate)
        self.assertIn("github.event.pull_request.number == 1452", gate)
        self.assertIn("cancel-in-progress: false", self.text)
        self.assertIn("group: memorycell-strong-rag-${{ github.sha }}", self.text)


if __name__ == "__main__":
    unittest.main()
