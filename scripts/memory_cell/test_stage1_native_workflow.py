"""Static guard for expensive real Reader execution; never loads model weights."""

from pathlib import Path
import unittest

WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github/workflows/hepta-memory-stage1-sharded-native.yml"
)


class ShardedNativeWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text()

    def test_explicit_label_only_and_authorized_pr(self):
        self.assertIn("types: [labeled]", self.source)
        self.assertIn("github.event.pull_request.number == 2607", self.source)
        self.assertIn(
            "github.event.label.name == 'memory-cell-preserved-native'",
            self.source,
        )
        self.assertNotIn("workflow_dispatch:", self.source)
        self.assertNotIn("contents: write", self.source)

    def test_exact_eight_job_matrix_resource_bound(self):
        self.assertIn("model: [smol-135m, smol-1.7b]", self.source)
        self.assertIn("shard: [0, 1, 2, 3]", self.source)
        self.assertIn("max-parallel: 4", self.source)
        self.assertIn("timeout-minutes: 85", self.source)
        self.assertIn("cancel-in-progress: false", self.source)

    def test_source_pin_precedes_any_model_download(self):
        self.assertIn("run-id: 38043602289", self.source)
        self.assertIn("ref: ${{ github.event.pull_request.head.sha }}", self.source)
        self.assertIn("persist-credentials: false", self.source)
        self.assertIn("original_pins", self.source)
        self.assertLess(
            self.source.index("name: Freeze exact eight-question corpus"),
            self.source.index("name: Stage exact publisher model"),
        )

    def test_model_staging_before_offline_inference(self):
        stage = self.source.index("name: Stage exact publisher model")
        infer = self.source.index("name: Execute real four-condition shard offline")
        self.assertLess(stage, infer)
        self.assertNotIn("HF_HUB_OFFLINE", self.source[stage:infer])
        self.assertIn('HF_HUB_OFFLINE: "1"', self.source[infer:])

    def test_before_pairing_the_collector_checks_original_slot_order(self):
        self.assertIn("verify_frozen_shard_attempts", self.source)
        self.assertLess(
            self.source.index("verify_frozen_shard_attempts(plan,reg['conditions']"),
            self.source.index("paired=0; delta=0.0"),
        )

    def test_original_failures_and_reader_pair_audited(self):
        self.assertIn("if: always()", self.source)
        self.assertIn("raw-answers.jsonl", self.source)
        self.assertIn("stage1_reader_score import answer_scores", self.source)
        self.assertIn("stage1_reader_pair import verify_inventory", self.source)
        self.assertIn("missing_bounds_not_statistical_intervals", self.source)
        self.assertIn("'production_accepted':False", self.source)


if __name__ == "__main__":
    unittest.main()
