"""Frozen-family multiplicity and exact complete-decision count regressions."""
import copy
import unittest

from binomial_support import error_upper_bound, family_support_report, support_report
from decision_cell_metrics import HEADS
from family_replay import decision_counts


def family(size=4, trials=64):
    receipts = {f"model-{index}": f"{index + 1:064x}" for index in range(size)}
    counts = {name: {"ood_errors": 0, "ood_trials": trials,
                     "decision_errors": 0, "decision_trials": trials} for name in receipts}
    return receipts, counts


class FamilySupportTests(unittest.TestCase):
    def test_one_member_matches_existing_two_bound_diagnostic(self):
        receipts, counts = family(1, 96)
        current = family_support_report(candidate_receipts=receipts, observations=counts)
        original = support_report(**next(iter(counts.values())))
        row = current["candidates"][0]
        self.assertEqual(row["ood"], original["ood"])
        self.assertEqual(row["accepted_decision"], original["accepted_decision"])
        self.assertEqual(current["zero_error_minimum_independent_trials_per_population"],
                         original["zero_error_minimum_independent_trials_per_population"])

    def test_full_family_adjustment_is_stricter_than_selecting_one(self):
        one, counts = family(1)
        many, panel = family(4)
        single = family_support_report(candidate_receipts=one, observations=counts)
        result = family_support_report(candidate_receipts=many, observations=panel)
        self.assertGreater(result["candidates"][0]["ood"]["upper"], single["candidates"][0]["ood"]["upper"])
        self.assertAlmostEqual(result["candidates"][0]["ood"]["upper"], error_upper_bound(0, 64, .05 / 8))
        self.assertFalse(result["all_count_bounds_met"])

    def test_minimum_zero_error_boundary_and_empty_support(self):
        receipts, counts = family()
        result = family_support_report(candidate_receipts=receipts, observations=counts)
        minimum = result["zero_error_minimum_independent_trials_per_population"]
        receipts, counts = family(trials=minimum)
        self.assertTrue(family_support_report(candidate_receipts=receipts, observations=counts)["all_count_bounds_met"])
        counts["model-0"]["ood_trials"] -= 1
        self.assertFalse(family_support_report(candidate_receipts=receipts, observations=counts)["all_count_bounds_met"])
        counts["model-0"]["decision_trials"] = 0
        result = family_support_report(candidate_receipts=receipts, observations=counts)
        self.assertIsNone(result["candidates"][0]["accepted_decision"]["upper"])
        self.assertFalse(result["all_count_bounds_met"])

    def test_missing_extra_and_duplicate_members_are_not_dropped(self):
        receipts, counts = family()
        for altered in ({k: v for k, v in counts.items() if k != "model-0"},
                        {**counts, "unknown": counts["model-0"]}):
            with self.assertRaisesRegex(ValueError, "exactly"):
                family_support_report(candidate_receipts=receipts, observations=altered)
        receipts["model-1"] = receipts["model-0"]
        with self.assertRaises(ValueError):
            family_support_report(candidate_receipts=receipts, observations=counts)

    def test_invalid_family_identities_and_bounds(self):
        for receipts in ({}, {"../model": "a" * 64}, {"m": "X" * 64}, {"m": True}, family(33)[0]):
            with self.assertRaises(ValueError):
                family_support_report(candidate_receipts=receipts, observations={})
        receipts, counts = family()
        for invalid in (True, 0, 1000000, 0.5, float("nan")):
            with self.assertRaises(ValueError):
                family_support_report(candidate_receipts=receipts, observations=counts, maximum_error_ppm=invalid)

    def test_counts_require_integers_and_exact_fields(self):
        receipts, counts = family()
        for key, value in (("ood_trials", True), ("decision_errors", -1),
                           ("decision_errors", 65), ("ood_errors", 0.0),
                           ("ood_trials", 1000001), ("extra", 1)):
            altered = copy.deepcopy(counts)
            altered["model-0"][key] = value
            with self.assertRaises(ValueError):
                family_support_report(candidate_receipts=receipts, observations=altered)

    def test_order_invariant_owned_projection(self):
        receipts, counts = family()
        before = copy.deepcopy((receipts, counts))
        first = family_support_report(candidate_receipts=receipts, observations=counts)
        second = family_support_report(candidate_receipts=dict(reversed(list(receipts.items()))),
                                       observations=dict(reversed(list(counts.items()))))
        self.assertEqual(first, second)
        self.assertEqual((receipts, counts), before)
        first["candidates"][0]["ood"]["errors"] = 1
        self.assertEqual((receipts, counts), before)

    def test_good_counts_never_establish_independence_or_authority(self):
        receipts, counts = family(trials=10000)
        result = family_support_report(candidate_receipts=receipts, observations=counts)
        self.assertTrue(result["all_count_bounds_met"])
        for key in ("independence_established", "calibration_trust_granted", "runtime_selection_eligible",
                    "prospective_future_window_evidence", "production_activation"):
            self.assertIs(result[key], False)


class CompleteDecisionCountsTests(unittest.TestCase):
    def inputs(self):
        predictions = {name: [0, 0, 0] for name in HEADS}
        labels = copy.deepcopy(predictions)
        labels["target"][0] = -1
        labels["postcondition"][1] = 1
        return dict(predictions=predictions, labels=labels, supported=[True] * 3,
                    ood_rejected=[False] * 3, in_domain=[True, True, False])

    def test_complete_decision_and_ood_errors_are_counted(self):
        self.assertEqual(decision_counts(**self.inputs()),
                         {"ood_errors": 1, "ood_trials": 1, "decision_errors": 2, "decision_trials": 3})

    def test_confidence_rejection_cannot_hide_marginal_ood_acceptance(self):
        inputs = self.inputs()
        inputs["supported"] = [False] * 3
        self.assertEqual(decision_counts(**inputs),
                         {"ood_errors": 1, "ood_trials": 1, "decision_errors": 0, "decision_trials": 0})

    def test_target_required_only_when_applicable(self):
        inputs = self.inputs()
        inputs["labels"]["target"][0] = 1
        self.assertEqual(decision_counts(**inputs)["decision_errors"], 3)

    def test_support_cannot_contradict_ood_rejection(self):
        inputs = self.inputs()
        inputs["ood_rejected"][0] = True
        with self.assertRaisesRegex(ValueError, "contradicts"):
            decision_counts(**inputs)

    def test_truthy_observations_invalid_classes_and_misalignment_reject(self):
        for key, value in (("supported", [1, 1, 1]), ("in_domain", [True]), ("ood_rejected", [False, None, False])):
            inputs = self.inputs()
            inputs[key] = value
            with self.assertRaises(ValueError):
                decision_counts(**inputs)
        inputs = self.inputs()
        inputs["predictions"]["action"][0] = 6
        with self.assertRaises(ValueError):
            decision_counts(**inputs)


if __name__ == "__main__":
    unittest.main()
