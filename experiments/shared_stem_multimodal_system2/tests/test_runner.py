import json
from pathlib import Path
import tempfile
import unittest

from experiments.shared_stem_multimodal_system2 import runner


ROOT = Path(__file__).resolve().parents[3] / "experiments" / "shared_stem_multimodal_system2"


def load(name: str):
    return runner.read_json(ROOT / "config" / name)


def modality_row(arm_id: str, input_modality: str, output_modality: str, example_id: str):
    return {
        "run_id": "run-3",
        "arm_id": arm_id,
        "example_id": example_id,
        "split": "holdout",
        "status": "completed",
        "objective_digest": "0" * 64,
        "stem_digest": "1" * 64,
        "dataset_digest": "2" * 64,
        "host_profile_digest": "3" * 64,
        "measurement_interval_digest": "4" * 64,
        "seed": 7,
        "cell_count": 4,
        "training_budget": 100,
        "model_digest": "5" * 64,
        "preprocessor_digest": "6" * 64,
        "head_digest": "7" * 64,
        "input_modality": input_modality,
        "output_modality": output_modality,
        "task_utility": 0.8,
        "active_flops": 1000,
        "latency_ms": 10,
        "peak_rss_bytes": 100,
        "gpu_peak_bytes": 200,
        "retention_score": 0.9,
        "old_task_regression": 0.01,
        "task_success": True,
    }


class SharedStemRunnerTests(unittest.TestCase):
    def test_both_frozen_plans_validate_and_have_expected_arms(self):
        multimodal = runner.validate_config(load("multimodal_differentiation.v1.json"))
        ndu = runner.validate_config(load("ndu_system2_ablation.v1.json"))
        self.assertEqual({arm["id"] for arm in multimodal["arms"]}, set(runner.MODALITY_ARMS))
        self.assertEqual({arm["id"] for arm in ndu["arms"]}, set(runner.NDU_ARMS))

    def test_receipt_retains_failed_rows_and_reports_missing_arm(self):
        config = runner.validate_config(load("multimodal_differentiation.v1.json"))
        rows = [modality_row("text_text", "text", "text", "q1")]
        rows.append({
            "run_id": "run-3",
            "arm_id": "image_text",
            "example_id": "q2",
            "split": "holdout",
            "status": "failed",
            "objective_digest": "0" * 64,
            "stem_digest": "1" * 64,
            "dataset_digest": "2" * 64,
            "host_profile_digest": "3" * 64,
            "measurement_interval_digest": "4" * 64,
            "seed": 7,
            "cell_count": 4,
            "training_budget": 100,
            "model_digest": "5" * 64,
            "preprocessor_digest": "6" * 64,
            "head_digest": "7" * 64,
            "input_modality": "image",
            "output_modality": "text",
        })
        receipt = runner.make_receipt(config, rows, "a" * 64)
        image = next(item for item in receipt["result"]["arms"] if item["arm_id"] == "image_text")
        self.assertEqual(image["rows"], 1)
        self.assertEqual(image["completed_rows"], 0)
        self.assertEqual(image["status_counts"]["failed"], 1)
        self.assertEqual(receipt["result"]["disposition"], "insufficient_evidence")
        self.assertIn("audio_text", receipt["result"]["insufficient_arms"])
        self.assertIsNone(receipt["result"]["winner"])

    def test_system2_variant_is_bound_to_arm_and_receipt_replays(self):
        config = runner.validate_config(load("ndu_system2_ablation.v1.json"))
        rows = []
        for index, arm_id in enumerate(runner.NDU_ARMS):
            rows.append({
                "run_id": "run-4",
                "arm_id": arm_id,
                "example_id": "q1",
                "split": "holdout",
                "status": "completed",
                "objective_digest": "0" * 64,
                "stem_digest": "1" * 64,
                "dataset_digest": "2" * 64,
                "host_profile_digest": "3" * 64,
                "measurement_interval_digest": "4" * 64,
                "seed": 7,
                "cell_count": 4,
                "training_budget": 100,
                "model_digest": "5" * 64,
                "preprocessor_digest": "6" * 64,
                "head_digest": "7" * 64,
                "system2_variant": arm_id,
                "task_utility": 0.5,
                "active_flops": 1000,
                "latency_ms": 5 + index,
                "peak_rss_bytes": 100,
                "gpu_peak_bytes": 200,
                "retention_score": 1.0,
                "old_task_regression": 0.0,
            })
        receipt = runner.make_receipt(config, rows, "b" * 64)
        runner.verify_receipt(receipt, config, rows, "b" * 64)
        self.assertEqual(receipt["result"]["disposition"], "diagnostic_complete")
        self.assertEqual(receipt["authority"]["authority_delta"], "none")

    def test_invalid_modality_metadata_fails_closed(self):
        config = runner.validate_config(load("multimodal_differentiation.v1.json"))
        row = modality_row("text_text", "image", "text", "q1")
        with self.assertRaises(runner.ExperimentError):
            runner.validate_observation(row, config)

    def test_context_drift_and_receipt_tamper_fail_closed(self):
        config = runner.validate_config(load("multimodal_differentiation.v1.json"))
        first = modality_row("text_text", "text", "text", "q1")
        second = modality_row("image_text", "image", "text", "q1")
        second["stem_digest"] = "3" * 64
        with self.assertRaises(runner.ExperimentError):
            runner.make_receipt(config, [first, second], "c" * 64)
        receipt = runner.make_receipt(config, [first], "d" * 64)
        receipt["result"]["winner"] = "text_text"
        with self.assertRaises(runner.ExperimentError):
            runner.verify_receipt(receipt, config, [first], "d" * 64)

    def test_failure_stays_in_task_success_denominator(self):
        config = runner.validate_config(load("multimodal_differentiation.v1.json"))
        success = modality_row("text_text", "text", "text", "q1")
        failed = modality_row("text_text", "text", "text", "q2")
        failed["status"] = "failed"
        failed["task_success"] = False
        for metric in runner.REQUIRED_METRICS:
            failed.pop(metric, None)
        receipt = runner.make_receipt(config, [success, failed], "e" * 64)
        summary = next(item for item in receipt["result"]["arms"] if item["arm_id"] == "text_text")
        self.assertEqual(summary["task_success_rate"], 0.5)

    def test_resource_budget_violation_is_diagnostic_blocker(self):
        config = runner.validate_config(load("multimodal_differentiation.v1.json"))
        row = modality_row("text_text", "text", "text", "q1")
        row["latency_ms"] = config["budgets"]["max_latency_ms"] + 1
        receipt = runner.make_receipt(config, [row], "f" * 64)
        self.assertEqual(receipt["result"]["disposition"], "resource_budget_exceeded")
        self.assertEqual(receipt["result"]["budget_violations"], {"text_text": ["q1"]})

    def test_cli_writes_and_verifies_receipt(self):
        config_path = ROOT / "config" / "multimodal_differentiation.v1.json"
        rows = modality_row("text_text", "text", "text", "q1")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observations = root / "observations.jsonl"
            observations.write_text(json.dumps(rows) + "\n", encoding="utf-8")
            receipt = root / "receipt.json"
            self.assertEqual(runner.main(["run", str(config_path), str(observations), str(receipt)]), 0)
            self.assertEqual(runner.main(["verify", str(config_path), str(observations), str(receipt)]), 0)


if __name__ == "__main__":
    unittest.main()
