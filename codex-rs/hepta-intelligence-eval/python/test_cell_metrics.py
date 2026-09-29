from dataclasses import replace
import hashlib
import math
import unittest
from cell_metrics import LabeledChoices, paired_metrics


def h(x):
    return hashlib.sha256(x.encode()).hexdigest()


class MetricTests(unittest.TestCase):
    def setUp(self):
        self.labels = (LabeledChoices("one", "g1", h("1"), ("abstain", "s1", "s2"), "s1"),
                       LabeledChoices("two", "g2", h("2"), ("abstain", "s1", "s2"), "s2"))
        self.old = {"one": (.2, .6, .2), "two": (.2, .6, .2)}
        self.new = {"one": (.1, .8, .1), "two": (.1, .1, .8)}

    def test_independent_known_values(self):
        result = paired_metrics(self.labels, self.old, self.new)
        self.assertEqual(result["baseline"]["accuracy"], .5)
        self.assertEqual(result["candidate"]["accuracy"], 1)
        self.assertAlmostEqual(result["candidate"]["brier"], .06)
        self.assertAlmostEqual(result["candidate"]["log_loss"], -math.log(.8))
        self.assertFalse(result["independent_acceptance"])
        self.assertFalse(result["final_holdout_consumed"])

    def test_no_change_and_order_invariance(self):
        a = paired_metrics(self.labels, self.old, self.old)
        b = paired_metrics(tuple(reversed(self.labels)), self.old, self.old)
        self.assertEqual(a, b)
        self.assertTrue(all(v == 0 for v in a["candidate_minus_baseline"].values()))

    def test_missing_or_additional_result_rejects(self):
        for altered in ({"one": self.old["one"]}, dict(self.old, third=(.2, .6, .2))):
            with self.assertRaises(ValueError):
                paired_metrics(self.labels, altered, self.new)

    def test_invalid_and_repeated_observation_rejects(self):
        for rows in ((), self.labels + (self.labels[0],),
                     (self.labels[0], replace(self.labels[1], outcome_digest=h("1"))),
                     (None,), (replace(self.labels[0], gold_id="missing"),)):
            with self.assertRaises(ValueError):
                paired_metrics(rows, self.old, self.new)

    def test_probabilities_reject_unknown_cost_as_success(self):
        for p in ((.1, .1), (float("nan"), 0, 1), (True, 0, 0), (-.1, .1, 1), (.3, .3, .3)):
            with self.assertRaises(ValueError):
                paired_metrics(self.labels, dict(self.old, one=p), self.new)

    def test_group_weighting_does_not_inflate_long_trajectory(self):
        third = replace(self.labels[0], row_id="three", outcome_digest=h("3"))
        result = paired_metrics((*self.labels, third), dict(self.old, three=(.2, .6, .2)),
                                dict(self.new, three=(.1, .8, .1)))
        self.assertEqual(result["baseline"]["accuracy"], .5)
        self.assertEqual(result["groups"], 2)
        self.assertEqual(result["rows"], 3)

    def test_tie_order_and_zero_gold_probability_are_explicit(self):
        row = replace(self.labels[0], gold_id="abstain")
        result = paired_metrics((row,), {"one": (.5, .5, 0)}, {"one": (0, 0, 1)})
        self.assertEqual(result["baseline"]["accuracy"], 1)
        self.assertAlmostEqual(result["candidate"]["log_loss"], -math.log(1e-12))
        self.assertEqual(result["candidate_minus_baseline"]["accuracy"], -1)

    def test_payload_changes_metric_identity(self):
        a = paired_metrics(self.labels, self.old, self.new)
        b = paired_metrics(self.labels, self.old, dict(self.new, one=(.2, .7, .1)))
        self.assertNotEqual(a["batch_digest"], b["batch_digest"])


if __name__ == "__main__":
    unittest.main()
