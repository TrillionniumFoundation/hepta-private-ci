import json
import subprocess
import sys
import unittest

from short_horizon_fbsde_tree import run


class ShortHorizonTreeTests(unittest.TestCase):
    def test_seed_and_cli_are_deterministic(self):
        self.assertEqual(run(17), run(17))
        self.assertNotEqual(run(17), run(18))
        payload = json.loads(subprocess.run([sys.executable, "short_horizon_fbsde_tree.py", "--seed", "17"], check=True, capture_output=True, text=True).stdout)
        self.assertEqual(payload["seed"], 17)

    def test_z_is_finite_and_shadow_only(self):
        result = run(17)
        self.assertTrue(result["z_finite"])
        self.assertEqual(result["protocol"]["mode"], "SHADOW_ONLY")
        self.assertEqual(result["protocol"]["authority"], "DENY_ALL")
        self.assertFalse(result["protocol"]["learned_fbsde"])

    def test_budget_constraint(self):
        result = run(17, budget=4.0, reserve_budget=0.5)
        self.assertLessEqual(result["global"]["spent"], 3.5 + 1e-9)
        self.assertLessEqual(result["composed"]["spent"], 3.5 + 1e-9)
        self.assertGreaterEqual(result["budget"]["global_remaining"], 0.5 - 1e-9)
        self.assertGreaterEqual(result["budget"]["local_remaining"], 0.5 - 1e-9)
        self.assertTrue(result["budget"]["constraints_ok"])

    def test_composition_gap_is_reported(self):
        result = run(17)
        self.assertGreaterEqual(result["local_composition_gap"], 0.0)
        self.assertGreaterEqual(result["global"]["value"], result["composed"]["value"])
        self.assertTrue(result["global_gap_detected"])
        self.assertTrue(result["global"]["path"])
        self.assertTrue(result["composed"]["path"])


if __name__ == "__main__":
    unittest.main()
