"""Source-pinned arithmetic and adversarial invariants, not new model tests."""
from __future__ import annotations

import copy
import unittest
from pathlib import Path

from posttrain_b2_rank import calculate, rank_counts
from posttrain_b2_reaudit import load_original


HERE = Path(__file__).parent


class RetainedRankTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest, cls.original = load_original(HERE)
        cls.report = calculate(cls.manifest, cls.original)

    def test_all_original_nine_runs_present_and_held(self):
        runs = self.report["runs"]
        self.assertEqual(len(runs), 9)
        self.assertEqual([(r["arm"], r["seed"]) for r in runs],
                         [("frozen_base", 0)] + [
                             (arm, s) for s in (11, 17, 23, 29)
                             for arm in ("interleaved", "bursty")])
        self.assertFalse(self.report["independent_evaluator"])
        self.assertFalse(self.report["model_inference_reexecuted"])
        self.assertEqual(self.report["authority"], "DENY_ALL")
        self.assertEqual(self.report["qualification"], "HOLD_NO_GO")

    def test_exact_base_pair_counts_and_classes(self):
        base = self.report["runs"][0]["pooled"]
        self.assertEqual((base["yes"], base["no"], base["total_pairs"]),
                         (30, 30, 900))
        self.assertEqual(base["twice_wins"], 784)
        self.assertLess(base["max_p_yes"], 0.5)
        self.assertLess(base["mean_p_yes_true_yes"],
                        base["mean_p_yes_true_no"])

    def test_all_nine_pooled_ranking_below_half(self):
        for row in self.report["runs"]:
            self.assertLess(row["pooled"]["auc"], .5)
            self.assertLess(row["pooled"]["max_p_yes"], .5)

    def test_family_heterogeneity_is_retained_not_smoothed(self):
        for row in self.report["runs"]:
            family = row["families"]
            self.assertEqual(set(family),
                             {"comparison", "divisibility", "even",
                              "prime", "set_membership"})
            for x in family.values():
                self.assertEqual((x["yes"], x["no"], x["total_pairs"]),
                                 (6, 6, 36))
            self.assertLess(family["comparison"]["auc"], .5)
            self.assertGreater(family["divisibility"]["auc"], .5)

    def test_order_and_strict_monotone_transform_invariance(self):
        rows = self.original["runs"][0]["scores"]["rows"]
        expected = rank_counts(rows)["twice_wins"]
        self.assertEqual(rank_counts(list(reversed(rows)))["twice_wins"],
                         expected)
        transformed = [
            {**row, "p_yes": row["p_yes"]**2} for row in rows
        ]
        self.assertEqual(rank_counts(transformed)["twice_wins"], expected)

    def test_label_reversal_inverts_auc(self):
        rows = self.original["runs"][0]["scores"]["rows"]
        flipped = [
            {**row, "truth": "no" if row["truth"] == "yes" else "yes"}
            for row in rows
        ]
        one = rank_counts(rows)
        other = rank_counts(flipped)
        self.assertEqual(one["twice_wins"] + other["twice_wins"],
                         2 * one["total_pairs"])

    def test_tied_scores_exact_half_credit(self):
        rows = [{"truth": "yes", "p_yes": .3},
                {"truth": "no", "p_yes": .3}]
        out = rank_counts(rows)
        self.assertEqual((out["twice_wins"], out["total_pairs"], out["auc"]),
                         (1, 1, .5))

    def test_unbalanced_and_invalid_probabilities_fail(self):
        for rows in (
            [{"truth": "yes", "p_yes": .4}],
            [{"truth": "yes", "p_yes": .4},
             {"truth": "no", "p_yes": float("nan")}],
            [{"truth": "yes", "p_yes": 0.0},
             {"truth": "no", "p_yes": .4}],
        ):
            with self.assertRaises(ValueError):
                rank_counts(rows)

    def test_original_score_or_label_mutation_is_rejected(self):
        changed = copy.deepcopy(self.original)
        changed["runs"][0]["scores"]["rows"][0]["p_yes"] = .75
        with self.assertRaises(ValueError):
            calculate(self.manifest, changed)
        changed = copy.deepcopy(self.original)
        target = changed["runs"][0]["scores"]["rows"][0]
        target["truth"] = "yes" if target["truth"] == "no" else "no"
        with self.assertRaises(ValueError):
            calculate(self.manifest, changed)


if __name__ == "__main__":
    unittest.main()
