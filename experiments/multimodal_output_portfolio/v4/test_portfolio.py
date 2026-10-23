"""Independent contract, finite-risk, covariance and feedback regressions."""
import math
import unittest
from fractions import Fraction
from itertools import product

from portfolio import (
    Allocation, Config, Controller, Decoded, SHOCK_PROBS, STOP, State,
    actions, advance, charge, conditional_ce, covariance_for_action,
    decode_all, decoded_external_loss, execute, feasible,
)


class PortfolioTests(unittest.TestCase):
    def test_four_distinct_outputs_and_true_emission_reserve(self):
        cfg = Config()
        state = State((0, 1, 1, 2), 4)
        self.assertEqual(actions(state, cfg), (STOP,))
        receipt = execute(state, cfg, seed=7)
        self.assertEqual(set(receipt["outputs"]), {"text", "audio", "image", "video"})
        self.assertEqual(receipt["spent"], 4)
        self.assertEqual(receipt["remaining_after_emission"], 0)
        self.assertEqual(len(receipt["output_sha256"]), 64)
        self.assertEqual(len(receipt["trace_sha256"]), 64)
        self.assertEqual(receipt["records"][0]["allocation"], STOP.units)

    def test_different_observed_states_change_modal_allocation(self):
        cfg = Config(horizon=1, risk_aversion=0, sync_penalty=0)
        text = Controller(cfg).solve(State((0, 2, 2, 2), 10))[0]
        audio = Controller(cfg).solve(State((2, 0, 2, 2), 10))[0]
        self.assertGreater(text.units[0], 0)
        self.assertEqual(text.units[1], 0)
        self.assertGreater(audio.units[1], 0)
        self.assertEqual(audio.units[0], 0)
        self.assertNotEqual(text, audio)

    def test_non_linear_joint_decoder_and_joint_action(self):
        cfg = Config(horizon=1, risk_aversion=0, sync_penalty=5)
        state = State((2, 2, 0, 0), 12)
        base = decoded_external_loss(decode_all(state), cfg.sync_penalty)
        img_only = decoded_external_loss(decode_all(State((2, 2, 1, 0), 12)), cfg.sync_penalty)
        vid_only = decoded_external_loss(decode_all(State((2, 2, 0, 1), 12)), cfg.sync_penalty)
        both = decoded_external_loss(decode_all(State((2, 2, 1, 1), 12)), cfg.sync_penalty)
        self.assertGreater(img_only, base)
        self.assertGreater(vid_only, base)
        self.assertLess(both, base)
        chosen = Controller(cfg).solve(state)[0]
        self.assertEqual(chosen.units, (0, 0, 1, 1))

    def test_joint_shock_produces_positive_cross_modal_covariance(self):
        cfg = Config()
        cov = covariance_for_action(State((0, 0, 0, 0), 20),
                                    Allocation((1, 1, 0, 0)), cfg)
        self.assertGreater(cov[0][1], 0)
        self.assertEqual(cov[0][1], cov[1][0])
        self.assertEqual(cov[2][0], 0)
        self.assertEqual(cov[3][3], 0)

    def test_cost_charged_once_per_activation_and_budget_never_negative(self):
        cfg = Config(horizon=3, max_units_per_step=2, activation_cost=3)
        first = State((0, 0, 0, 0), 11)
        action = Allocation((1, 0, 0, 0))
        self.assertEqual(charge(first, action, cfg), 4)
        second = advance(first, action, 2, cfg)
        self.assertEqual(charge(second, action, cfg), 1)
        self.assertEqual(charge(second, Allocation((0, 1, 0, 0)), cfg), 4)
        for s in [first, second]:
            for a in actions(s, cfg):
                self.assertTrue(feasible(s, a, cfg))
                if not a.stop:
                    self.assertGreaterEqual(advance(s, a, 0, cfg).remaining,
                                            cfg.emission_reserve)
        self.assertNotIn(Allocation((1, 1, 0, 0)), actions(first, cfg))

    def test_entropy_penalizes_downside_and_stable_large_values(self):
        values = (0.0, 10.0)
        self.assertEqual(conditional_ce(values, (0.5, 0.5), 0), 5.0)
        self.assertLess(conditional_ce(values, (0.5, 0.5), 1), 5.0)
        self.assertTrue(math.isfinite(conditional_ce((-1e6, 1e6), (0.5, 0.5), 10)))
        for probs in [(0.4, 0.5), (-0.2, 1.2)]:
            with self.assertRaises(ValueError):
                conditional_ce(values, probs, 0.5)

    def test_exact_fraction_reference_for_risk_neutral_bellman(self):
        # Separate rational oracle: enumerate the non-STOP portfolios explicitly.
        # No call to Controller.solve or conditional_ce inside the reference.
        cfg = Config(horizon=2, risk_aversion=0, cost_shadow_price=0.25,
                     activation_cost=1, sync_penalty=5)
        probs = (Fraction(1, 5), Fraction(1, 4), Fraction(11, 20))

        def reference(s):
            terminal = Fraction(-decoded_external_loss(decode_all(s), 5), 1) - 1
            best = terminal
            if s.step >= 2:
                return best
            for weights in product(range(3), repeat=4):
                if not 0 < sum(weights) <= 2:
                    continue
                a = Allocation(weights)
                if not feasible(s, a, cfg):
                    continue
                val = Fraction(-charge(s, a, cfg), 4)
                for k, probability in enumerate(probs):
                    val += probability * reference(advance(s, a, k, cfg))
                best = max(best, val)
            return best

        for state in (State((2, 2, 0, 0), 11), State((0, 2, 2, 2), 9),
                      State((1, 1, 0, 0), 8), State((2, 2, 2, 2), 6)):
            self.assertAlmostEqual(Controller(cfg).solve(state)[1], float(reference(state)), places=9)

    def test_future_noise_not_known_at_decision_and_hashed_trace_is_consistent(self):
        cfg = Config(horizon=2)
        state = State((0, 2, 2, 2), 12)
        first = execute(state, cfg, seed=3)
        second = execute(state, cfg, seed=938)
        self.assertEqual(first["records"][0]["allocation"],
                         second["records"][0]["allocation"])
        for receipt in (first, second):
            self.assertEqual(receipt["scope"], "RESEARCH_ONLY_DENY_ALL")
            self.assertEqual(receipt["spent"] + receipt["remaining_after_emission"],
                             state.remaining)
            self.assertGreaterEqual(receipt["remaining_after_emission"], 0)
            self.assertEqual(receipt["records"][-1]["allocation"], STOP.units)
            self.assertLessEqual(len(receipt["records"]), cfg.horizon + 1)

    def test_fail_closed_on_missing_output_illegal_state_and_action(self):
        with self.assertRaises(ValueError):
            State((1, 2, 3, 0), 10)
        with self.assertRaises(ValueError):
            Allocation((1, 0, 0))
        with self.assertRaises(ValueError):
            actions(State((0, 0, 0, 0), 3), Config())
        with self.assertRaises(ValueError):
            decoded_external_loss(Decoded("symbol:2", (2,), ((2, 2),), ()), 5)
        with self.assertRaises(ValueError):
            advance(State((0, 0, 0, 0), 4), Allocation((1, 0, 0, 0)), 0, Config())


if __name__ == "__main__":
    unittest.main()
