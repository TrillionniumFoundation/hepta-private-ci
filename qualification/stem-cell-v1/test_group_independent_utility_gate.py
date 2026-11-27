"""Fail-closed contract regressions for paired research utility gate."""
import copy
import unittest

from group_independent_utility_gate import COST_KEYS, review

SHA_A = "a" * 64
SHA_B = "b" * 64


def observations(groups=24, improvement=False):
    rows = []
    for i in range(groups):
        cohort = ("ordinary", "long", "deleted", "composition")[i % 4]
        for arm in ("static", "recurrent", "ndu", "split"):
            cost = {k: 0.0 for k in COST_KEYS}
            cost["inference"] = 0.01 if arm == "static" else 0.03
            supported = cohort != "deleted"
            correct = supported and (arm != "static" if improvement else True)
            rows.append(dict(case_id=f"case-{i}", group_id=f"group-{i}",
                             cohort=cohort, arm=arm, source_sha256=SHA_A,
                             evaluator_sha256=SHA_B, correct=correct,
                             evidence_supported=supported, cost=cost))
    return rows


class IndependentUtilityGateTests(unittest.TestCase):
    def test_negative_or_unproven_gain_never_promotes(self):
        result = review(observations())
        self.assertEqual(result["authority"], "DENY_ALL")
        self.assertFalse(result["production_promotion_permitted"])
        self.assertTrue(all(x["decision"] == "reject_or_insufficient_evidence"
                            for x in result["arms"].values()))

    def test_finite_cohort_and_group_statistics(self):
        result = review(observations(improvement=True))
        self.assertEqual(result["number_of_source_groups"], 24)
        self.assertEqual(result["arms"]["ndu"]["rescued"], 18)
        self.assertIn("deleted", result["arms"]["ndu"]["cohort_mean_deltas"])
        self.assertFalse(result["source_group_independence_verified"])

    def test_favorable_math_never_becomes_unverified_selection_authority(self):
        result = review(observations(groups=400, improvement=True))
        self.assertEqual(result["arms"]["ndu"]["decision"],
                         "diagnostic_lower_bound_pass_unverified")
        self.assertFalse(result["arms"]["ndu"]["topology_or_model_selection_authorized"])
        self.assertFalse(result["production_promotion_permitted"])
        self.assertFalse(result["source_group_independence_verified"])

    def test_reject_missing_arm(self):
        rows = observations()
        rows.pop()
        with self.assertRaisesRegex(ValueError, "unpaired"):
            review(rows)

    def test_reject_duplicate_case(self):
        rows = observations()
        rows.append(copy.deepcopy(rows[0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            review(rows)

    def test_reject_unverified_success_without_evidence(self):
        rows = observations()
        deleted = next(r for r in rows if r["cohort"] == "deleted")
        deleted["correct"] = True
        with self.assertRaisesRegex(ValueError, "unsupported"):
            review(rows)

    def test_reject_source_mismatch(self):
        rows = observations()
        rows[1]["source_sha256"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            review(rows)

    def test_reject_missing_cost_or_invalid_numeric(self):
        for value in (float("nan"), -1.0, True):
            rows = observations()
            rows[0]["cost"]["inference"] = value
            with self.assertRaises(ValueError):
                review(rows)
        rows = observations()
        del rows[0]["cost"]["training_amortized"]
        with self.assertRaisesRegex(ValueError, "lifecycle"):
            review(rows)

    def test_reject_unbounded_utility_range(self):
        rows = observations()
        rows[0]["cost"]["inference"] = 2.0
        with self.assertRaisesRegex(ValueError, "cost bound"):
            review(rows)

    def test_reject_changing_group_cohort(self):
        rows = observations()
        for r in rows:
            if r["group_id"] == "group-1":
                r["group_id"] = "group-0"
        with self.assertRaisesRegex(ValueError, "cross cohorts"):
            review(rows)

    def test_reject_posthoc_arms_and_missing_critical_stratum(self):
        with self.assertRaisesRegex(ValueError, "pre-registered"):
            review(observations(), preregistered_arms=("ndu", "ndu"))
        rows = [r for r in observations() if r["cohort"] != "composition"]
        result = review(rows)
        self.assertIn("composition", result["arms"]["ndu"]["missing_critical_cohorts"])
        self.assertNotEqual(result["arms"]["ndu"]["decision"], "candidate_admissible")

    def test_reject_schema_drift_and_wrong_evaluator(self):
        rows = observations()
        rows[0]["extra"] = True
        with self.assertRaisesRegex(ValueError, "schema"):
            review(rows)
        rows = observations()
        rows[1]["evaluator_sha256"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "identity"):
            review(rows)


if __name__ == "__main__":
    unittest.main()
