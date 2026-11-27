"""Inferential failure modes that would inflate the mechanism pilot's evidence."""

import unittest

from ..mechanism_analysis import holm_fixed_family, paired_summary


class MechanismAnalysisTests(unittest.TestCase):
    def test_useful_difference_is_the_null_not_zero(self):
        at_null = paired_summary([.007, .009, .011, .013])
        self.assertAlmostEqual(at_null["mean_effect"], .01, places=14)
        self.assertAlmostEqual(at_null["one_sided_p_above_mud"], .5, places=13)
        self.assertLess(at_null["pointwise_95_ci"][0], .01)
        negative = paired_summary([-.1, -.2, -.3, -.4])
        self.assertLess(negative["pointwise_95_ci"][1], 0)
        self.assertGreater(negative["one_sided_p_above_mud"], .95)

    def test_holm_keeps_all_twenty_registered_comparisons(self):
        rows = [dict(all_four_registered_seeds_present=True, inferential_eligible=True, one_sided_p_above_mud=p,
                     pointwise_95_ci=[.02, .04]) for p in [.001, .003, .01] + [1.] * 17]
        holm_fixed_family(rows)
        self.assertAlmostEqual(rows[0]["holm_adjusted_p_above_mud"], .02)
        self.assertAlmostEqual(rows[1]["holm_adjusted_p_above_mud"], .057)
        self.assertAlmostEqual(rows[2]["holm_adjusted_p_above_mud"], .18)
        self.assertTrue(rows[0]["exploratory_effect_gate_pass"])
        self.assertFalse(rows[1]["exploratory_effect_gate_pass"])
        with self.assertRaises(ValueError):
            holm_fixed_family(rows[:3])

    def test_fewer_training_seeds_cannot_pass_by_tiny_p(self):
        incomplete = paired_summary([.09999999, .1, .10000001])
        self.assertLess(incomplete["one_sided_p_above_mud"], 1e-12)
        rows = [incomplete] + [paired_summary([]) for _ in range(19)]
        holm_fixed_family(rows)
        self.assertEqual(rows[0]["holm_adjusted_p_above_mud"], 1.)
        self.assertFalse(any(row["exploratory_effect_gate_pass"] for row in rows))
        self.assertEqual(len(rows), 20)

    def test_zero_variance_is_not_an_infinite_significance_claim(self):
        degenerate = paired_summary([.1, .1, .1, .1])
        self.assertEqual(degenerate["mean_effect"], .1)
        self.assertTrue(degenerate["zero_sample_variance"])
        self.assertFalse(degenerate["inferential_eligible"])
        self.assertIsNone(degenerate["one_sided_p_above_mud"])
        rows = [degenerate] + [paired_summary([]) for _ in range(19)]
        holm_fixed_family(rows)
        self.assertFalse(rows[0]["exploratory_effect_gate_pass"])

    def test_direction_and_nonfinite_samples(self):
        positive = paired_summary([.1, .2, .3, .4])
        negative = paired_summary([-.1, -.2, -.3, -.4])
        self.assertAlmostEqual(positive["mean_effect"], -negative["mean_effect"])
        self.assertAlmostEqual(positive["pointwise_95_ci"][0], -negative["pointwise_95_ci"][1])
        with self.assertRaises(ValueError):
            paired_summary([.1, float("nan"), .2, .3])


if __name__ == "__main__":
    unittest.main()
