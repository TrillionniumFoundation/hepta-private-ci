import unittest
from synthetic_matrix import (
    _receding_horizon, _simulate, _select_actions,
    independent_synthetic_episodes, run_synthetic_matrix,
)
from shadow_reference import EvidenceError, EXPERIMENT_MODES


class TestA0A5Synthetic(unittest.TestCase):
    def test_every_arm_runnable_with_matched_future_cohort(self):
        result = run_synthetic_matrix(seed=124)
        self.assertEqual(set(result["experiments"]), set(EXPERIMENT_MODES))
        self.assertEqual(result["qualification"], "SHADOW_SYNTHETIC_ONLY")
        self.assertFalse(result["selected_for_production"])
        self.assertEqual(result["covariance_supported_contexts"], ["easy", "hard"])
        for metrics in result["experiments"].values():
            self.assertEqual(metrics["episodes"], 256)
            self.assertEqual(metrics["hard_budget_violations"], 0)
            self.assertLessEqual(metrics["mean_synthetic_cost_units"], 5)

    def test_small_recursive_controller_uses_validation_then_generation(self):
        action, _ = _receding_horizon("hard", False, 5, 2)
        self.assertEqual(action, "verify")
        samples = independent_synthetic_episodes(5, 123, "future")
        hard = next((e for e in samples if e.context == "hard"), None)
        if hard is not None:
            actions, _ = _select_actions("A5", hard, 5, {}, 123)
            self.assertEqual(actions, ["verify", "fast"])

    def test_synthetic_reproducibility_except_measured_runtime(self):
        a, b = run_synthetic_matrix(seed=22), run_synthetic_matrix(seed=22)
        for mode in EXPERIMENT_MODES:
            for key in ("mean_observed_utility", "mean_quality", "mean_synthetic_cost_units"):
                self.assertEqual(a["experiments"][mode][key], b["experiments"][mode][key])

    def test_budget_and_invalid_trajectory_fail_closed(self):
        e = independent_synthetic_episodes(1, 24, "future")[0]
        for actions in (["verify", "high", "fast"], ["verify"], ["bogus"]):
            with self.assertRaises(EvidenceError):
                _simulate(e, actions, 4)

    def test_hypothesis_can_be_detected_in_toy_but_not_certified(self):
        r = run_synthetic_matrix(seed=124)["experiments"]
        self.assertGreater(r["A5"]["mean_observed_utility"], r["A0"]["mean_observed_utility"])


if __name__ == "__main__":
    unittest.main()
