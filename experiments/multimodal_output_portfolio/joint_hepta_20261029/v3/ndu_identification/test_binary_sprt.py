"""Independent exact checks of SPRT values and deadline qualification."""
from fractions import Fraction as F
import unittest
from .binary_sprt import absorbing_chain, deadline_walk, exact_sprt


class BinarySprtTests(unittest.TestCase):
    def test_closed_form_matches_independent_chain(self):
        for delta in (F(1, 5), F(1, 20), F(1, 1000), F(1, 1000000)):
            row = exact_sprt(F(7, 10), delta)
            self.assertEqual(absorbing_chain(F(7, 10), row["boundary"]),
                             (row["error"], row["expected_queries"]))
            self.assertLessEqual(row["error"], delta)
            self.assertLessEqual(row["count_lower_bound"], float(row["expected_queries"])+1e-12)
            self.assertLessEqual(float(row["expected_queries"]), row["count_upper_bound"]+1e-12)

    def test_single_step_chain_and_truncation(self):
        self.assertEqual(absorbing_chain(F(7, 10), 1), (F(3, 10), F(1)))
        self.assertEqual(deadline_walk(F(7, 10), 1, 3),
                         {"unresolved": F(0), "forced_error": F(3, 10), "expected_queries": F(1),
                          "optimal_full_cap_error": F(27, 125)})

    def test_five_query_deadline_cannot_inherit_five_percent_claim(self):
        row = exact_sprt(F(7, 10), F(1, 20))
        finite = deadline_walk(F(7, 10), row["boundary"], 5)
        self.assertLess(row["error"], F(1, 20))
        self.assertGreater(finite["forced_error"], F(1, 20))
        self.assertGreater(finite["optimal_full_cap_error"], F(1, 20))
        self.assertLess(5*row["kl_per_query"], row["required_information"])
        self.assertGreater(finite["unresolved"], 0)

    def test_zero_deadline_is_uninformed_and_free(self):
        self.assertEqual(deadline_walk(F(7, 10), 4, 0),
                         {"unresolved": F(1), "forced_error": F(1, 2), "expected_queries": F(0),
                          "optimal_full_cap_error": F(1, 2)})

    def test_deadline_helper_rejects_reversed_success_orientation(self):
        with self.assertRaises(ValueError):
            deadline_walk(F(3, 10), 4, 1)

    def test_threshold_lattice_uses_exact_inequality(self):
        ratio = F(3, 7)
        self.assertEqual(exact_sprt(F(7, 10), ratio**4)["boundary"], 4)
        self.assertEqual(exact_sprt(F(7, 10), ratio**4-F(1, 10**8))["boundary"], 5)


if __name__ == "__main__":
    unittest.main()
