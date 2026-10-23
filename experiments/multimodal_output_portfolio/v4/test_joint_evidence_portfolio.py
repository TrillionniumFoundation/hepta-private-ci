"""Adversarial tests for jointly costed QUERY/REFINE/EMIT (toy only)."""
from fractions import Fraction
import math
import unittest

from portfolio import Config, State
from joint_evidence_portfolio import (
    EMIT, QUERY, JointAction, JointController, JointState,
    emission, offline_audit, public_state, query_next, raw_output_loss,
)


class JointEvidencePortfolioTests(unittest.TestCase):

    def test_query_hard_but_not_easy_under_same_generation_state(self):
        cfg = Config(horizon=1, risk_aversion=1, cost_shadow_price=0.05)
        controller = JointController(cfg)
        hard = public_state("hard", (2, 2, 2, 2), 5)
        easy = public_state("easy", (2, 2, 2, 2), 5)
        self.assertEqual(controller.solve(hard)[0], QUERY)
        self.assertEqual(controller.solve(easy)[0], EMIT)

    def test_observable_generation_levels_change_value_of_refinement(self):
        cfg = Config(horizon=1, risk_aversion=0, cost_shadow_price=0.05)
        controller = JointController(cfg, allow_query=False)
        complete = public_state("easy", (2, 2, 2, 2), 8)
        incomplete = public_state("easy", (2, 2, 0, 0), 8)
        self.assertEqual(controller.solve(complete)[0], EMIT)
        choice = controller.solve(incomplete)[0]
        self.assertEqual(choice.kind, "REFINE")
        self.assertEqual(choice.allocation.units, (0, 0, 1, 1))

    def test_evidence_and_generator_compete_for_same_finite_budget(self):
        cfg = Config(horizon=1, risk_aversion=1, cost_shadow_price=0.05)
        c = JointController(cfg)
        hard = public_state("hard", (2, 2, 2, 2), 5)
        self.assertEqual(c.solve(hard)[0], QUERY)
        after = query_next(hard, 0, 1, cfg)
        self.assertEqual(after.generation.remaining, cfg.emission_reserve)
        self.assertTrue(after.queried)
        self.assertEqual(c.solve(after)[0], EMIT)
        self.assertEqual(set(emission(after)), {"text","audio","image","video"})
        with self.assertRaises(ValueError):
            query_next(after, 1, 1, cfg)
        with self.assertRaises(ValueError):
            query_next(public_state("hard", (2,2,2,2), 4), 0, 1, cfg)

    def test_independent_truth_does_not_follow_cross_modal_agreement(self):
        cfg = Config()
        state = public_state("hard", (2, 2, 2, 2), 4)
        raw = emission(state)
        self.assertEqual({part[0] for part in raw.values()}, {0})
        self.assertEqual(raw_output_loss(raw, 0, cfg, 12), 0)
        self.assertEqual(raw_output_loss(raw, 1, cfg, 12), 12)
        raw["video"] = (1, raw["video"][1])
        with self.assertRaisesRegex(ValueError, "conflict"):
            raw_output_loss(raw, 0, cfg, 12)

    def test_full_path_decoded_utility_equals_backward_bellman(self):
        for gamma in (0, 0.5, 2):
            with self.subTest(gamma=gamma):
                cfg = Config(horizon=2, risk_aversion=gamma,
                             cost_shadow_price=0.05)
                model = JointController(cfg)
                for mode, levels, budget in (
                    ("hard", (2,2,2,2), 5),
                    ("easy", (2,2,0,0), 8),
                    ("hard", (1,1,0,0), 9),
                ):
                    state = public_state(mode, levels, budget)
                    selected, value = model.solve(state)
                    measured = offline_audit(state, model)
                    self.assertTrue(math.isfinite(value))
                    self.assertAlmostEqual(
                        value, measured["full_path_utility"], places=8)
                    self.assertTrue(measured["four_outputs_every_path"])
                    self.assertTrue(measured["all_budget_feasible"])
                    self.assertGreaterEqual(measured["path_count"], 1)
                    self.assertIn(selected.kind, ("QUERY","REFINE","EMIT"))

    def test_adaptive_paid_witness_improves_true_loss_over_no_query(self):
        cfg = Config(horizon=1, risk_aversion=1, cost_shadow_price=0.05)
        state = public_state("hard", (2,2,2,2), 5)
        adaptive = JointController(cfg)
        no_query = JointController(cfg, allow_query=False)
        a = offline_audit(state, adaptive)
        b = offline_audit(state, no_query)
        self.assertLess(a["mean_external_loss"], b["mean_external_loss"])
        self.assertGreater(a["mean_modeled_units"], b["mean_modeled_units"])
        self.assertGreater(a["full_path_utility"], b["full_path_utility"])
        self.assertAlmostEqual(a["mean_external_loss"], 12/50)
        self.assertAlmostEqual(b["mean_external_loss"], 6)
        self.assertAlmostEqual(a["mean_modeled_units"], 5)
        self.assertAlmostEqual(b["mean_modeled_units"], 4)

    def test_query_policy_only_sees_observed_belief_not_future_truth(self):
        cfg = Config(horizon=1, risk_aversion=1)
        model = JointController(cfg)
        state = public_state("hard", (2,2,2,2), 5)
        decision = model.solve(state)[0]
        self.assertEqual(decision, QUERY)
        # Changing a hidden offline truth value cannot be passed to solve().
        self.assertEqual(model.solve(state)[0], decision)
        self.assertEqual(query_next(state, 0, 1, cfg).belief_zero,
                         Fraction(49, 50))
        self.assertEqual(query_next(state, 1, 1, cfg).belief_zero,
                         Fraction(1, 50))

    def test_miscalibrated_shared_wrong_witness_reverses_advantage(self):
        # This is a new environment law: the sensor is wrong 49/50 of the
        # time, but the FROZEN nominal policy still believes it is 49/50
        # accurate. More nominal information can cause worse actual quality.
        cfg = Config(horizon=1, risk_aversion=1, cost_shadow_price=0.05)
        state = public_state("hard", (2,2,2,2), 5)
        adaptive = JointController(cfg)
        no_query = JointController(cfg, allow_query=False)
        nominal = offline_audit(state, adaptive)
        shifted = offline_audit(
            state, adaptive,
            observed_witness_accuracy=Fraction(1, 50))
        static_shift = offline_audit(
            state, no_query,
            observed_witness_accuracy=Fraction(1, 50))
        self.assertAlmostEqual(nominal["mean_external_loss"], 0.24)
        self.assertAlmostEqual(shifted["mean_external_loss"], 11.76)
        self.assertAlmostEqual(static_shift["mean_external_loss"], 6)
        self.assertLess(shifted["full_path_utility"],
                        static_shift["full_path_utility"])
        self.assertLess(shifted["full_path_utility"],
                        nominal["full_path_utility"])
        self.assertTrue(shifted["off_nominal_witness_law"])
        self.assertTrue(shifted["four_outputs_every_path"])
        self.assertTrue(shifted["all_budget_feasible"])
        # Unlike nominal full-path parity, the shifted environment should
        # NOT be passed off as an NDU model calibration certificate.
        self.assertNotAlmostEqual(
            adaptive.solve(state)[1], shifted["full_path_utility"],
            places=4)

    def test_shift_audit_rejects_invalid_witness_likelihood(self):
        state = public_state("hard", (2,2,2,2), 5)
        controller = JointController(Config())
        for bad in (0.5, True, Fraction(-1, 10), Fraction(11, 10)):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    offline_audit(state, controller,
                                  observed_witness_accuracy=bad)

    def test_invalid_data_authority_and_actions_reject(self):
        cfg = Config()
        with self.assertRaises(ValueError):
            JointState(State((0,0,0,0), 8), 0.5)
        with self.assertRaises(ValueError):
            JointState(State((0,0,0,0), 8), Fraction(2))
        with self.assertRaises(ValueError):
            JointAction("QUERY", __import__("portfolio").Allocation((1,0,0,0)))
        with self.assertRaises(ValueError):
            JointAction("REFINE")
        for data in ({"query_units": True}, {"factual_penalty": 0},
                     {"allow_query": 1}, {"allow_refine": "yes"}):
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    JointController(cfg, **data)
        with self.assertRaises(ValueError):
            offline_audit(public_state("easy", (0,0,0,0), 3),
                          JointController(cfg))

    def test_independent_audit_rejects_unfunded_or_malformed_policy(self):
        cfg = Config(horizon=1)
        controller = JointController(cfg)
        state = public_state("hard", (2,2,2,2), 4)
        with self.assertRaises(ValueError):
            offline_audit(state, controller, policy=lambda s: QUERY)
        with self.assertRaises(ValueError):
            offline_audit(state, controller, policy=lambda s: "QUERY")
        with self.assertRaises(ValueError):
            offline_audit(state, controller, max_outcomes=0)


if __name__ == "__main__":
    unittest.main()
