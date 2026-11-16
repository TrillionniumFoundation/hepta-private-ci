"""Witness identity boundaries and failure summaries cannot imply safety."""

import copy
import unittest

from stop_census_v8 import matched_witness, summarize_repair


class CensusTests(unittest.TestCase):
    def test_witness_requires_exact_state_configuration_and_anchors(self):
        configuration = {"dt": .02, "action_bound": 4.}
        contract = {"original_old_anchors": [1.]*4, "old_panel_sha256": ["a"]*4, "training_sha256": "train"}
        snapshot = {"full_state_sha256": "origin", "contract": contract}
        repair = {"old_panel_sha256": ["a"]*4, "original_old_anchors": [1.]*4, "dt": .02, "action_bound": 4., "horizon": 8}
        branch = {"certified": True, "initial_state_sha256": "origin", "repair": repair,
            "prospective_steps": 8, "receipts": [{"dataset_sha256": "train"}]*8}
        diagnostic = {"initial_state_sha256": "origin", "configuration": configuration,
            "original_old_anchors": [1.]*4, "branches": {"full": branch, "future_field": branch}}
        self.assertTrue(matched_witness(diagnostic, snapshot, configuration, 8))
        for key, value in (("initial_state_sha256", "different"), ("original_old_anchors", [2.]*4)):
            changed = copy.deepcopy(diagnostic)
            changed[key] = value
            self.assertFalse(matched_witness(changed, snapshot, configuration, 8))
        changed = copy.deepcopy(snapshot)
        changed["contract"]["training_sha256"] = "other"
        with self.assertRaisesRegex(ValueError, "same physical task"):
            matched_witness(diagnostic, changed, configuration, 8)

    def test_competing_constraint_trials_cannot_be_combined_into_a_safe_action(self):
        trials = [{"old_losses": v, "kind": "gradient_grid"} for v in
            ([1.01, .9, .9, .9], [.9, 1.02, .9, .9])]
        repair = {"original_old_anchors": [1.]*4, "step_records": [{"status": "rejected", "trials": trials,
            "initial_state_sha256": "prospective", "parameter_hold_within_box": False}],
            "committed_optimizer_steps": 0, "certified_optimizer_steps": 0,
            "failed_at_step": 3, "prospective_safe_steps": 3, "initial_within_threshold": True,
            "initial_old_losses": [.9]*4}
        result = summarize_repair(repair)
        self.assertEqual(result["feasible_actual_trial_count"], 0)
        self.assertEqual(result["prospective_safe_steps_not_committed"], 3)
        self.assertAlmostEqual(result["best_trial_maximum_old_excess"], .01)
        self.assertFalse(result["parameter_hold_within_original_box_at_failed_step"])
        repair["step_records"][0]["trials"].append({"old_losses": [.9]*4, "kind": "gradient_grid"})
        with self.assertRaisesRegex(ValueError, "cannot contain an accepted"):
            summarize_repair(repair)


if __name__ == "__main__":
    unittest.main()
