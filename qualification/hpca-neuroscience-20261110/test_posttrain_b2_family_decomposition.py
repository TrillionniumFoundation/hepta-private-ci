"""Controls for source-pinned family AUC decomposition (no model execution)."""
from __future__ import annotations
import copy
import unittest
from pathlib import Path
from posttrain_b2_family_decomposition import calculate, decompose_retained_rank
from posttrain_b2_rank import calculate as rank_calculate
from posttrain_b2_reaudit import load_original

HERE = Path(__file__).parent

class FamilyPairAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.original = load_original(HERE)
        cls.rank = rank_calculate(cls.manifest, cls.original)
        cls.report = calculate(cls.manifest, cls.original)

    def test_authority_and_evaluator_not_upgraded(self):
        self.assertEqual((self.report["authority"], self.report["qualification"]),
                         ("DENY_ALL", "HOLD_NO_GO"))
        self.assertIs(self.report["independent_evaluator"], False)
        self.assertIs(self.report["model_inference_reexecuted"], False)
        self.assertEqual(len(self.report["runs"]), 9)
        self.assertIn("not nine independent", self.report["interpretation"])

    def test_base_integer_partition(self):
        base = self.report["runs"][0]
        self.assertEqual((base["arm"], base["seed"]), ("frozen_base", 0))
        self.assertEqual(base["within_family"],
                         {"pairs": 180, "twice_wins": 136, "auc": 136 / 360})
        self.assertEqual(base["cross_family"],
                         {"pairs": 720, "twice_wins": 648, "auc": 648 / 1440})
        self.assertEqual(base["pooled_auc"], 784 / 1800)

    def test_all_nine_conditional_ranks_still_below_half(self):
        for r in self.report["runs"]:
            within, cross = r["within_family"], r["cross_family"]
            self.assertLess(within["auc"], cross["auc"])
            self.assertLess(within["auc"], .5)
            self.assertLess(cross["auc"], .5)
            self.assertEqual(within["pairs"] + cross["pairs"], 900)
            self.assertEqual(within["twice_wins"] + cross["twice_wins"],
                             self.rank["runs"][
                                 self.report["runs"].index(r)]["pooled"]["twice_wins"])

    def test_exact_four_seed_paired_roster(self):
        self.assertEqual([(x["arm"], x["seed"]) for x in self.report["runs"]],
                         [("frozen_base", 0)] +
                         [(arm, s) for s in (11, 17, 23, 29)
                          for arm in ("interleaved", "bursty")])

    def test_adversarial_authority_and_evaluator_forgery(self):
        for key, value in (("authority", "ALLOW"),
                           ("qualification", "GO"),
                           ("independent_evaluator", True),
                           ("model_inference_reexecuted", True)):
            mutated = copy.deepcopy(self.rank)
            mutated[key] = value
            with self.assertRaises(ValueError):
                decompose_retained_rank(mutated)

    def test_adversarial_roster_and_pair_count_drift(self):
        mutated = copy.deepcopy(self.rank)
        mutated["runs"][0]["families"].pop("even")
        with self.assertRaises(ValueError):
            decompose_retained_rank(mutated)
        for key, value in (("total_pairs", 901), ("twice_wins", 1900)):
            mutated = copy.deepcopy(self.rank)
            mutated["runs"][0]["pooled"][key] = value
            with self.assertRaises(ValueError):
                decompose_retained_rank(mutated)

    def test_original_probability_mutation_rejected(self):
        tampered = copy.deepcopy(self.original)
        tampered["runs"][0]["scores"]["rows"][0]["p_yes"] = .91
        with self.assertRaises(ValueError):
            calculate(self.manifest, tampered)

if __name__ == "__main__":
    unittest.main()
