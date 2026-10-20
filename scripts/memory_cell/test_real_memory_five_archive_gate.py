"""Exact original generation evidence is required before any research promotion."""

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from real_memory_five_archive_gate import analyze, pairs

ARCHIVES = os.environ.get("HEPTA_REAL_READER_ARCHIVES")


class RealEvidenceGateTests(unittest.TestCase):
    def test_actual_pairs_do_not_average_independent_samples(self):
        group = {
            "a": {"hybrid": False, "entity_time": True},
            "b": {"hybrid": True, "entity_time": True},
            "c": {"hybrid": True, "entity_time": False},
        }
        self.assertEqual(
            pairs(group, "hybrid", "entity_time"),
            dict(wins=1, losses=1, ties=1, delta=0.0),
        )

    @unittest.skipUnless(ARCHIVES, "the five original model ZIPs are not mounted")
    def test_complete_actual_five_archive_recomputation(self):
        root = Path(ARCHIVES)
        result = analyze(
            root / "source.zip",
            root / "smol.zip",
            root / "qwen.zip",
            root / "strong.zip",
            root / "replay.zip",
        )
        self.assertEqual(result["actual_inference_records"], 208)
        self.assertEqual(result["original_reader_pairs"], 48)
        self.assertEqual(result["independent_program_worker_reexecutions"], 24)
        self.assertEqual(result["stage1"]["ablation_answer_removed"], 4)
        self.assertEqual(result["stage1"]["qwen_organized_success"], 8)
        self.assertEqual(
            result["stage2"]["organized_extra_correct_over_entity_time"], 0
        )
        self.assertFalse(result["production_accepted"])

    @unittest.skipUnless(ARCHIVES, "the five original model ZIPs are not mounted")
    def test_wrong_archive_sha_rejected_before_any_benchmark_claim(self):
        root = Path(ARCHIVES)
        with patch(
            "real_memory_five_archive_gate.MODELS",
            {"smol-1.7b": "0" * 64, "qwen-3b": "0" * 64},
        ):
            with self.assertRaisesRegex(ValueError, "wrong immutable archive"):
                analyze(
                    root / "source.zip",
                    root / "smol.zip",
                    root / "qwen.zip",
                    root / "strong.zip",
                    root / "replay.zip",
                )


if __name__ == "__main__":
    unittest.main()
