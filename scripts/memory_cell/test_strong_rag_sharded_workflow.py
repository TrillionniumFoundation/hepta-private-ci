"""Model-free contract checks for the disjoint Qwen source-pinned workflow."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/hepta-memory-strong-rag-sharded.yml"


class ShardedWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.value = WORKFLOW.read_text(encoding="utf-8")

    def test_32_sources_cover_40_calibration_and_72_evaluation_arms(self):
        from strong_rag_shards import groups

        self.assertEqual(sum(len(g) for g in groups("calibration")) * 8, 40)
        self.assertEqual(sum(len(g) for g in groups("evaluation")) * 8, 72)
        self.assertEqual(self.value.count("case: [0, 1, 2, 3, 4, 5, 6, 7]"), 2)
        self.assertEqual(self.value.count("part: [0, 1]"), 2)
        self.assertEqual(self.value.count("max-parallel: 4"), 2)

    def test_calibration_is_sealed_before_any_evaluation_job(self):
        for gate in (
            "prepare:\n    needs: preflight",
            "calibration-shard:\n    needs: prepare",
            "calibration-collect:\n    needs: calibration-shard",
            "evaluation-shard:\n    needs: calibration-collect",
            "evaluation-collect:\n    needs: evaluation-shard",
            "independent-replay:\n    needs: evaluation-collect",
        ):
            self.assertIn(gate, self.value)
        self.assertIn("/tmp/absent-test-labels", self.value)
        self.assertIn("rag-sharded-calibration-joined", self.value)

    def test_all_generators_bind_original_source_commit_and_frozen_qwen(self):
        self.assertIn("HEPTA_MEMORY_TESTED_COMMIT: ${{ github.sha }}", self.value)
        self.assertIn("group: memory-strong-rag-shards-${{ github.sha }}", self.value)
        self.assertIn("cancel-in-progress: false", self.value)
        self.assertEqual(self.value.count("reader_reference.py stage qwen-3b"), 2)
        self.assertEqual(self.value.count("strong_rag_sharded_ci.py align"), 2)
        self.assertEqual(self.value.count("strong_rag_host_gate.py"), 2)
        self.assertIn("timeout-minutes: 360", self.value)
        self.assertNotIn("workflow_dispatch:", self.value)

    def test_final_read_only_replay_never_bypasses_failed_shards(self):
        self.assertIn("strong_rag_shards.py verify-release", self.value)
        self.assertIn("strong_rag_receipt.py /tmp/rag-release", self.value)
        self.assertIn("strong_rag_sharded_ci.py verify /tmp/rag-release", self.value)
        self.assertIn("if-no-files-found: warn", self.value)
        self.assertNotIn("continue-on-error: true", self.value)
        self.assertNotIn("production_accepted: true", self.value)


if __name__ == "__main__":
    unittest.main()
