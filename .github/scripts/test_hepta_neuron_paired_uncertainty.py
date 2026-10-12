"""Synthetic negative tests; this module never sees production labels."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from hepta_neuron_paired_uncertainty import (
    InvalidPairedUncertainty,
    paired_cluster_interval,
)


class PairedClusterUncertaintyTests(unittest.TestCase):
    def test_insufficient_source_groups_do_not_fake_precision(self):
        result = paired_cluster_interval(
            [("episode-one", 1), ("episode-one", 1), ("episode-two", -1)],
            seed_identity="frozen/test/holdout", unit="accuracy",
        )
        self.assertIsNone(result["lower"])
        self.assertIsNone(result["upper"])
        self.assertEqual(result["independent_source_groups"], 2)
        self.assertEqual(result["paired_events"], 3)
        self.assertFalse(result["significance_or_promotion_claim"])

    def test_cluster_bootstrap_is_bounded_order_invariant_and_reproducible(self):
        pairs = [(f"group-{i}", 1 if i < 5 else (-1 if i == 5 else 0)) for i in range(12)]
        a = paired_cluster_interval(pairs, seed_identity="signed-cohort/typed/future_1", unit="accuracy")
        b = paired_cluster_interval(list(reversed(pairs)), seed_identity="signed-cohort/typed/future_1", unit="accuracy")
        self.assertEqual(a, b)
        self.assertEqual(a["resamples"], 1024)
        self.assertGreaterEqual(a["point_estimate"], a["lower"])
        self.assertLessEqual(a["point_estimate"], a["upper"])
        self.assertGreaterEqual(a["lower"], -1)
        self.assertLessEqual(a["upper"], 1)

    def test_source_group_is_resampled_as_entire_cluster(self):
        pairs = [("one", 1)] * 100 + [(f"other-{i}", -1) for i in range(7)]
        report = paired_cluster_interval(pairs, seed_identity="signed-cohort/laya/future_2", unit="accuracy")
        self.assertEqual(report["paired_events"], 107)
        self.assertEqual(report["independent_source_groups"], 8)
        self.assertAlmostEqual(report["point_estimate"], 93 / 107)
        self.assertIsNotNone(report["upper"])
        self.assertGreater(report["upper"], report["lower"])

    def test_mse_direction_and_source_groups(self):
        pairs = [(f"group-{i}", -0.04) for i in range(10)]
        result = paired_cluster_interval(pairs, seed_identity="heads/swiglu/future_2", unit="mse")
        self.assertEqual(result["benefit_when"], "negative")
        self.assertEqual(result["point_estimate"], -0.04)
        self.assertFalse(result["significance_or_promotion_claim"])

    def test_reject_forged_units_nonfinite_and_invalid_source(self):
        cases = [
            ([("good", float("nan"))], "accuracy"),
            ([("good", float("inf"))], "mse"),
            ([("bad/name", 0)], "mse"),
            ([("good", True)], "accuracy"),
            ([("good", 2)], "accuracy"),
            ([("good", 300)], "mse"),
            ([("good", 0, 0)], "mse"),
            ([], "mse"),
        ]
        for rows, unit in cases:
            with self.subTest(rows=rows, unit=unit):
                with self.assertRaises(InvalidPairedUncertainty):
                    paired_cluster_interval(rows, seed_identity="frozen", unit=unit)
        with self.assertRaises(InvalidPairedUncertainty):
            paired_cluster_interval([("group", 0)], seed_identity="frozen", unit="unknown")

    def test_bounded_group_cardinality(self):
        with self.assertRaises(InvalidPairedUncertainty):
            paired_cluster_interval([("same-group", 0)] * 4097, seed_identity="frozen", unit="accuracy")


if __name__ == "__main__":
    unittest.main()
