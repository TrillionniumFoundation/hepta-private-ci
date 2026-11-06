"""Independent finite-risk identities and executable-policy boundary checks."""
from fractions import Fraction as F
import math
import unittest

from .frontier import Contract, Tree
from .binary_deadline import minimax
from ..ndu_identification.model import Task, planner


class FrontierTests(unittest.TestCase):
    def solve(self, contract, budget=None):
        tree = Tree(contract)
        result = tree.solve(budget)
        self.assertLessEqual(result["gap"], F(1, 10**8))
        self.assertLessEqual(result["lower"], result["upper"])
        if budget is not None:
            self.assertTrue(all(c <= budget for c in result["resources"]))
        return tree, result

    def test_no_information_requires_shared_randomized_decision(self):
        _, r = self.solve(Contract(0))
        self.assertEqual((r["lower"], r["upper"], r["errors"]), (F(1, 2), F(1, 2), (F(1, 2), F(1, 2))))

    def test_expected_budget_has_exact_randomized_frontier(self):
        _, r = self.solve(Contract(1, family="bernoulli"), F(7, 400))
        self.assertEqual((r["lower"], r["upper"]), (F(2, 5), F(2, 5)))
        self.assertEqual(r["resources"], (F(7, 400), F(7, 400)))

    def test_eight_samples_cannot_deliver_five_percent_error(self):
        _, r = self.solve(Contract(8, max_probes=8, family="bernoulli"))
        # Independent binomial full-sample Bayes risk (ties randomized).
        exact = sum((F(math.comb(8, k))*F(7, 10)**k*F(3, 10)**(8-k) for k in range(4)), F(0))
        exact += F(math.comb(8, 4), 2)*F(7, 10)**4*F(3, 10)**4
        self.assertEqual(r["lower"], exact)
        self.assertGreater(r["lower"], F(1, 20))

    def test_censored_duration_and_failure_preserve_cost(self):
        tree, r = self.solve(Contract(3, max_probes=1))
        self.assertEqual((r["lower"], r["upper"]), (F(17, 250), F(17, 250)))
        self.assertEqual(r["resources"], (F(11, 200), F(11, 200)))
        for node in tree.nodes:
            self.assertLessEqual(node["elapsed"], 3)

    def test_preparation_is_paid_and_consumes_real_horizon(self):
        _, early = self.solve(Contract(1, family="gated"))
        _, enough = self.solve(Contract(2, family="gated"))
        _, capped = self.solve(Contract(2, family="gated"), F(1, 20))
        self.assertEqual((early["lower"], enough["lower"]), (F(1, 2), F(1, 10)))
        self.assertEqual((capped["lower"], capped["upper"]), (F(3, 14), F(3, 14)))

    def test_unconstrained_risk_matches_independent_belief_dp(self):
        for deadline in range(5):
            with self.subTest(deadline=deadline):
                _, r = self.solve(Contract(deadline))
                _, dp = planner(Task(deadline=deadline, fee=0, rho=0, max_probes=3))
                independent = 1-dp(F(1, 2), deadline, 3)[0]
                self.assertAlmostEqual(float(r["upper"]), independent, places=9)

    def test_zero_budget_and_exact_policy_validation(self):
        tree, r = self.solve(Contract(2), F(0))
        self.assertEqual((r["upper"], r["resources"]), (F(1, 2), (F(0), F(0))))
        r["policy"][0][0] += F(1, 10)
        with self.assertRaises(ValueError):
            tree.evaluate(r["policy"])

    def test_rounding_repair_is_the_returned_executable_policy(self):
        budget = F(5928486, 1000000007)
        tree, r = self.solve(Contract(1, family="bernoulli"), budget)
        errors, costs, mass = tree.evaluate(r["policy"])
        self.assertEqual((errors, costs), (r["errors"], r["resources"]))
        self.assertTrue(all(c <= budget for c in costs))
        self.assertEqual(mass, (F(1), F(1)))

    def test_catalog_deadline_threshold_and_complete_acquisition_price(self):
        self.assertGreater(minimax(22)["risk"], F(1, 20))
        self.assertLess(minimax(23)["risk"], F(1, 20))
        for n in range(23):
            self.assertGreater(minimax(n)["risk"], F(1, 20))
        _, r = self.solve(Contract.paid_catalog(3, max_probes=1))
        self.assertEqual(r["lower"], minimax(1)["risk"])
        with self.assertRaises(ValueError):
            Contract(3, family="catalog")
        with self.assertRaises(ValueError):
            minimax(0, .57, .87)


if __name__ == "__main__":
    unittest.main()
