"""Research-only original model receipt consistency adversarial regressions."""

import copy
import json
from pathlib import Path
import unittest

from source_delivered_local_receipt_gate import replay_published

DATA = (
    Path(__file__).resolve().parent
    / "data"
    / "source_delivered_original_local_20261016.json"
)


class LocalOriginalReaderResearchReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = json.loads(DATA.read_text())

    def fixture(self):
        return copy.deepcopy(self.original)

    def test_complete_exact_negative_original_model_receipt(self):
        record = replay_published(self.fixture())
        self.assertEqual(record["model_requests"], 48)
        self.assertEqual(record["independently_recounted_forwards"], 732)
        self.assertEqual(record["independent_program_rechecks"], 12)
        self.assertEqual(record["new_model_calls"], 0)
        self.assertFalse(record["production_qualified"])

    def test_no_evidence_refusal_and_answer_success_stay_distinct(self):
        report = self.fixture()
        self.assertEqual(report["observed"]["by_arm"]["empty"]["choice_correct"], 0)
        self.assertEqual(
            report["retrospective_refusal_ablation"]["by_arm"]["empty"][
                "fixed_refusal_correct"
            ],
            8,
        )
        self.assertEqual(replay_published(report)["model_requests"], 48)

    def test_no_evidence_forced_guess_or_fake_correct_refusal_rejected(self):
        for key, value in (
            ("posthoc_forced_guess_correct", 1),
            ("fixed_refusal_correct", 7),
            ("guess_unsupported", 1),
        ):
            with self.subTest(key=key):
                report = self.fixture()
                report["retrospective_refusal_ablation"]["by_arm"]["empty"][key] = value
                with self.assertRaisesRegex(ValueError, "no-evidence abstention"):
                    replay_published(report)

    def test_fabricated_historical_runtime_parity_denied(self):
        report = self.fixture()
        report["execution_provenance"][
            "original_experiment_runtime_pytorch_2_5_1_parity_verified"
        ] = True
        with self.assertRaisesRegex(ValueError, "canonical parity"):
            replay_published(report)

    def test_incomplete_physical_model_calls_denied(self):
        report = self.fixture()
        report["observed"]["actual_neural_forwards"] = 731
        with self.assertRaisesRegex(ValueError, "execution or replay inflated"):
            replay_published(report)

    def test_original_prompt_replay_mislabel_rejected(self):
        report = self.fixture()
        report["source_and_program_replay"][
            "conditional_log_probabilities_independently_recomputed"
        ] = True
        with self.assertRaisesRegex(ValueError, "mechanical replay misrepresented"):
            replay_published(report)

    def test_deleted_prerequisite_cannot_earn_task_success(self):
        report = self.fixture()
        report["observed"]["by_arm"]["without_prerequisite"]["supported_success"] = 4
        with self.assertRaisesRegex(ValueError, "task or actual program count drift"):
            replay_published(report)

    def test_retrospective_forced_guess_is_never_safe_adoption(self):
        report = self.fixture()
        report["retrospective_refusal_ablation"]["safe_refusal_rule_validated"] = True
        with self.assertRaisesRegex(ValueError, "posthoc refusal analysis promoted"):
            replay_published(report)

    def test_refusal_score_tamper_denied(self):
        report = self.fixture()
        report["retrospective_refusal_ablation"]["by_arm"]["hybrid"][
            "posthoc_forced_guess_correct"
        ] = 6
        with self.assertRaisesRegex(ValueError, "posthoc refusal recomputation"):
            replay_published(report)

    def test_false_training_or_future_families_denied(self):
        report = self.fixture()
        report["interpretation"]["independent_future_source_families"] = 8
        with self.assertRaisesRegex(ValueError, "scope-cost-production"):
            replay_published(report)

    def test_original_source_sha_mismatch_denied(self):
        report = self.fixture()
        report["execution_provenance"]["original_input_zip_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "canonical parity"):
            replay_published(report)

    def test_overstated_program_checks_denied(self):
        report = self.fixture()
        report["source_and_program_replay"][
            "original_program_worker_execution_replays"
        ] = 48
        with self.assertRaisesRegex(ValueError, "mechanical replay"):
            replay_published(report)


if __name__ == "__main__":
    unittest.main()
