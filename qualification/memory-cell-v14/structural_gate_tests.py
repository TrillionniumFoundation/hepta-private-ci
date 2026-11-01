"""Structural admission behavior, independent of the model's training details."""

import unittest

from structural_gate import KEEP, MERGE, SPLIT, assess_structure, cost_ledger, inventory, require_structural_admission


def records():
    names = KEEP + MERGE + SPLIT
    selection = {"selected": "centroid", "new_holdout_scored": False, "scores": {n: 40 for n in names}}
    selection["scores"]["centroid"] = 42
    result = {"selected": "centroid", "held_used_for_selection": False,
              "costs": {n: {"numerical_bytes": 100, "artifact_bytes": 200} for n in names},
              "models": {n: {"unrestricted": {"in_domain_correct": 65, "in_domain_total": 72, "accepted_in_domain": 72}} for n in names},
              "training_and_exploration": {"gradient": {"seconds": 3, "experts": [{"seconds": 2}]},
                 "gradient_partition_search": {"proposal_seconds": 1},
                 "gradient_calibration": [{"fold": 0, "seconds": 2, "status": "identity_after_fit_failure", "expert_example_invocations": 6}]},
              "unmeasured_costs": ["energy"]}
    result["models"]["centroid"]["unrestricted"]["in_domain_correct"] = 68
    return selection, result


class StructuralAdmissionTests(unittest.TestCase):
    def test_nonbeneficial_split_is_rejected_and_keep_preserved(self):
        selection, result = records()
        decision = assess_structure("gradient_calibrated", selection, result)
        self.assertEqual(decision["preserve_candidate"], "centroid")
        self.assertEqual(decision["actual_held_correctness_gain"], -3)
        with self.assertRaises(RuntimeError):
            require_structural_admission(decision)

    def test_merge_is_eligible_for_calibration_selection(self):
        selection, result = records()
        selection["scores"]["merge_retrain"] = 43
        selection["selected"] = result["selected"] = "merge_retrain"
        self.assertEqual(inventory(selection, result), "merge_retrain")
        self.assertEqual(assess_structure("gradient_raw", selection, result)["preserve_candidate"], "merge_retrain")

    def test_selected_merge_is_compared_with_keep_not_itself(self):
        selection, result = records()
        selection["scores"]["merge_retrain"] = 43
        selection["selected"] = result["selected"] = "merge_retrain"
        decision = assess_structure("merge_retrain", selection, result)
        self.assertEqual(decision["preserve_candidate"], "centroid")
        self.assertEqual(decision["actual_held_correctness_gain"], -3)
        self.assertIn("no_actual_held_advantage_or_noninferiority", decision["reasons"])

    def test_held_ids_must_match_not_only_counts(self):
        selection, result = records()
        result["models"]["centroid"]["unrestricted"]["traces"] = [{"id": "same-count-a"}]
        result["models"]["gradient_calibrated"]["unrestricted"]["traces"] = [{"id": "same-count-b"}]
        with self.assertRaises(ValueError):
            assess_structure("gradient_calibrated", selection, result)

    def test_no_split_without_bound_retention_and_cost_evidence(self):
        selection, result = records()
        selection["scores"]["fixed_calibrated"] = 44
        selection["selected"] = result["selected"] = "fixed_calibrated"
        result["models"]["fixed_calibrated"]["unrestricted"]["in_domain_correct"] = 70
        rejected = assess_structure("fixed_calibrated", selection, result)
        self.assertFalse(rejected["approved"])
        binding = {"candidate": "fixed_calibrated", "evidence_identity": rejected["evidence_identity"]}
        retention = {**binding, "passed": True, "new_and_old_tasks_checked": True}
        economics = {**binding, "complete_costs": True, "all_exploration_charged": True,
                     "lower_bound_net_value": 1, "expected_reads": 1000}
        decision = assess_structure("fixed_calibrated", selection, result, retention=retention, economics=economics)
        self.assertEqual(require_structural_admission(decision), binding["evidence_identity"])
        economics["candidate"] = "gradient_calibrated"
        self.assertFalse(assess_structure("fixed_calibrated", selection, result, retention=retention, economics=economics)["approved"])

    def test_all_exploration_including_failure_counted_once(self):
        _, result = records()
        cost = cost_ledger(result)
        self.assertEqual(cost["all_stage_seconds"], 6)
        self.assertEqual(cost["all_saved_candidate_artifact_bytes"], 14 * 200)
        self.assertEqual(cost["nonselected_saved_candidate_artifact_bytes"], 13 * 200)

    def test_incomplete_baseline_inventory_and_held_selection_refused(self):
        selection, result = records()
        del selection["scores"]["ridge"]
        with self.assertRaises(ValueError):
            inventory(selection, result)
        selection, result = records()
        result["held_used_for_selection"] = True
        with self.assertRaises(ValueError):
            inventory(selection, result)


if __name__ == "__main__":
    unittest.main()
