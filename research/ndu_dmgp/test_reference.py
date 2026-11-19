"""Negative conformance tests for the qualification-only portfolio reference."""
import unittest
from reference import Candidate, select_deterministic, shrink_covariance, portfolio_objective, state_closure_delta


def candidate(name, utility, **kw):
    base = dict(identity=name, expected_ndu=utility, cost=1.0,
                duration_ms=1.0, hard_feasible=True,
                evidence_digest="external-observation-digest",
                objective_digest="frozen-objective", generation=1,
                observer_id="independent-observer")
    base.update(kw)
    return Candidate(**base)


class PortfolioTests(unittest.TestCase):
    def test_no_infeasible_winner(self):
        c = [candidate("abstain", 0, cost=0),
             candidate("unsafe", 100, hard_feasible=False),
             candidate("overbudget", 90, cost=900),
             candidate("good", 2)]
        self.assertEqual(select_deterministic(
            c, objective_digest="frozen-objective", generation=1,
            max_cost=2, max_duration_ms=5).identity, "good")

    def test_fallback_abstain(self):
        c = [candidate("abstain", 0, cost=0),
             candidate("bad", 20, hard_feasible=False)]
        self.assertEqual(select_deterministic(
            c, objective_digest="frozen-objective", generation=1,
            max_cost=2, max_duration_ms=5).identity, "abstain")

    def test_objective_and_observer_cannot_drift(self):
        for bad in [candidate("bad", 1, objective_digest="changed"),
                    candidate("bad", 1, observer_id=""),
                    candidate("bad", 1, generation=2),
                    candidate("bad", 1, evidence_digest="")]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    select_deterministic(
                        [candidate("abstain", 0, cost=0), bad],
                        objective_digest="frozen-objective", generation=1,
                        max_cost=5, max_duration_ms=5)

    def test_tie_is_not_fake_optimum(self):
        with self.assertRaises(ValueError):
            select_deterministic(
                [candidate("abstain", 0, cost=0), candidate("a", 1),
                 candidate("b", 1)],
                objective_digest="frozen-objective", generation=1,
                max_cost=5, max_duration_ms=5)

    def test_covariance_support_fallback(self):
        self.assertIsNone(shrink_covariance([[1, 2]] * 7))
        data = [[float(i), float(i)] for i in range(10)]
        cov = shrink_covariance(data)
        self.assertGreater(cov[0][0], cov[0][1])
        self.assertAlmostEqual(cov[0][1], cov[1][0])

    def test_correlation_matters(self):
        a = [1, 1]
        w = [0.5, 0.5]
        c = [1, 1]
        low = [[1, 0], [0, 1]]
        high = [[1, 0.9], [0.9, 1]]
        self.assertGreater(
            portfolio_objective(w, a, low, 1, c, 1),
            portfolio_objective(w, a, high, 1, c, 1))

    def test_budget_and_simplex_fail_closed(self):
        for weights, budget in [([0.8, 0.8], 10), ([0.5, 0.5], 0.1)]:
            with self.assertRaises(ValueError):
                portfolio_objective(weights, [1, 1],
                                    [[1, 0], [0, 1]], 1, [1, 1], budget)

    def test_missing_history_blocks_markov_claim(self):
        self.assertGreater(state_closure_delta([1, 1], [0.1, 0.2]), 0.5)
        self.assertAlmostEqual(state_closure_delta([1, 1], [1, 1]), 0)


if __name__ == "__main__":
    unittest.main()
