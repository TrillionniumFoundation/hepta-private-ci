"""Security, stochastic regression, equal-budget and real-tensor shadow tests."""

import importlib.util
import math
import random
import unittest

from hepta_sngr_cell_pilot import (
    CallMeter,
    CellServing,
    PilotError,
    MAX_PROBES,
    check_context,
    exact_posterior,
    generate_training_rows,
    martingale_z,
    oracle_action,
    oracle_targets,
    oracle_value,
    plan_choice,
    probability_of_positive,
    run_episode,
    run_pilot,
    sample_episode,
    tensorize,
    train_network,
)

HAS_TORCH = importlib.util.find_spec("torch") is not None


class ConditionalOracleTests(unittest.TestCase):
    def test_posterior_balanced_before_any_evidence(self):
        self.assertEqual(exact_posterior(0.72, ()), 0.5)
        p_plus = exact_posterior(0.72, (1,))
        p_minus = exact_posterior(0.72, (-1,))
        self.assertAlmostEqual(p_plus, 0.72)
        self.assertAlmostEqual(p_minus, 0.28)
        self.assertAlmostEqual(p_plus + p_minus, 1.0)

    def test_oracle_value_obeys_stop_constraint_and_budget(self):
        for r in (0.61, 0.7, 0.84):
            for c in (0.025, 0.07, 0.13):
                for s in range(-MAX_PROBES, MAX_PROBES + 1, 2):
                    p = exact_posterior(r, (1,) * max(s, 0) + (-1,) * max(-s, 0))
                    value = oracle_value(r, c, MAX_PROBES, s)
                    self.assertAlmostEqual(value, max(p, 1 - p))
                initial = oracle_value(r, c, 0, 0)
                self.assertGreaterEqual(initial, 0.5)
                self.assertLessEqual(initial, 1.0)

    def test_conditional_z_sigma_equals_centered_covariance(self):
        for q in (0.2, 0.5, 0.8):
            z, sigma, cross = martingale_z(0.91, 0.33, q)
            self.assertAlmostEqual(z, 0.29)
            self.assertAlmostEqual(z * sigma, cross)
            self.assertGreater(sigma, 0)

    def test_z_rejects_singular_or_nonfinite_support(self):
        for bad_q in (0.0, 1.0, math.nan, math.inf, -0.2):
            with self.subTest(q=bad_q), self.assertRaises(PilotError):
                martingale_z(1.0, 0.0, bad_q)
        with self.assertRaises(PilotError):
            martingale_z(math.inf, 0.3, 0.5)

    def test_a_stopped_policy_has_zero_active_z(self):
        p, value, z = oracle_targets(0.7, 0.14, (1, 1, 1))
        self.assertAlmostEqual(p, 0.927027, places=4)
        self.assertEqual(z, 0)
        self.assertAlmostEqual(value, p)

    def test_more_probe_cost_cannot_increase_optimal_value(self):
        low = oracle_value(0.74, 0.02, 0, 0)
        high = oracle_value(0.74, 0.14, 0, 0)
        self.assertGreaterEqual(low, high)

    def test_reject_invalid_context_and_unauthorized_tokens(self):
        bad = ((0.9, 0.04, ()), (0.7, -0.1, ()), (0.7, 0.04, (2,)),
               (0.7, 0.04, (True,)), (0.7, 0.04, (1,) * 6),
               (math.nan, 0.04, ()), (0.7, math.inf, ()))
        for p, c, obs in bad:
            with self.subTest(p=p, c=c, obs=obs), self.assertRaises(PilotError):
                check_context(p, c, obs)

    def test_generator_seeds_produce_independent_task_scopes(self):
        a, a_targets = generate_training_rows(128, 101)
        b, b_targets = generate_training_rows(128, 303)
        self.assertEqual((a, a_targets), generate_training_rows(128, 101))
        self.assertFalse(set(a).intersection(b))
        self.assertEqual(len(a_targets), 128)
        for state, target in zip(a, a_targets):
            self.assertEqual(oracle_targets(state[1], state[2], state[0]), target)

    def test_oracle_uses_actual_terminal_budget(self):
        self.assertEqual(oracle_action(0.75, 0.06, (1,) * MAX_PROBES), "stop")
        self.assertEqual(oracle_action(0.74, 0.02, ()), "probe")


@unittest.skipUnless(HAS_TORCH, "optional PyTorch not installed; train only in explicitly opted-in pilot")
class NeuralServingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model, cls.training = train_network(seed=41, train_samples=512, steps=60)
        import torch
        cls.torch = torch

    def test_single_physical_encoder_shared_by_three_heads(self):
        serving = CellServing(self.model, self.torch, CallMeter(max_calls=2))
        p = serving.predict((1, -1), 0.72, 0.07)
        self.assertTrue(0 < p.posterior < 1)
        self.assertTrue(math.isfinite(p.utility) and math.isfinite(p.z))
        self.assertEqual(serving.predict((1, -1), 0.72, 0.07), p)
        self.assertEqual(serving.meter.physical_encoder_calls, 1)
        self.assertEqual(serving.meter.head_evaluations, 3)
        self.assertEqual(serving.meter.cache_hits, 1)
        self.assertIsNotNone(self.model.utility_head)
        self.assertIsNotNone(self.model.posterior_head)
        self.assertIsNotNone(self.model.z_head)

    def test_selected_model_is_frozen_and_training_mode_rejected(self):
        self.assertTrue(all(not p.requires_grad for p in self.model.parameters()))
        self.assertFalse(self.model.training)
        self.model.train()
        with self.assertRaisesRegex(PilotError, "frozen"):
            CellServing(self.model, self.torch, CallMeter(max_calls=2))
        self.model.eval()
        CellServing(self.model, self.torch, CallMeter(max_calls=2))

    def test_inference_budget_and_scoped_fallback_fail_closed(self):
        serving = CellServing(self.model, self.torch, CallMeter(max_calls=1))
        serving.predict((), 0.71, 0.06)
        with self.assertRaisesRegex(PilotError, "budget"):
            serving.predict((1,), 0.71, 0.06)
        self.assertEqual(serving.meter.physical_encoder_calls, 1)
        other_episode = CellServing(self.model, self.torch, CallMeter(max_calls=1))
        self.assertEqual(other_episode.meter.physical_encoder_calls, 0)

    def test_padding_does_not_inject_future_probes(self):
        states = [((), 0.71, 0.06), ((1,), 0.71, 0.06), ((1, -1), 0.71, 0.06)]
        ids, features, mask = tensorize(self.torch, states)
        self.assertEqual(ids.shape, (3, MAX_PROBES + 1))
        self.assertEqual(features.shape, (3, 3))
        self.assertTrue(mask[0, 1:].all())
        self.assertFalse(mask[1, 1])

    def test_bounded_tree_validates_budget_and_reuses_model(self):
        serving = CellServing(self.model, self.torch, CallMeter(max_calls=63))
        action, disagreement = plan_choice(serving, (), 0.71, 0.06, depth=2)
        self.assertIn(action, ("probe", "stop"))
        self.assertGreaterEqual(disagreement, 0)
        self.assertLessEqual(serving.meter.physical_encoder_calls, 7)
        with self.assertRaises(PilotError):
            plan_choice(serving, (), 0.71, 0.06, depth=100)

    def test_actual_episode_runs_with_independently_hidden_answer(self):
        hidden, obs = sample_episode(random.Random(31), 0.73)
        for policy in ("oracle_full", "oracle_policy_neural_answer", "stop_now",
                       "fixed_3", "bellman_h2", "ndu_h2", "value_bellman_h2", "ndu_adaptive_h2", "value_bellman_adaptive_h2"):
            output = run_episode(self.model, self.torch, hidden, obs, 0.73, 0.06, policy)
            self.assertIn(output["correct"], (0, 1))
            self.assertGreaterEqual(output["probes"], 0)
            self.assertLessEqual(output["probes"], MAX_PROBES)
            self.assertLessEqual(output["encoder_calls"], 63)
        self.assertEqual(run_episode(self.model, self.torch, hidden, obs, 0.73, 0.06, "oracle_full")["encoder_calls"], 0)

    def test_compute_gated_policy_reuses_shared_head(self):
        hidden, obs = sample_episode(random.Random(99), 0.77)
        a = run_episode(self.model, self.torch, hidden, obs, 0.77, 0.08, "ndu_adaptive_h2")
        b = run_episode(self.model, self.torch, hidden, obs, 0.77, 0.08, "value_bellman_adaptive_h2")
        self.assertEqual(a, b)
        self.assertLessEqual(a["encoder_calls"], 63)

    def test_bellman_ndu_additive_value_parity(self):
        hidden, obs = sample_episode(random.Random(99), 0.77)
        a = run_episode(self.model, self.torch, hidden, obs, 0.77, 0.08, "ndu_h2")
        b = run_episode(self.model, self.torch, hidden, obs, 0.77, 0.08, "value_bellman_h2")
        self.assertEqual(a, b)


@unittest.skipUnless(HAS_TORCH, "optional PyTorch not installed; synthetic learning omitted")
class EndToEndPilotTests(unittest.TestCase):
    def test_end_to_end_neural_training_receipt_has_reproducible_weights(self):
        first = run_pilot(seed=121, train_samples=256, steps=80, episodes=16, heldout_examples=128)
        second = run_pilot(seed=121, train_samples=256, steps=80, episodes=16, heldout_examples=128)
        self.assertEqual(first["model_snapshot_sha256"], second["model_snapshot_sha256"])
        self.assertEqual(first["training"]["synthetic_training_dataset_sha256"], second["training"]["synthetic_training_dataset_sha256"])
        self.assertEqual(first["results"]["ndu_h2"]["mean_net_reward"],
                         second["results"]["ndu_h2"]["mean_net_reward"])
        self.assertEqual(first["paired_reward_delta_bootstrap_ci_95pct"]["ndu_minus_identical_value_bellman"], [0.0, 0.0])
        self.assertGreater(first["shared_stem_parameters"], first["exclusive_heads_parameters"])
        self.assertFalse(first["real_laya_execution"])
        self.assertIsNone(first["continuous_time_fbsde_convergence"])

    def test_evaluation_budget_preflight(self):
        for parameters in ({"heldout_examples":127}, {"episodes":0}, {"max_calls":0}):
            with self.subTest(parameters=parameters), self.assertRaises(PilotError):
                run_pilot(steps=1, train_samples=256, **parameters)


if __name__ == "__main__":
    unittest.main()
