"""Counterexamples for finite-sample, floating-point and event-type confusion."""

from fractions import Fraction
import json
import math
import unittest

from .calibration import split_conformal_threshold


class CalibrationTests(unittest.TestCase):
    def test_unavailable_rank_is_infinite_not_clamped_to_sample_max(self):
        result = split_conformal_threshold([0.1, 0.2, 0.3], 0.1)
        self.assertEqual(
            (
                result["quantile_rank"],
                result["threshold"],
                result["nontrivial_bound_available"],
            ),
            (4, None, False),
        )
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)

    def test_empty_data_has_no_nontrivial_bound(self):
        result = split_conformal_threshold([], 0.1)
        self.assertEqual(
            (
                result["sample_count"],
                result["quantile_rank"],
                result["threshold"],
                result["nontrivial_bound_available"],
            ),
            (0, 1, None, False),
        )

    def test_float_neighbors_do_not_silently_round_below_boundary(self):
        below = split_conformal_threshold([1, 2, 3], math.nextafter(0.25, 0))
        exact = split_conformal_threshold([1, 2, 3], 0.25)
        above = split_conformal_threshold([1, 2, 3], math.nextafter(0.25, 1))
        self.assertEqual(
            [item["threshold"] for item in (below, exact, above)], [None, 3.0, 3.0]
        )
        for count in (0, 1, 2, 3, 9, 99):
            for alpha in (0.1, 1 / 3, math.nextafter(0.0, 1), math.nextafter(1.0, 0)):
                result = split_conformal_threshold(list(range(count)), alpha)
                target = (count + 1) * (1 - Fraction.from_float(alpha))
                self.assertLess(result["quantile_rank"] - 1, target)
                self.assertGreaterEqual(result["quantile_rank"], target)

    def test_order_statistic_is_permutation_invariant_with_ties(self):
        first = split_conformal_threshold([4, 0, 2, 2, 6], 0.5)
        second = split_conformal_threshold([6, 2, 0, 4, 2], 0.5)
        self.assertEqual(first, second)
        self.assertEqual((first["quantile_rank"], first["threshold"]), (3, 2.0))

    def test_perfect_score_coverage_can_coexist_with_all_outcomes_wrong(self):
        result = split_conformal_threshold([0] * 19, 0.1)
        test_scores, actual_errors = [0, 0, 0], [True, True, True]
        score_miscoverage = (
            sum(score > result["threshold"] for score in test_scores) / 3
        )
        actual_error_rate = sum(actual_errors) / 3
        self.assertEqual((score_miscoverage, actual_error_rate), (0, 1))
        self.assertIsNone(result["actual_error_bound"])

    def test_rejects_invalid_probabilities_scores_and_implicit_iterables(self):
        for alpha in (
            True,
            False,
            0,
            1,
            -0.1,
            1.1,
            float("nan"),
            float("inf"),
            "0.1",
            None,
        ):
            with self.subTest(alpha=alpha), self.assertRaises(ValueError):
                split_conformal_threshold([0], alpha)
        for scores in (
            [True],
            [-0.1],
            [float("nan")],
            [float("inf")],
            ["0.1"],
            [10**1000],
            None,
            {0},
        ):
            with self.subTest(scores=scores), self.assertRaises(ValueError):
                split_conformal_threshold(scores, 0.1)


if __name__ == "__main__":
    unittest.main()
