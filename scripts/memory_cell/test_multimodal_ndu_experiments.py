import unittest

from multimodal_ndu_experiments import run_experiment
from experiments.shared_stem_multimodal_system2.runner import NDU_ARMS, MODALITY_ARMS, ExperimentError


def context():
    return {
        "objective_digest": "0" * 64,
        "stem_digest": "1" * 64,
        "dataset_digest": "2" * 64,
        "host_profile_digest": "3" * 64,
        "measurement_interval_digest": "4" * 64,
        "seed": 13,
        "cell_count": 4,
        "training_budget": 100,
    }


def metric_row(arm_id, example_id, **metadata):
    row = {
        "run_id": "smoke",
        "arm_id": arm_id,
        "example_id": example_id,
        "split": "holdout",
        "status": "completed",
        **context(),
        "task_utility": 0.5,
        "active_flops": 1000,
        "latency_ms": 10,
        "peak_rss_bytes": 100,
        "gpu_peak_bytes": 200,
        "retention_score": 1.0,
        "old_task_regression": 0.0,
        "model_digest": "5" * 64,
        "preprocessor_digest": "6" * 64,
        "head_digest": "7" * 64,
        "baseline_status": "completed",
        "baseline_id": "single-modality",
        "baseline_model_digest": "8" * 64,
        "baseline_preprocessor_digest": "9" * 64,
        "baseline_head_digest": "a" * 64,
        "baseline_task_utility": 0.4,
        "baseline_active_flops": 900,
        "baseline_latency_ms": 9,
        "baseline_peak_rss_bytes": 90,
        "baseline_gpu_peak_bytes": 190,
        "baseline_retention_score": 0.9,
        "baseline_old_task_regression": 0.01,
        **metadata,
    }
    return row


class MultimodalNduEntrypointTests(unittest.TestCase):
    def test_multimodal_receipt_contains_all_registered_arms(self):
        modalities = {
            "text_text": ("text", "text"),
            "image_text": ("image", "text"),
            "audio_text": ("audio", "text"),
            "video_text": ("video", "text"),
            "text_image": ("text", "image"),
            "text_audio": ("text", "audio"),
        }
        rows = [
            metric_row(arm, "q-1", input_modality=modalities[arm][0], output_modality=modalities[arm][1])
            for index, arm in enumerate(MODALITY_ARMS)
        ]
        receipt = run_experiment("multimodal_differentiation", rows)
        self.assertEqual(receipt["result"]["disposition"], "diagnostic_complete")
        self.assertEqual(receipt["authority"]["authority_delta"], "none")

    def test_ndu_receipt_rejects_mismatched_variant(self):
        rows = [metric_row(NDU_ARMS[0], "q-0", system2_variant=NDU_ARMS[1])]
        with self.assertRaises(ExperimentError):
            run_experiment("ndu_system2_ablation", rows)


if __name__ == "__main__":
    unittest.main()
