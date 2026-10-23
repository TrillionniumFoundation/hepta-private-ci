"""Six data-free stdlib tests; artificial losses test algebra, not science."""
import copy
import math
import unittest
from oracle import summarize


def row(audio, video):
    return {"audio_mse": audio, "video_mse": video, "audio_scalars": 2, "video_scalars": 3}


class PrefixOracleTests(unittest.TestCase):
    def test_identical_records_have_no_dynamic_headroom(self):
        report = summarize([row([4., 3., 2., 1.], [4., 3., 2., 1.])] * 2)
        self.assertTrue(all(f["mean_headroom"] == 0 for f in report["frontiers"]))

    def test_truth_oracle_can_detect_real_heterogeneity_in_fixture(self):
        report = summarize([row([4., 0., 0., 0.], [4., 4., 4., 4.]),
                            row([4., 4., 4., 4.], [4., 0., 0., 0.])])
        point = next(f for f in report["frontiers"] if f["semantics"] == "exact_calls" and f["budget"] == 1)
        self.assertEqual(point["mean_headroom"], 1.)
        self.assertEqual(point["static_mean_calls"], point["oracle_mean_calls"])

    def test_prefix_dependencies_and_costs_are_paid(self):
        report = summarize([row([4., 3., 2., 0.], [4., 3., 2., 0.])])
        last = next(f for f in report["frontiers"] if f["semantics"] == "exact_calls" and f["budget"] == 6)
        self.assertEqual(last["static_prefix"], [3, 3])
        self.assertEqual(last["oracle_matrix_macs"], 64 * 3 * (2 + 3))
        self.assertEqual(report["eager_audit_calls"], 6)

    def test_at_most_can_stop_but_exact_cannot_hide_work(self):
        report = summarize([row([0., 1., 2., 3.], [0., 1., 2., 3.])])
        exact = next(f for f in report["frontiers"] if f["semantics"] == "exact_calls" and f["budget"] == 6)
        capped = next(f for f in report["frontiers"] if f["semantics"] == "at_most_calls" and f["budget"] == 6)
        self.assertEqual((exact["oracle_mean_calls"], capped["oracle_mean_calls"]), (6, 0))
        self.assertEqual(report["coverage"], 1.)
        self.assertFalse(report["oracle_is_deployable"])

    def test_invalid_losses_or_sizes_fail_closed(self):
        template = row([1.] * 4, [1.] * 4)
        for value in (math.nan, math.inf, -1., True):
            bad = copy.deepcopy(template)
            bad["audio_mse"][0] = value
            with self.assertRaises(ValueError):
                summarize([bad])
        with self.assertRaises(ValueError):
            summarize([])
        with self.assertRaises(ValueError):
            summarize([dict(template, video_scalars=0)])

    def test_only_aggregates_are_returned_without_mutating_inputs(self):
        records = [row([4., 3., 2., 1.], [4., 3., 2., 1.])]
        before = copy.deepcopy(records)
        report = summarize(records)
        self.assertEqual(records, before)
        self.assertNotIn("rows", report)
        self.assertNotIn("oracle_prefixes", report)
        self.assertFalse(report["scientific_efficacy_confirmed"])


if __name__ == "__main__":
    unittest.main()
