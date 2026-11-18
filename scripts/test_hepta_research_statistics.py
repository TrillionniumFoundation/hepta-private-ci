"""Synthetic arithmetic cases, never research experiment outcomes."""

import copy
import math
import unittest

from hepta_cells.research_statistics import (
    analyze_grouped_pairs,
    build_statistical_plan,
    statistical_plan_digest,
)


def plan(n=100, m=1, repeats=("r1",)):
    return build_statistical_plan(
        alpha=0.05,
        margin=0.1,
        comparison_count=m,
        comparisons={
            str(i): {"candidate": "a" * 64, "control": "b" * 64} for i in range(m)
        },
        groups=[str(i) for i in range(n)],
        seeds=[1, 2],
        repeats=list(repeats),
        phase="C",
        metric="success_fraction",
        precision_justification="test-only arithmetic case",
        stopping_rule="fixed_complete_schedule_no_interim_tests",
    )


def rows(p):
    return [
        dict(
            comparison="0", source_group=g, seed=s, repeat=r, candidate=1.0, control=0.0
        )
        for g in p["groups"]
        for s in p["seeds"]
        for r in p["repeats"]
    ]


def analyze(p, data):
    return analyze_grouped_pairs(p, data, frozen_plan_sha256=statistical_plan_digest(p))


class StatisticsTests(unittest.TestCase):
    def test_groups_not_seed_or_repeat_count_determine_bound(self):
        small, repeated = plan(), plan(repeats=("r1", "r2", "r3"))
        a = analyze(small, rows(small))["results"]["0"]
        b = analyze(repeated, rows(repeated))["results"]["0"]
        self.assertEqual((a["statistical_n"], b["statistical_n"]), (100, 100))
        expected = 1 - math.sqrt(2 * math.log(20) / 100)
        self.assertAlmostEqual(a["lower_confidence_bound"], expected)
        self.assertEqual(a["lower_confidence_bound"], b["lower_confidence_bound"])
        self.assertTrue(a["statistical_gain_exceeds_margin"])
        data = rows(small)
        with self.assertRaisesRegex(ValueError, "duplicate pair"):
            analyze(small, data + [data[0]])

    def test_missing_group_seed_or_arm_never_qualifies(self):
        p = plan()
        partial_arm = rows(p)
        partial_arm[0]["control"] = None
        cases = [
            rows(p)[1:],
            [r for r in rows(p) if r["source_group"] != "0"],
            partial_arm,
            [],
        ]
        for data in cases:
            with self.subTest(size=len(data)):
                result = analyze(p, data)["results"]["0"]
                self.assertEqual(result["status"], "INCOMPLETE")
                self.assertIsNone(result["lower_confidence_bound"])
                self.assertFalse(result["statistical_gain_exceeds_margin"])

    def test_failed_unrun_attempts_keep_bonferroni_charge(self):
        p1, p10 = plan(), plan(m=10)
        r1, r10 = analyze(p1, rows(p1)), analyze(p10, rows(p10))
        self.assertEqual(r10["family_comparisons_charged"], 10)
        self.assertLess(
            r10["results"]["0"]["lower_confidence_bound"],
            r1["results"]["0"]["lower_confidence_bound"],
        )
        self.assertEqual(r10["results"]["1"]["status"], "INCOMPLETE")
        self.assertIsNone(r10["research_accepted"])
        p10["comparison_count"] = 1
        with self.assertRaisesRegex(ValueError, "charged"):
            analyze(p10, [])

    def test_null_nonfinite_boolean_and_unplanned_scores_rejected(self):
        p = plan()
        for bad in (True, float("nan"), float("inf"), 10**1000, -0.1, 1.1):
            data = rows(p)
            data[0]["candidate"] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                analyze(p, data)
        for key in ("alpha", "margin", "groups", "seeds", "precision_justification"):
            broken = copy.deepcopy(p)
            broken[key] = None
            with self.subTest(key=key), self.assertRaises(ValueError):
                analyze(broken, [])
        data = rows(p)
        data[0]["comparison"] = "extra-attempt"
        with self.assertRaisesRegex(ValueError, "unscheduled"):
            analyze(p, data)
        data[0]["comparison"] = "0"
        data[0]["seed"] = True
        with self.assertRaisesRegex(ValueError, "not bool"):
            analyze(p, data)

    def test_changed_postfreeze_plan_and_optional_stopping_rejected(self):
        p = plan()
        frozen = statistical_plan_digest(p)
        p["margin"] = 0.0
        with self.assertRaisesRegex(ValueError, "frozen digest"):
            analyze_grouped_pairs(p, rows(p), frozen_plan_sha256=frozen)
        p["stopping_rule"] = "stop_when_significant"
        with self.assertRaisesRegex(ValueError, "fixed complete"):
            analyze(p, [])


if __name__ == "__main__":
    unittest.main()
