"""No historical local model performance promotion through report edits."""

import copy
import unittest
from locomo_real_evidence_gate import verify_sources, disposition


class FrozenOriginalReaderProofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original, cls.replay = verify_sources()

    def fixture(self):
        return copy.deepcopy(self.original), copy.deepcopy(self.replay)

    def test_original_negative_and_no_go(self):
        out = disposition(*self.fixture())
        self.assertEqual(out["executed_physical_reader_calls"], 32)
        self.assertEqual(out["task_success_in_all_conditions"], 0)
        self.assertFalse(out["production_accepted"])

    def test_fabricated_task_success_rejected(self):
        a, b = self.fixture()
        a["by_arm"]["annotated_witness"]["strict_correct"] = 1
        with self.assertRaisesRegex(ValueError, "task/citation"):
            disposition(a, b)

    def test_empty_arm_cost_forge_rejected(self):
        a, b = self.fixture()
        a["by_arm"]["empty"]["input_tokens"] = 0
        with self.assertRaisesRegex(ValueError, "task/citation"):
            disposition(a, b)

    def test_new_learner_false_positive_rejected(self):
        a, b = self.fixture()
        a["trained_parameter_memory"] = True
        with self.assertRaisesRegex(ValueError, "qualification"):
            disposition(a, b)

    def test_human_judge_forge_rejected(self):
        a, b = self.fixture()
        a["human_semantic_evidence_review"] = True
        with self.assertRaisesRegex(ValueError, "qualification"):
            disposition(a, b)

    def test_fake_new_future_families_rejected(self):
        a, b = self.fixture()
        b["prospective_future_source_families"] = 8
        with self.assertRaisesRegex(ValueError, "source-only"):
            disposition(a, b)

    def test_claim_of_independent_neural_replay_rejected(self):
        a, b = self.fixture()
        b["original_model_forwards_independently_attested"] = True
        with self.assertRaisesRegex(ValueError, "source-only"):
            disposition(a, b)

    def test_original_sha_drift_rejected(self):
        a, b = self.fixture()
        a["original_raw_journal_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "model or input"):
            disposition(a, b)

    def test_unmeasured_cost_remains_null(self):
        a, b = self.fixture()
        a["complete_lifecycle_cost_usd"] = 0
        with self.assertRaisesRegex(ValueError, "qualification"):
            disposition(a, b)


if __name__ == "__main__":
    unittest.main()
