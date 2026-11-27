"""External-path audits: finite Bellman parity, shift and emission reserve."""
import unittest

from portfolio import Allocation, Config, Controller, State, STOP
from counterfactual_audit import (
    advance_joint, best_open_loop, check_dependence_regime, check_joint_law,
    empirical_cvar90, paired_dependence_shift, paired_nominal_shift, rollout,
)


class CounterfactualAuditTests(unittest.TestCase):
    def test_independent_complete_tree_matches_controller_value(self):
        cfg = Config(horizon=2, risk_aversion=0.5, cost_shadow_price=0.1)
        state = State((0, 0, 0, 0), 12)
        review = paired_nominal_shift(state, cfg, (0.7, 0.2, 0.1))
        self.assertTrue(review["nominal_exact_bellman_parity"])
        self.assertGreaterEqual(review["nominal_dynamic"]["conditional_utility"] + 1e-8,
                                review["nominal_open_loop"]["conditional_utility"])
        self.assertTrue(review["nominal_dynamic"]["complete_outputs"])
        self.assertTrue(review["nominal_open_loop"]["all_budget_feasible"])
        self.assertGreater(review["nominal_dynamic"]["distinct_allocation_traces"], 1)

    def test_dependence_shift_can_reverse_risk_utility_and_cvar(self):
        # Better mean output loss does not entail better downside protection.
        # A nominal finite Bellman certificate cannot be exported to a shifted
        # cross-modality covariance without new evidence and assumptions.
        cfg = Config(horizon=2, risk_aversion=0.5, cost_shadow_price=0.1)
        state = State((0, 0, 0, 0), 12)
        regime = (((0, 2, 0, 2), 0.45),
                  ((2, 0, 2, 0), 0.45),
                  ((1, 1, 1, 1), 0.10))
        review = paired_dependence_shift(state, cfg, regime)
        dynamic = review["dependence_dynamic"]
        static = review["dependence_open_loop"]
        self.assertLess(dynamic["mean_loss"], static["mean_loss"])
        self.assertGreater(dynamic["cvar90_decoded_loss"], static["cvar90_decoded_loss"])
        self.assertLess(dynamic["conditional_utility"], static["conditional_utility"])
        self.assertTrue(review["no_out_of_envelope_robustness_claim"])

    def test_no_controller_access_to_future_noise(self):
        cfg = Config(horizon=2, risk_aversion=0)
        state = State((0, 0, 0, 0), 12)
        controller = Controller(cfg)
        policy = lambda s: controller.solve(s)[0]
        left = rollout(state, cfg, (0, 2), policy)
        right = rollout(state, cfg, (2, 0), policy)
        self.assertEqual(left["allocation_trace"][0], right["allocation_trace"][0])
        self.assertLessEqual(left["paid_units"], state.remaining)
        self.assertLessEqual(right["paid_units"], state.remaining)

    def test_four_outputs_always_charge_mandatory_reserve(self):
        cfg = Config()
        observed = rollout(State((0, 1, 2, 0), 4), cfg, (0, 1), lambda _: STOP)
        self.assertEqual(observed["paid_units"], 4)
        self.assertEqual(observed["remaining_after_emission"], 0)
        self.assertEqual(set(observed["decoded_modalities"]),
                         {"text", "audio", "image", "video"})

    def test_fractional_weighted_upper_tail_cvar(self):
        losses = [0.0] * 10 + [10.0]
        probs = [1 / 11] * 11
        self.assertAlmostEqual(empirical_cvar90(losses, probs), 100 / 11,
                               places=11)

    def test_negative_cross_modal_dependence_is_observable(self):
        cfg = Config(horizon=1)
        state = State((0, 0, 0, 0), 12)
        action = Allocation((1, 0, 0, 1))
        first = advance_joint(state, action, (0, 0, 2, 2), cfg)
        second = advance_joint(state, action, (2, 2, 0, 0), cfg)
        self.assertEqual((first.levels[0], first.levels[3]), (0, 1))
        self.assertEqual((second.levels[0], second.levels[3]), (1, 0))
        self.assertEqual(first.remaining, second.remaining)
        self.assertLess(0.5 * (0 - 0.5) * (1 - 0.5)
                        + 0.5 * (1 - 0.5) * (0 - 0.5), 0)

    def test_invalid_regimes_fail_closed(self):
        with self.assertRaises(ValueError):
            check_joint_law((0.2, 0.3, 0.5000000005))
        with self.assertRaises(ValueError):
            check_dependence_regime((((0, 0, 0, 0), 0.8),
                                     ((0, 0, 0, 0), 0.2)))
        with self.assertRaises(ValueError):
            check_dependence_regime((((0, 0, 0, 0), 0.6),))
        with self.assertRaises(ValueError):
            advance_joint(State((0, 0, 0, 0), 10),
                          Allocation((1, 0, 0, 0)), (2, 0, 0, 3), Config())

    def test_exponential_open_loop_search_rejects_over_cap(self):
        cfg = Config(horizon=3, max_units_per_step=3)
        with self.assertRaisesRegex(ValueError, "resource cap"):
            best_open_loop(State((0, 0, 0, 0), 20), cfg)


if __name__ == "__main__":
    unittest.main()
