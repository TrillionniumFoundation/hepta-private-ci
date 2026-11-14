import json
import subprocess
import sys
import unittest

from ndu_system2_orchestrator import CANDIDATES, run


class System2OrchestratorTests(unittest.TestCase):
    def test_same_seed_is_deterministic(self):
        self.assertEqual(run(17), run(17))
        self.assertNotEqual(run(17), run(18))
        payload = json.loads(
            subprocess.run(
                [sys.executable, "ndu_system2_orchestrator.py", "--seed", "17"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
        self.assertEqual(payload["seed"], 17)
        self.assertEqual(payload["authority"], "DENY_ALL")

    def test_end_to_end_receipt_and_support(self):
        result = run(17)
        decision = result["receipts"]["decision"]
        self.assertEqual(tuple(decision["candidates"]), CANDIDATES)
        self.assertEqual(set(decision["support"]), set(CANDIDATES))
        self.assertEqual(set(decision["propensity"]), set(CANDIDATES))
        self.assertAlmostEqual(sum(decision["propensity"].values()), 1.0)
        self.assertIn(decision["selected_action"], decision["support"])
        self.assertGreater(decision["propensity"][decision["selected_action"]], 0.0)
        self.assertEqual(result["receipts"]["pending_outcome"]["outcome"], None)
        self.assertEqual(result["receipts"]["observed_outcome"]["decision_id"], decision["decision_id"])

    def test_budget_and_tree_gap(self):
        result = run(17)
        self.assertTrue(result["budget"]["tree_constraints_ok"])
        self.assertLessEqual(
            result["budget"]["tree_global_spent"],
            result["budget"]["tree_initial"] - result["budget"]["tree_reserve"] + 1e-9,
        )
        self.assertTrue(result["tree"]["z_finite"])
        self.assertGreaterEqual(result["tree"]["local_composition_gap"], 0.0)
        self.assertTrue(result["tree"]["global_gap_detected"])

    def test_lineage_delayed_outcome_and_ope(self):
        result = run(17)
        lineage = result["cell"]["lineage"]
        self.assertEqual(result["candidate_snapshot_digest"], lineage["candidate_snapshot_digest"])
        self.assertTrue(lineage["candidate_predecessor_matches_initial"])
        self.assertEqual(len(lineage["parent_digest"]), 64)
        self.assertEqual(len(lineage["candidate_snapshot_digest"]), 64)

        delayed = result["ope"]["delayed_as_of_1"]
        self.assertFalse(delayed["valid"])
        self.assertIsNone(delayed["value"])
        self.assertTrue(result["ope"]["ips"]["valid"])
        self.assertTrue(result["ope"]["snips"]["valid"])
        self.assertTrue(result["ope"]["dr"]["valid"])
        self.assertEqual(result["ope"]["ips"]["n"], 1)
        self.assertGreater(result["ope"]["ess"], 0.0)

    def test_authority_is_fail_closed(self):
        result = run(23)
        self.assertEqual(result["protocol"]["mode"], "SHADOW_ONLY")
        self.assertEqual(result["protocol"]["authority"], "DENY_ALL")
        self.assertFalse(result["protocol"]["provider_dispatch"])
        self.assertFalse(result["protocol"]["real_model_call"])
        self.assertFalse(result["protocol"]["learned_fbsde"])


if __name__ == "__main__":
    unittest.main()
