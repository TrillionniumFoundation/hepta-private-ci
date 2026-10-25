"""Independent synthetic factorial and metric checks; no real data or model execution."""

import unittest
import numpy as np
from .statistics import analyze, paired_cube, score_observation, upper_tail
from .test_support import plan, synthetic_rows


class FactorialStatisticsTests(unittest.TestCase):
    def test_known_factorial_effects_and_fixed_seed_unit(self):
        protocol = plan()
        result = analyze(synthetic_rows(protocol), protocol)
        for name, expected in (("base_main_effect", -.11), ("gate_main_effect", -.05), ("interaction", -.02)):
            self.assertAlmostEqual(result["primary"][name]["estimate"], expected, places=12)
            np.testing.assert_allclose(result["primary"][name]["interval"], [expected, expected], rtol=0, atol=1e-14)
        self.assertEqual(result["bootstrap"]["source_pairs"], 60)
        self.assertIsNone(result["primary"]["interaction"]["main_effect_improvement"])
        self.assertEqual(result["bootstrap"]["quantiles"], [.05 / 6, 1 - .05 / 6])

    def test_no_duplicate_missing_or_cross_case_source_reuse(self):
        protocol = plan()
        rows = synthetic_rows(protocol)
        for bad in (rows[:-1], rows[:-1] + [rows[0]]):
            with self.assertRaises(ValueError):
                paired_cube(bad, protocol)
        rows[0]["source_ids"] = rows[1]["source_ids"][:1] * 2
        with self.assertRaises(ValueError):
            paired_cube(rows, protocol)

    def test_positive_main_effect_not_called_improvement(self):
        protocol, rows = plan(), synthetic_rows(plan())
        for row in rows:
            row["metrics"]["joint_loss"] = 1 - row["metrics"]["joint_loss"]
        primary = analyze(rows, protocol)["primary"]
        self.assertFalse(primary["base_main_effect"]["main_effect_improvement"])
        self.assertEqual(primary["base_main_effect"]["direction"], "positive")

    def test_nonfinite_loss_or_inconsistent_corruption_fails(self):
        for field, value in (("joint_loss", float("nan")), ("joint_fact_correct", .5)):
            rows = synthetic_rows(plan())
            rows[0]["metrics"][field] = value
            with self.assertRaises(ValueError):
                analyze(rows, plan())
        rows = synthetic_rows(plan())
        rows[0]["corruption"] = "wrong_hint"
        with self.assertRaises(ValueError):
            analyze(rows, plan())

    def test_metric_partial_credit_invalid_caption_and_mse(self):
        zero = np.zeros((1, 1, 28, 56), np.float32)
        half = np.full_like(zero, .5)
        exact = score_observation(zero, "left 2 right 7 relation less", [2, 7], zero, [2, 7])
        self.assertEqual(exact["joint_loss"], 0)
        self.assertEqual(exact["joint_fact_correct"], 1)
        wrong = score_observation(half, "left 2 right 8 relation greater", [2, 7], zero, [2, 7])
        self.assertAlmostEqual(wrong["joint_loss"], .15 + .15 + .05 + .025)
        bad = score_observation(zero, "left 2 right 7 relation less extra", [2, 7], zero, [2, 7])
        self.assertFalse(bad["caption_valid"])
        self.assertAlmostEqual(bad["joint_loss"], .55)
        self.assertEqual(upper_tail([1, .5, 0], .5), (1 + .25) / 1.5)

if __name__ == "__main__":
    unittest.main()
