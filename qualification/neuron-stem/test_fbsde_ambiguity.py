"""Exact nonanticipative robust-value counterexample regression."""
import unittest
from fractions import Fraction as F

from fbsde_ambiguity import (PRIORS, ACTIONS, expected_prior, exhaustive_global,
                              local_rectangular, experiment)


class NonrectangularTests(unittest.TestCase):
    def test_valid_laws_share_public_signal_marginal(self):
        for p in PRIORS:
            self.assertEqual(sum(p.values()), 1)
            self.assertEqual([sum(v for (s, _), v in p.items() if s == i)
                              for i in (0, 1)], [F(1, 2), F(1, 2)])

    def test_global_robust_policy_and_exhaustive_count(self):
        r = exhaustive_global()
        self.assertEqual(r["value"], F(0))
        self.assertEqual(r["policy_count"], len(ACTIONS)**2)
        self.assertEqual([expected_prior({0: "guess0", 1: "guess0"}, p)
                          for p in PRIORS], [F(0), F(0)])

    def test_local_rectangular_objective_is_distinct(self):
        local = local_rectangular()
        self.assertEqual(local["policy"], {0: "abstain", 1: "abstain"})
        self.assertEqual(local["value"], -F(1, 4))
        r = experiment()
        self.assertEqual(r["gap"], "1/4")
        self.assertFalse(r["production_promotion_permitted"])

    def test_clairvoyance_cannot_enter_policy(self):
        with self.assertRaisesRegex(ValueError, "both public signal"):
            expected_prior({(0, 0): "guess0", (0, 1): "guess1"}, PRIORS[0])
        with self.assertRaisesRegex(ValueError, "both public signal"):
            expected_prior({0: "oracle", 1: "guess0"}, PRIORS[0])


if __name__ == "__main__":
    unittest.main()
