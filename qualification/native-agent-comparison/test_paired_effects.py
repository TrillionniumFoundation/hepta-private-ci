import unittest
from paired_effects import paired_effects_by_scale


def pairs_for(scales=(64, 4096)):
    tasks = [{"task_id": "t1", "seed": 7}, {"task_id": "t2", "seed": 8}]
    actual = {}
    for scale in scales:
        for task in tasks:
            for mode in ("A", "B", "C"):
                actual[(task["task_id"], task["seed"], scale, mode)] = {
                    "task_success": True,
                    "tool_correct": True,
                    "recovery_pass": True,
                    "wall_ms": 100.0,
                    "peak_rss_bytes": 1_000_000,
                    "input_tokens": 20,
                    "output_tokens": 10,
                    "tool_calls": 2,
                }
    return tasks, actual


class PairedEffectsTests(unittest.TestCase):
    def test_4096_native_failure_cannot_be_masked_by_small_scales(self):
        tasks, actual = pairs_for()
        case = actual[("t1", 7, 4096, "C")]
        case["task_success"] = False
        case["wall_ms"] = 400.0
        case["peak_rss_bytes"] = 6_000_000
        result = paired_effects_by_scale(tasks, actual, (64, 4096))
        native = result["4096"]["C_vs_B"]
        self.assertTrue(native["any_paired_quality_regression"])
        self.assertEqual(native["quality"]["task_success"]["reference_only_passes"], 1)
        self.assertEqual(native["quality"]["task_success"]["paired_delta_percentage_points"], -50.0)
        self.assertEqual(native["mean_resource_delta_C_minus_reference"]["wall_ms"], 150.0)
        self.assertEqual(native["mean_resource_delta_C_minus_reference"]["peak_rss_bytes"], 2_500_000)
        self.assertFalse(result["64"]["C_vs_B"]["any_paired_quality_regression"])
        self.assertFalse(native["independent_measurement_proven"])
        self.assertFalse(native["statistical_significance_proven"])

    def test_comparisons_preserve_pair_identity_and_delta_sign(self):
        tasks, actual = pairs_for()
        actual[("t1", 7, 64, "A")]["task_success"] = False
        actual[("t2", 8, 64, "B")]["task_success"] = False
        actual[("t1", 7, 64, "C")]["input_tokens"] = 13
        a = paired_effects_by_scale(tasks, actual, (64,))["64"]["C_vs_A"]
        b = paired_effects_by_scale(tasks, actual, (64,))["64"]["C_vs_B"]
        self.assertEqual(a["quality"]["task_success"]["native_only_passes"], 1)
        self.assertEqual(b["quality"]["task_success"]["native_only_passes"], 1)
        self.assertEqual(a["quality"]["task_success"]["paired_delta_percentage_points"], 50.0)
        self.assertEqual(b["mean_resource_delta_C_minus_reference"]["input_tokens"], -3.5)
        self.assertFalse(a["any_paired_quality_regression"])

    def test_empty_cohort_is_invalid(self):
        with self.assertRaisesRegex(ValueError, "nonempty"):
            paired_effects_by_scale([], {}, (64,))


if __name__ == "__main__":
    unittest.main()
