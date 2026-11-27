"""Risk-sensitive information value with paid independent witnessing."""
import unittest
from fractions import Fraction
from portfolio import Config
from information_acquisition import (
    action_for_public, all_outputs, enumerate_outcomes, evaluate_policy,
    posterior, prior_from_public, query_value, score_raw_outputs,
    shared_wrong_no_new_information_bound, stop_value, weighted_cvar90,
    witness_probability,
)


class InformationTests(unittest.TestCase):
    def test_exogenous_bayes_channel_has_full_mass(self):
        prior = prior_from_public("hard")
        self.assertEqual(prior, Fraction(1, 2))
        self.assertEqual(posterior(prior, 0), Fraction(49, 50))
        self.assertEqual(posterior(prior, 1), Fraction(1, 50))
        self.assertEqual(witness_probability(prior, 0), Fraction(1, 2))
        self.assertEqual(sum(witness_probability(prior, k) for k in (0, 1)), 1)

    def test_query_only_if_public_evidence_is_ambiguous(self):
        cfg = Config(risk_aversion=1, cost_shadow_price=0.05)
        self.assertEqual(action_for_public("easy", 6, cfg), "EMIT")
        self.assertEqual(action_for_public("hard", 6, cfg), "QUERY_INDEPENDENT")
        self.assertEqual(action_for_public("hard", 4, cfg), "EMIT")
        self.assertGreater(query_value(prior_from_public("hard"), cfg),
                           stop_value(prior_from_public("hard"), cfg.risk_aversion))

    def test_selective_witness_is_cheaper_at_equal_fixture_accuracy(self):
        cfg = Config(risk_aversion=1, cost_shadow_price=0.05)
        adaptive = evaluate_policy(cfg, 6, "adaptive")
        always = evaluate_policy(cfg, 6, "always_query")
        never = evaluate_policy(cfg, 6, "never_query")
        self.assertAlmostEqual(adaptive["mean_external_loss"],
                               always["mean_external_loss"])
        self.assertLess(adaptive["mean_paid_units"], always["mean_paid_units"])
        self.assertLess(adaptive["mean_external_loss"], never["mean_external_loss"])
        self.assertGreater(adaptive["terminal_entropic_utility"],
                           always["terminal_entropic_utility"])
        self.assertGreater(adaptive["terminal_entropic_utility"],
                           never["terminal_entropic_utility"])
        self.assertEqual(adaptive["mean_paid_units"], 4.5)

    def test_four_agreeing_outputs_can_still_all_be_wrong(self):
        outputs = all_outputs(0)
        self.assertEqual(set(outputs), {"text", "audio", "image", "video"})
        self.assertEqual(score_raw_outputs(outputs, truth=0), 0)
        self.assertEqual(score_raw_outputs(outputs, truth=1), 1)
        with self.assertRaises(ValueError):
            score_raw_outputs({"text": "symbol:0"}, 1)
        with self.assertRaises(ValueError):
            score_raw_outputs(None, 1)

    def test_joint_truth_witness_mass_and_budget_accounting(self):
        cfg = Config(risk_aversion=1, cost_shadow_price=0.05)
        rows = enumerate_outcomes("hard", cfg, 5, "adaptive")
        self.assertEqual(sum(p for p, _, _ in rows), Fraction(1))
        self.assertTrue(all(paid == 5 for _, _, paid in rows))
        with self.assertRaises(ValueError):
            enumerate_outcomes("hard", cfg, 4, "always_query")
        with self.assertRaises(ValueError):
            evaluate_policy(cfg, 3, "adaptive")

    def test_no_information_purchase_when_price_exceeds_value(self):
        cfg = Config(risk_aversion=0, cost_shadow_price=1)
        self.assertEqual(action_for_public("hard", 5, cfg), "EMIT")

    def test_shared_wrong_upper_bound_without_new_information(self):
        self.assertEqual(shared_wrong_no_new_information_bound(8),
                         Fraction(1, 7))
        with self.assertRaises(ValueError):
            shared_wrong_no_new_information_bound(1)
        # The 1/7 value is for the named eight-label symmetry only.

    def test_fractional_tail_and_input_rejection(self):
        self.assertEqual(weighted_cvar90(
            [0, 1], [Fraction(9, 10), Fraction(1, 10)]), 1)
        self.assertEqual(weighted_cvar90(
            [0, 1], [Fraction(99, 100), Fraction(1, 100)]), 0.1)
        with self.assertRaises(ValueError):
            weighted_cvar90(
                [0, 1], [Fraction(11, 10), Fraction(-1, 10)])
        with self.assertRaises(ValueError):
            action_for_public("unknown", 6, Config())


if __name__ == "__main__":
    unittest.main()
