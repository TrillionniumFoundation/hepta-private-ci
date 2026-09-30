"""Real metric and eligibility regressions without ML runtime dependencies."""
import copy
import unittest
from decision_cell_metrics import EVALUATION_PROFILE, HEADS, quality_gates, recommendations, selection_statistics, verify_summary_projection


class DecisionMetricTests(unittest.TestCase):
    def metrics(self, **overrides):
        labels = {name: [0, 1] for name in HEADS}
        args = dict(predictions=copy.deepcopy(labels), labels=labels,
                    confidence_accepted=[True, True], ood_rejected=[False, False],
                    in_domain=[True, True])
        return selection_statistics(**{**args, **overrides})

    def good_receipt(self):
        return {"evaluation_profile": EVALUATION_PROFILE,
                "test_metrics": dict(action_accuracy=1.0, target_accuracy=1.0,
                    disposition_accuracy=1.0, postcondition_accuracy=1.0,
                    joint_exact_accuracy=1.0, confidence_error=0.0,
                    supported_in_domain_rows=48, supported_in_domain_coverage=0.5,
                    supported_joint_error=0.0),
                "ood_test_metrics": {"ood_false_acceptance": 0.0}}

    def test_wrong_postcondition_is_not_jointly_correct(self):
        predictions = {name: [0, 1] for name in HEADS}
        predictions["postcondition"] = [1, 0]
        observed = self.metrics(predictions=predictions)
        self.assertEqual(observed["joint_exact_accuracy"], 0.0)
        self.assertEqual(observed["supported_joint_error"], 1.0)

    def test_non_target_actions_do_not_require_a_fabricated_pointer(self):
        labels = {name: [0, 1] for name in HEADS}
        labels["target"] = [-1, 1]
        self.assertEqual(self.metrics(labels=labels)["joint_exact_accuracy"], 1.0)

    def test_all_ood_rejected_is_not_zero_supported_risk(self):
        observed = self.metrics(ood_rejected=[True, True])
        self.assertIsNone(observed["supported_joint_error"])
        self.assertIsNone(observed["supported_joint_error_wilson95_upper"])
        self.assertEqual(observed["supported_in_domain_coverage"], 0.0)

    def test_confidence_and_ood_filters_are_applied_jointly(self):
        observed = self.metrics(confidence_accepted=[True, False], ood_rejected=[True, False])
        self.assertEqual(observed["supported_rows"], 0)
        self.assertIsNone(observed["supported_joint_error"])

    def test_accepted_ood_is_an_error_even_with_matching_labels(self):
        observed = self.metrics(in_domain=[False, True])
        self.assertEqual(observed["supported_joint_error"], 0.5)
        self.assertEqual(observed["supported_in_domain_rows"], 1)

    def test_zero_errors_retains_nonzero_uncertainty(self):
        observed = self.metrics()
        self.assertGreater(observed["supported_joint_error_wilson95_upper"], 0.0)
        self.assertLessEqual(observed["supported_joint_error_wilson95_upper"], 1.0)

    def test_empty_or_misaligned_observations_reject(self):
        for patch in ({"in_domain": []}, {"confidence_accepted": [True]},
                      {"ood_rejected": [1, 0]}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.metrics(**patch)

    def test_invalid_head_labels_reject(self):
        for name in HEADS:
            labels = {key: [0, 1] for key in HEADS}
            labels[name][0] = 99
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.metrics(labels=labels)

    def test_positive_candidate_remains_eligible(self):
        self.assertTrue(all(quality_gates(self.good_receipt()).values()))

    def test_no_coverage_candidate_cannot_win_on_zero_error(self):
        receipt = self.good_receipt()
        receipt["test_metrics"].update(supported_in_domain_rows=0,
            supported_in_domain_coverage=0.0, supported_joint_error=None)
        self.assertFalse(all(quality_gates(receipt).values()))

    def test_action_accuracy_cannot_hide_bad_supported_targets(self):
        receipt = self.good_receipt()
        receipt["test_metrics"]["supported_joint_error"] = 0.4
        self.assertFalse(all(quality_gates(receipt).values()))

    def test_old_profile_cannot_be_relabelled_as_new_evidence(self):
        receipt = self.good_receipt()
        del receipt["evaluation_profile"]
        self.assertFalse(quality_gates(receipt)["current_evaluation_profile"])

    def test_rehashed_summary_cannot_change_verified_results_or_authority(self):
        rows = [{"model_name": "candidate", "receipt_sha256": "a" * 64, "score": 0.5,
                 "quality_eligible": True, "internal_shadow_eligible": True,
                 "distribution_candidate_eligible": False}]
        summary = {"models": rows, **recommendations(rows), "evaluation_profile": EVALUATION_PROFILE,
                   "evaluation_implementation_sha256": "b" * 64, "candidate_scope": "synthetic_fixture_only",
                   "selection_authority": False, "runtime_selection_eligible": False,
                   "operator_acceptance": False, "production_activation": False,
                   "prospective_future_window_evidence": False}
        verify_summary_projection(summary, rows, "b" * 64)
        variants = []
        for name in ("selection_authority", "runtime_selection_eligible", "operator_acceptance",
                     "production_activation", "prospective_future_window_evidence"):
            variants.append({**summary, name: True})
        changed = copy.deepcopy(summary)
        changed["models"][0]["score"] = 999.0
        variants.append(changed)
        changed = copy.deepcopy(summary)
        changed["internal_shadow_recommendation"]["model_name"] = "unverified-model"
        variants.append(changed)
        variants.append({**summary, "evaluation_implementation_sha256": "c" * 64})
        for changed in variants:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                verify_summary_projection(changed, rows, "b" * 64)

    def test_no_eligible_candidate_produces_no_recommendation(self):
        rows = [{"model_name": "candidate", "score": 100.0,
                 "internal_shadow_eligible": False, "distribution_candidate_eligible": False}]
        self.assertEqual(recommendations(rows), {"internal_shadow_recommendation": None,
                                               "distribution_candidate_recommendation": None})

    def test_missing_nonfinite_and_boolean_metrics_are_not_passes(self):
        for value in (None, float("nan"), float("inf"), True, -0.1, 1.1):
            receipt = self.good_receipt()
            receipt["test_metrics"]["action_accuracy"] = value
            with self.subTest(value=value):
                self.assertFalse(quality_gates(receipt)["action_accuracy_at_least_0_80"])


if __name__ == "__main__":
    unittest.main()
