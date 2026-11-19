"""Contract tests for archived fresh-process V2 readback (no Torch in CI)."""
import copy
from pathlib import Path
import json
import unittest

from fresh_process_readback_v2 import (
    ORIGINAL_RESULT_SHA256, ORIGINAL_TRAINING_SCRIPT_SHA256,
    ARMS, SEEDS, check_rows, sha256,
)

ROOT = Path(__file__).resolve().parent


class FreshProcessReadbackTests(unittest.TestCase):
    def test_pinned_original_archive_and_source(self):
        self.assertEqual(sha256(ROOT / "real_cpu_clock_v2_RESULT.json"),
                         ORIGINAL_RESULT_SHA256)
        self.assertEqual(sha256(ROOT / "native_lora_clock_v2.py"),
                         ORIGINAL_TRAINING_SCRIPT_SHA256)

    def test_independent_process_archive_has_all_pairs_and_full_costs(self):
        data = json.loads((ROOT / "fresh_process_readback_v2_RESULT.json").read_text())
        self.assertEqual(data["original_result_sha256"], ORIGINAL_RESULT_SHA256)
        self.assertEqual(data["consumer_script_sha256"],
                         sha256(ROOT / "fresh_process_readback_v2.py"))
        self.assertEqual(data["fresh_process_evaluated_arms"], 8)
        self.assertEqual(data["fresh_process_task_forwards"], 96)
        self.assertEqual({(r["seed"], r["arm"]) for r in data["arms"]},
                         {(seed, arm) for seed in SEEDS for arm in ARMS})
        self.assertTrue(data["cpu_only"])
        self.assertEqual(data["authority"], "DENY_ALL")
        self.assertEqual(data["qualification"], "HOLD_NO_GO")
        self.assertGreater(data["full_consumer_wall_seconds"], 0)
        self.assertGreater(data["full_consumer_cpu_seconds"], 0)
        self.assertGreater(data["process_ru_maxrss_kib"], 0)
        self.assertLessEqual(max(max(r["max_B_p_yes_difference"],
                                     r["max_C_p_yes_difference"])
                                 for r in data["arms"]), 1e-5)
        archive = json.loads((ROOT / "real_cpu_clock_v2_RESULT.json").read_text())
        original = {(r["seed"], r["arm"]): r for r in archive["runs"]}
        for run in data["arms"]:
            old = original[(run["seed"], run["arm"])]
            self.assertEqual(run["B_accuracy"], old["scores"]["B_exposed_eval"]["accuracy"])
            self.assertEqual(run["C_accuracy"],
                             old["scores"]["C_operator_constructed"]["accuracy"])
            self.assertEqual(run["checkpoint_file_sha256"],
                {n: meta["sha256"] for n, meta in old["checkpoint_files"].items()})

    def test_row_identity_and_truth_tamper_rejected(self):
        rows = [{"id": "b", "truth": "yes", "prediction": "no",
                 "prompt_sha256": "a" * 64, "correct": False, "p_yes": 0.3}]
        self.assertEqual(check_rows(rows, rows), 0.0)
        for field, change in [("id", "different"), ("truth", "no"),
                              ("prediction", "yes"), ("prompt_sha256", "b" * 64),
                              ("correct", True)]:
            altered = copy.deepcopy(rows)
            altered[0][field] = change
            with self.subTest(field=field), self.assertRaises(ValueError):
                check_rows(altered, rows)
        with self.assertRaises(ValueError):
            check_rows([], rows)

    def test_probability_drift_and_missing_state_fail_closed(self):
        expected = [{"id": "q", "truth": "no", "prediction": "no",
                     "prompt_sha256": "a" * 64, "correct": True, "p_yes": 0.1}]
        changed = copy.deepcopy(expected)
        changed[0]["p_yes"] = 0.101
        with self.assertRaises(ValueError):
            check_rows(changed, expected)
        changed[0]["p_yes"] = 0.100000001
        self.assertLess(check_rows(changed, expected), 1e-5)


if __name__ == "__main__":
    unittest.main()

