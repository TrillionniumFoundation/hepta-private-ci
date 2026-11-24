import copy
import unittest

from acceptance import ARMS, COMMON, RESOURCES, adopted_rate, circuit_controls, scale_pair


def point(curve, users=1, workers=1, factor=1):
    return dict({k: "pinned" for k in COMMON}, curve=curve, users=users, workers=workers,
                data_sha256="data", roster_sha256="roster",
                budget={k: 100 * factor for k in RESOURCES}, used={k: 10 for k in RESOURCES})


class AcceptanceTests(unittest.TestCase):
    def test_user_and_worker_axes_cannot_be_relabelled(self):
        a, b = point("fixed_total"), point("fixed_total", users=4)
        self.assertTrue(scale_pair("fixed_total", a, b)["intervention_consistent"])
        with self.assertRaisesRegex(ValueError, "relabeling"):
            scale_pair("fixed_per_user", a, b)
        a["curve"] = b["curve"] = "fixed_per_user"
        with self.assertRaisesRegex(ValueError, "per-user"):
            scale_pair("fixed_per_user", a, b)
        b = point("fixed_per_user", users=4, factor=4)
        scale_pair("fixed_per_user", a, b)
        a, b = point("fixed_data_workers"), point("fixed_data_workers", workers=2)
        scale_pair("fixed_data_workers", a, b)
        b["data_sha256"] = "other"
        with self.assertRaisesRegex(ValueError, "data or roster"):
            scale_pair("fixed_data_workers", a, b)

    def test_missing_ablation_tie_or_more_budget_never_establishes_advantage(self):
        self.assertEqual(circuit_controls({})["status"], "BLOCKED")
        arms = {name: dict(point("unused"), outcomes={"task": name == "learned"},
                           old_parent_passes_lost=0, original_receipts_sha256="test-only") for name in ARMS}
        self.assertEqual(circuit_controls(arms)["scientific_qualification"], "UNVERIFIED")
        tied = copy.deepcopy(arms)
        tied["fixed"]["outcomes"] = {"task": True}
        self.assertIn("fixed:no_strict_advantage", circuit_controls(tied)["reasons"])
        del tied["message_shuffled"]
        self.assertIn("message_shuffled", circuit_controls(tied)["missing"])
        arms["learned"]["budget"]["training_cpu_ns"] += 1
        with self.assertRaisesRegex(ValueError, "unequal"):
            circuit_controls(arms)

    def test_json_claims_and_incomplete_cost_cannot_unlock_rate(self):
        row = dict(complete_total_cost=True, total_cost={"amount": 10, "unit": "development_units"},
                   improvement_id="test-only", site_attested_independent_adopted_improvements=1)
        self.assertIsNone(adopted_rate([row]))
        self.assertIsNone(adopted_rate([dict(row, complete_total_cost=False)], lambda r: True))
        self.assertIsNone(adopted_rate([row], lambda r: False))
        rate = adopted_rate([row, row], lambda r: True)  # a stub tests arithmetic, never authorizes work
        self.assertEqual((rate["unique_site_attested_improvements"], rate["total_cost"]), (1, 20))


if __name__ == "__main__":
    unittest.main()
