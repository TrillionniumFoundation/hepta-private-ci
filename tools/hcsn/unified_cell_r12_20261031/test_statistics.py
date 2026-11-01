"""Tests for paired-fit units, exact testing and distinct cost accounting."""

import copy
import unittest

import numpy as np
from scipy.stats import t as student_t

from .statistics import exact_sign_flip, holm_adjust, summarize


def fixture():
    rows = []
    for domain in ("iid", "ood"):
        for seed in range(8):
            rows.append({"seed": seed, "domain": domain, "arms": {
                "A": {"mean_utility": .60, "online_cpu_per_episode": .02,
                      "direct_cpu_per_episode": .04, "full_cpu_per_episode": .08},
                "B": {"mean_utility": .65, "online_cpu_per_episode": .04,
                      "direct_cpu_per_episode": .06, "full_cpu_per_episode": .10},
                "C": {"mean_utility": .62, "online_cpu_per_episode": .03,
                      "direct_cpu_per_episode": .04, "full_cpu_per_episode": .05},
                "D": {"mean_utility": .68+.001*seed, "online_cpu_per_episode": .05,
                      "direct_cpu_per_episode": .07, "full_cpu_per_episode": .08},
            }})
    return rows


class PairedFitStatisticsTests(unittest.TestCase):
    def test_exhaustive_two_sided_test_counts_both_extremes(self):
        self.assertEqual(exact_sign_flip(np.ones(8)), 2/256)
        self.assertEqual(exact_sign_flip(np.zeros(8)), 1.)
        self.assertEqual(exact_sign_flip([1, -1]*4), 1.)

    def test_holm_adjustment_is_monotone_and_has_two_tests(self):
        self.assertEqual(holm_adjust({"iid": .01, "ood": .015}), {"iid": .02, "ood": .02})
        self.assertEqual(holm_adjust({"iid": .6, "ood": .8}), {"iid": 1., "ood": 1.})

    def test_paired_contrasts_t_intervals_and_interaction(self):
        output = summarize(fixture())["domains"]["iid"]
        contrast = output["contrasts"]["D-B"]
        values = .03+.001*np.arange(8)
        expected_sd = np.std(values, ddof=1)
        self.assertAlmostEqual(contrast["mean"], values.mean())
        self.assertAlmostEqual(contrast["sample_sd"], expected_sd)
        self.assertAlmostEqual(contrast["t_95pct_ci"][0], values.mean()-student_t.ppf(.975, 7)*expected_sd/np.sqrt(8))
        self.assertEqual(contrast["degrees_of_freedom"], 7)
        self.assertEqual(contrast["n"], 8)
        self.assertAlmostEqual(output["contrasts"]["B-A"]["mean"], .05)
        self.assertAlmostEqual(output["contrasts"]["C-A"]["mean"], .02)
        self.assertAlmostEqual(output["contrasts"]["interaction"]["mean"], .0135)
        self.assertTrue(output["primary_test"]["improvement"])
        self.assertEqual(output["primary_test"]["holm_adjusted_p"], 4/256)

    def test_cost_uses_full_ratio_and_simultaneous_utility_bound(self):
        result = summarize(fixture())["domains"]["iid"]
        ratios = result["costs"]["D_over_B"]
        self.assertAlmostEqual(ratios["online_cpu_per_episode"], 1.25)
        self.assertAlmostEqual(ratios["direct_cpu_per_episode"], 7/6)
        self.assertAlmostEqual(ratios["full_cpu_per_episode"], .8)
        self.assertTrue(result["cost_acceptance"]["accepted"])
        self.assertEqual(result["cost_acceptance"]["per_domain_one_sided_confidence"], .975)
        rows = fixture()
        for row in rows:
            row["arms"]["D"]["full_cpu_per_episode"] = .095
        self.assertFalse(summarize(rows)["domains"]["iid"]["cost_acceptance"]["accepted"])

    def test_cost_ratio_is_ratio_of_means_not_mean_of_ratios(self):
        rows = fixture()
        for row in rows:
            row["arms"]["B"]["full_cpu_per_episode"] = .1*(row["seed"]+1)
            row["arms"]["D"]["full_cpu_per_episode"] = .1
        ratio = summarize(rows)["domains"]["iid"]["costs"]["D_over_B"]["full_cpu_per_episode"]
        self.assertAlmostEqual(ratio, .1/.45)
        self.assertNotAlmostEqual(ratio, np.mean(1/np.arange(1, 9)))

    def test_effect_threshold_is_additional_to_significance(self):
        rows = fixture()
        for row in rows:
            row["arms"]["D"]["mean_utility"] = .655
        result = summarize(rows)["domains"]["iid"]
        self.assertLess(result["primary_test"]["holm_adjusted_p"], .05)
        self.assertFalse(result["primary_test"]["improvement"])
        for row in rows:
            row["arms"]["D"]["mean_utility"] = .63
        result = summarize(rows)["domains"]["iid"]
        self.assertFalse(result["cost_acceptance"]["utility_noninferior"])
        self.assertFalse(result["cost_acceptance"]["accepted"])

    def test_missing_direct_cost_is_not_replaced(self):
        rows = fixture()
        for row in rows:
            for arm in row["arms"].values():
                del arm["direct_cpu_per_episode"]
        result = summarize(rows)["domains"]["iid"]["costs"]
        self.assertIsNone(result["D_over_B"]["direct_cpu_per_episode"])
        self.assertFalse(result["direct_column_supplied"])
        rows[0]["arms"]["A"]["direct_cpu_per_episode"] = .2
        with self.assertRaises(ValueError):
            summarize(rows)

    def test_rejects_pseudoreplication_missing_fits_and_unpaired_seeds(self):
        valid = fixture()
        for invalid in (valid[:-1], valid*128):
            with self.assertRaises(ValueError):
                summarize(invalid)
        duplicate = copy.deepcopy(valid)
        duplicate[0]["seed"] = duplicate[1]["seed"]
        unpaired = copy.deepcopy(valid)
        unpaired[0]["seed"] = 999
        nonfinite = copy.deepcopy(valid)
        nonfinite[0]["arms"]["D"]["mean_utility"] = float("nan")
        for invalid in (duplicate, unpaired, nonfinite):
            with self.assertRaises(ValueError):
                summarize(invalid)


if __name__ == "__main__":
    unittest.main()
