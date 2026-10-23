"""Non-authorizing policy ablation tests."""

import unittest
from copy import deepcopy

import portfolio_policy as p
from ndu_dmgp import EvidenceError


def scenario():
    context = {
        "objective_digest": "obj-1", "selected_snapshot_digest": "snapshot-1",
        "state_digest": "state-1", "remaining_compute_units": 8,
        "minimum_predicted_quality": 0.6, "terminal_requirements_satisfied": False,
        "default_action_id": "A", "risk_aversion": 0.5, "kl_penalty": 0.2,
    }
    def action(id, cost, quality, now, future):
        return {"id": id, "compute_units": cost, "predicted_quality": quality,
                "instant_ndu": now, "recursive_ndu": future,
                "authorized": True, "hard_constraints_ok": True,
                "objective_digest": "obj-1", "snapshot_digest": "snapshot-1"}
    actions = [action("A", 5, .7, .3, .2), action("B", 4, .9, .2, .7),
               action("C", 8, .9, .4, .5), action("abstain", 0, 1, 0, 0)]
    covariance = {"qualified": True, "state_digest": "state-1",
                  "action_ids": ["A", "B", "C"],
                  "diagonal": [.3, .2, .4], "factors": [[.1, .2, .1]]}
    return context, actions, covariance


class PolicyReferenceTests(unittest.TestCase):
    def test_all_ablation_arms_advisory_and_stable(self):
        ctx, acts, cov = scenario()
        for arm in p.ARMS:
            first = p.choose(arm, ctx, acts, cov)
            self.assertTrue(first["advisory_only"])
            self.assertEqual(first, p.choose(arm, ctx, acts, cov))
            self.assertAlmostEqual(sum(first["probabilities"].values()), 1.0, places=12)
            self.assertNotIn("abstain", first["probabilities"])
            self.assertEqual(first["evaluated_arm"], arm)

    def test_modes_have_distinct_reference_actions(self):
        ctx, acts, cov = scenario()
        self.assertEqual(p.choose("A0", ctx, acts, cov)["probabilities"], {"A": 1.0})
        self.assertEqual(p.choose("A1", ctx, acts, cov)["probabilities"], {"B": 1.0})
        self.assertEqual(p.choose("A2", ctx, acts, cov)["probabilities"], {"B": 1.0})
        self.assertEqual(p.choose("A3", ctx, acts, cov)["probabilities"], {"C": 1.0})
        x4 = p.choose("A4", ctx, acts, cov)["probabilities"]
        x5 = p.choose("A5", ctx, acts, cov)["probabilities"]
        self.assertNotEqual(x4, x5)
        self.assertGreater(x5["B"], x4["B"])

    def test_missing_risk_support_falls_back_to_deterministic_ndu(self):
        ctx, acts, cov = scenario()
        cov["qualified"] = False
        fallback = p.choose("A5", ctx, acts, cov)
        self.assertEqual(fallback["evaluated_arm"], "A3")
        self.assertEqual(fallback["probabilities"], {"C": 1.0})
        self.assertIn("fallback", fallback["reason"])

    def test_wrong_action_covariance_order_falls_back(self):
        ctx, acts, cov = scenario()
        cov["action_ids"] = ["C", "A", "B"]
        self.assertEqual(p.choose("A4", ctx, acts, cov)["evaluated_arm"], "A3")

    def test_wrong_state_covariance_falls_back(self):
        ctx, acts, cov = scenario()
        cov["state_digest"] = "future-injected-state"
        self.assertEqual(p.choose("A5", ctx, acts, cov)["evaluated_arm"], "A3")

    def test_unauthorized_high_ndu_excluded(self):
        ctx, acts, cov = scenario()
        acts[2]["authorized"] = False
        self.assertEqual(p.choose("A3", ctx, acts)["probabilities"], {"A": 1.0})

    def test_budget_filters_before_utility_scoring(self):
        ctx, acts, cov = scenario()
        ctx["remaining_compute_units"] = 4
        self.assertEqual(p.choose("A3", ctx, acts)["probabilities"], {"B": 1.0})

    def test_ineligible_stop_filtered(self):
        ctx, acts, cov = scenario()
        acts.append({"id": "stop", "compute_units": 0, "predicted_quality": 1,
                     "instant_ndu": 1, "recursive_ndu": 1,
                     "authorized": True, "hard_constraints_ok": True,
                     "objective_digest": "obj-1", "snapshot_digest": "snapshot-1"})
        self.assertEqual(p.choose("A3", ctx, acts)["probabilities"], {"C": 1.0})
        ctx["terminal_requirements_satisfied"] = True
        self.assertEqual(p.choose("A3", ctx, acts)["probabilities"], {"stop": 1.0})

    def test_no_feasible_action_explicit_abstain(self):
        ctx, acts, cov = scenario()
        ctx["remaining_compute_units"] = 0
        self.assertEqual(p.choose("A5", ctx, acts, cov)["probabilities"], {"abstain": 1.0})

    def test_missing_abstain_rejected(self):
        ctx, acts, cov = scenario()
        acts = [x for x in acts if x["id"] != "abstain"]
        with self.assertRaisesRegex(EvidenceError, "abstain"):
            p.choose("A0", ctx, acts)

    def test_objective_mismatch_rejected(self):
        ctx, acts, cov = scenario()
        acts[1]["objective_digest"] = "goal-rewrite"
        with self.assertRaisesRegex(EvidenceError, "mixed objective"):
            p.choose("A5", ctx, acts, cov)

    def test_overflow_or_nan_rejected(self):
        ctx, acts, cov = scenario()
        acts[1]["compute_units"] = float('nan')
        with self.assertRaisesRegex(EvidenceError, "compute_units"):
            p.choose("A5", ctx, acts, cov)


if __name__ == "__main__":
    unittest.main()
