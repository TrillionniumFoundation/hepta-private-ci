"""Adversarial checks for post-hoc four-arm learning/control credit audit."""
from copy import deepcopy
import json
import math
from pathlib import Path
import unittest

from factorial_credit_gate import audit_factorial, audit_frozen_file

REPORT = Path(__file__).with_name("development-report.json")


class CreditAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = json.loads(REPORT.read_text())

    def altered(self):
        return deepcopy(self.source)

    def test_exact_frozen_factorial_keeps_negative_science_visible(self):
        result = audit_frozen_file(REPORT)
        self.assertEqual([s["seed"] for s in result["per_seed"]], [17, 29, 43])
        self.assertAlmostEqual(result["seed_mean_interaction"], -0.021484375)
        self.assertAlmostEqual(result["seed_mean_joint_vs_base_loss"],
                               -0.24088541666666663)
        # The pooled mean loss improves, but the *seed-averaged CVaR* worsens.
        self.assertAlmostEqual(result["seed_mean_joint_vs_base_cvar90"],
                               0.05208333333333333)
        self.assertAlmostEqual(result["seed_mean_joint_vs_ndu_static_cvar90"],
                               0.3385416666666667)
        self.assertGreater(result["per_seed"][1][
            "control_effect_under_ndu_training"], 0)
        self.assertEqual(result["per_seed"][1]["factorial_interaction"], 0)
        self.assertEqual([r["joint_refine_rate"] for r in result["per_seed"]],
                         [0, 0, 0])
        self.assertFalse(any(result["gates"].values()))
        self.assertFalse(result["all_scientific_blockers_closed"])
        self.assertFalse(result["original_outcomes_independently_signed_here"])
        self.assertFalse(result["source_level_pairs_replayed_here"])
        self.assertEqual(len(result["input_sha256"]), 64)

    def test_per_seed_interaction_is_true_difference_in_differences(self):
        result = audit_factorial(self.source)
        for row in result["per_seed"]:
            self.assertAlmostEqual(row["factorial_interaction"], (
                row["control_effect_under_ndu_training"] -
                row["control_effect_under_supervised"]))
            self.assertAlmostEqual(row["train_effect_under_dynamic"] -
                                   row["train_effect_under_static"],
                                   row["factorial_interaction"])

    def test_reject_duplicated_training_seed(self):
        record = self.altered()
        record["seeds"][1]["seed"] = 17
        with self.assertRaisesRegex(ValueError, "seed census"):
            audit_factorial(record)

    def test_reject_missing_or_extra_arm_instead_of_silent_drop(self):
        record = self.altered()
        record["seeds"][0]["arms"].pop("ndu_risk|static")
        with self.assertRaisesRegex(ValueError, "unpaired"):
            audit_factorial(record)
        record = self.altered()
        record["seeds"][0]["arms"]["forged|arm"] = {}
        with self.assertRaisesRegex(ValueError, "unpaired"):
            audit_factorial(record)

    def test_reject_fake_query_rate_and_missing_cost(self):
        record = self.altered()
        record["seeds"][0]["arms"]["ndu_risk|ndu_contextual"]["query_rate"] = 0.0
        with self.assertRaisesRegex(ValueError, "query-rate"):
            audit_factorial(record)
        record = self.altered()
        record["seeds"][0]["arms"]["ndu_risk|ndu_contextual"]["mean_cost_units"] = 0
        with self.assertRaisesRegex(ValueError, "decoded-loss or modeled cost"):
            audit_factorial(record)

    def test_reject_invalid_tail_loss_and_boolean_metric(self):
        record = self.altered()
        record["seeds"][0]["arms"]["supervised|static"]["cvar90_loss"] = 0.001
        with self.assertRaisesRegex(ValueError, "decoded-loss or modeled cost"):
            audit_factorial(record)
        record = self.altered()
        record["seeds"][0]["arms"]["supervised|static"]["mean_loss"] = True
        with self.assertRaisesRegex(ValueError, "unsupported"):
            audit_factorial(record)

    def test_reject_nonfinite_objective_and_forged_success(self):
        record = self.altered()
        record["seeds"][0]["arms"]["ndu_risk|static"]["mean_loss"] = float("nan")
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            audit_factorial(record)
        record = self.altered()
        record["status"] = "PRODUCTION_READY"
        with self.assertRaisesRegex(ValueError, "scoped development"):
            audit_factorial(record)

    def test_reject_pseudoreplication_census_and_missing_head_forwards(self):
        record = self.altered()
        record["seeds"][2]["arms"]["ndu_risk|ndu_contextual"]["test_sources"] = 2048
        with self.assertRaisesRegex(ValueError, "census"):
            audit_factorial(record)
        record = self.altered()
        record["seeds"][2]["arms"]["ndu_risk|ndu_contextual"]["head_forward_calls"] = 0
        with self.assertRaisesRegex(ValueError, "census"):
            audit_factorial(record)


if __name__ == "__main__":
    unittest.main()
