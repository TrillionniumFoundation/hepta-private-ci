"""Pure parser/feature-contract tests; no model weights or device qualification."""
from __future__ import annotations

import unittest

from run_laya import choice_question, result_row
from run_heads import row_texts


class DriverContractTests(unittest.TestCase):
    def setUp(self):
        self.row = {"case_id": "e7", "state": {"text": "hello"}, "question": "Where?",
                    "labels": ["a", "b"], "criteria": {"a": "North", "b": "South"},
                    "label": "a", "group_id": "confidential", "ood": True}

    def test_laya_prompt_excludes_gold_label_and_private_group(self):
        question = choice_question(self.row)
        self.assertEqual(question["decision"]["criteria"], {"a": "North", "b": "South"})
        self.assertNotIn("label", str(question))
        self.assertNotIn("confidential", str(question))

    def test_shared_head_prompt_excludes_gold_label(self):
        prompts = row_texts(self.row)
        self.assertEqual(len(prompts), 2)
        self.assertTrue(all("confidential" not in text for text in prompts))
        self.assertTrue(all('"label"' not in text for text in prompts))

    def test_laya_abstention_and_gpu_unknown(self):
        result = result_row(self.row, {"probabilities": {"a": .65, "b": .35}},
                            elapsed_ms=4.5, rss=12345, host_id="local", device="cpu",
                            weights_sha256="a" * 64, calibration_sha256="b" * 64,
                            threshold=.8, gpu_allocator_peak=None)
        self.assertTrue(result["abstained"])
        self.assertIsNone(result["gpu_peak_bytes"])
        self.assertEqual(result["model_weights_sha256"], "a" * 64)

    def test_laya_malformed_schema_rejected(self):
        with self.assertRaisesRegex(ValueError, "schema"):
            result_row(self.row, {"probabilities": {"a": 1.0}}, elapsed_ms=2,
                       rss=123, host_id="local", device="cpu", weights_sha256="a" * 64,
                       calibration_sha256="b" * 64,
                       threshold=.5, gpu_allocator_peak=None)

    def test_encoder_prompt_labels_mismatch_rejected(self):
        bad = dict(self.row, criteria={"x": "not one of the labels"})
        with self.assertRaisesRegex(ValueError, "criteria"):
            row_texts(bad)


if __name__ == "__main__":
    unittest.main()
