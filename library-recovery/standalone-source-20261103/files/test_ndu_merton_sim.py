import json
import subprocess
import sys
import unittest

from ndu_merton_sim import default_accounts, gibbs_portfolio, run


class PortfolioTests(unittest.TestCase):
    def test_budget_and_probability_constraints(self):
        for _, (budget, reserve, assets, cov) in default_accounts().items():
            weights, stopped, _ = gibbs_portfolio(
                assets, cov, budget, reserve, gamma=1.2, temperature=0.18,
                cost_shadow=0.06, stop_utility=0.05,
            )
            self.assertTrue(all(p >= 0.0 for p in weights))
            self.assertLessEqual(sum(weights), 1.0 + 1e-9)
            cost = sum(p * a.cost for p, a in zip(weights, assets))
            self.assertLessEqual(cost, budget - reserve + 1e-9)
            self.assertIsInstance(stopped, bool)

    def test_seed_is_deterministic(self):
        self.assertEqual(run(17), run(17))
        self.assertNotEqual(run(17), run(18))

    def test_stop_boundary(self):
        assets = default_accounts()["inference"][2]
        cov = default_accounts()["inference"][3]
        bad = [type(a)(a.name, a.kind, -1.0, a.cost, a.prior) for a in assets]
        weights, stopped, objective = gibbs_portfolio(
            bad, cov, 12.0, 1.5, gamma=1.2, temperature=0.18,
            cost_shadow=0.06, stop_utility=0.05,
        )
        self.assertTrue(stopped)
        self.assertEqual(weights, [0.0] * len(assets))
        self.assertEqual(objective, 0.05)

    def test_cli_emits_json(self):
        proc = subprocess.run(
            [sys.executable, "ndu_merton_sim.py", "--seed", "17"],
            check=True, capture_output=True, text=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["seed"], 17)
        self.assertEqual(len(payload["accounts"]), 3)
        for account in payload["accounts"]:
            self.assertAlmostEqual(
                account["active_mass"] + account["unallocated_mass"], 1.0, places=7
            )


if __name__ == "__main__":
    unittest.main()
