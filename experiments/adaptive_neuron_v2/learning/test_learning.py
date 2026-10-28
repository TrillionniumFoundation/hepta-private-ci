"""Development-only derivative and native readout contract checks."""

import copy
import json
import unittest

import numpy as np

from experiments.free_boundary_neuron.math.hitting import hit_probability_and_gradient

from .kernel import activation, initial_raw, physical
from .meta import bilevel_step, check_hypergradient, train
from .network import (
    forward,
    initial_state,
    initialize,
    loss_gradient,
    model_payload,
    step,
)
from .task import make_batch


class KernelTests(unittest.TestCase):
    def test_probability_and_slope_match_independent_sealed_operator(self):
        values = np.array([-20.0, -7.0, -2.0, -0.3, -1e-4, 0.0, 0.2])
        for raw in (
            initial_raw(),
            np.array([-1.7, -2.0, 1.1]),
            np.array([1.2, 1.3, -3.1]),
        ):
            theta, _ = physical(raw)
            expected = hit_probability_and_gradient(
                -values, 1.0, *theta[:2], rate=theta[2]
            )
            actual, slope, _ = activation(
                values, raw, "first_passage", soft=True, mixed=True
            )
            np.testing.assert_allclose(actual, expected[0], rtol=2e-12, atol=2e-14)
            np.testing.assert_allclose(slope, expected[1], rtol=2e-12, atol=2e-14)

    def test_mixed_kernel_derivatives_agree_at_two_step_sizes(self):
        values = np.array([-12.0, -5.0, -1.2, -0.1, 0.1])
        for raw in (initial_raw(), np.array([-1.0, -1.5, 1.0])):
            _, _, exact = activation(values, raw, "first_passage", mixed=True)
            for epsilon in (1e-4, 2e-5):
                for channel in range(3):
                    direction = np.zeros(3)
                    direction[channel] = epsilon
                    plus = activation(values, raw + direction, "first_passage")[1]
                    minus = activation(values, raw - direction, "first_passage")[1]
                    np.testing.assert_allclose(
                        exact[..., channel],
                        (plus - minus) / (2 * epsilon),
                        rtol=3e-6,
                        atol=3e-9,
                    )

    def test_compact_parameterization_rejects_invalid_inputs(self):
        for raw in ([0.0, np.inf, 0.0], [0.0, 6.1, 0.0], [1.0]):
            with self.assertRaises(ValueError):
                physical(raw)


class NeuralTests(unittest.TestCase):
    def setUp(self):
        self.raw = initial_raw()
        self.parameters = initialize(910001)
        self.support = make_batch(910001, 0, "development", (0.68, 0.04, 8), 5)
        self.query = make_batch(910002, 1, "development", (0.68, 0.04, 8), 5)

    def test_native_scalar_step_matches_hard_batch_and_prefix_causality(self):
        voltage, tape = forward(
            self.parameters, self.support, self.raw, "first_passage"
        )
        for episode, row in enumerate(self.support.observations):
            state = initial_state()
            for time_index, observation in enumerate(row):
                state, result = step(
                    self.parameters,
                    state,
                    int(observation),
                    0.68,
                    0.04,
                    8,
                    time_index + 1,
                )
                self.assertAlmostEqual(
                    result["logit"], voltage[episode, time_index], places=12
                )
                self.assertEqual(
                    result["spikes"], tape["spike_counts"][episode, time_index]
                )
        altered = copy.deepcopy(self.support)
        altered.features[:, 5:] *= -1
        after = forward(self.parameters, altered, self.raw, "first_passage")[0]
        np.testing.assert_array_equal(voltage[:, :5], after[:, :5])

    def test_query_gradient_is_ordinary_soft_objective_derivative(self):
        _, gradient, _, _ = loss_gradient(
            self.parameters, self.query, self.raw, "standard", soft=True
        )
        random = np.random.default_rng(910003)
        for _ in range(3):
            direction = {
                key: random.normal(size=value.shape)
                for key, value in self.parameters.items()
            }
            norm = np.sqrt(sum(np.sum(value**2) for value in direction.values()))
            direction = {key: value / norm for key, value in direction.items()}
            epsilon = 1e-6
            plus = {
                key: value + epsilon * direction[key]
                for key, value in self.parameters.items()
            }
            minus = {
                key: value - epsilon * direction[key]
                for key, value in self.parameters.items()
            }
            difference = (
                loss_gradient(plus, self.query, self.raw, "standard", soft=True)[0]
                - loss_gradient(minus, self.query, self.raw, "standard", soft=True)[0]
            ) / (2 * epsilon)
            exact = sum(np.sum(gradient[key] * direction[key]) for key in gradient)
            self.assertAlmostEqual(exact, difference, delta=2e-7)

    def test_support_mixed_reverse_mode_matches_gradient_rule_differences(self):
        _, _, exact, _ = loss_gradient(
            self.parameters, self.support, self.raw, "first_passage", mixed=True
        )
        epsilon = 2e-5
        for channel in range(3):
            direction = np.zeros(3)
            direction[channel] = epsilon
            plus = loss_gradient(
                self.parameters, self.support, self.raw + direction, "first_passage"
            )[1]
            minus = loss_gradient(
                self.parameters, self.support, self.raw - direction, "first_passage"
            )[1]
            for key in exact:
                np.testing.assert_allclose(
                    exact[key][..., channel],
                    (plus[key] - minus[key]) / (2 * epsilon),
                    rtol=2e-5,
                    atol=2e-8,
                )

    def test_bilevel_gradient_matches_complete_resolve_with_and_without_clipping(self):
        for clip in (5.0, 0.01):
            for epsilon in (1e-3, 1e-4):
                checked = check_hypergradient(
                    self.parameters,
                    self.raw,
                    self.support,
                    self.query,
                    epsilon=epsilon,
                    clip=clip,
                )
                self.assertLess(checked["max_scaled_error"], 2e-7)
        projected = copy.deepcopy(self.parameters)
        projected["weights"][0, 0] = 3.2
        checked = check_hypergradient(
            projected, self.raw, self.support, self.query, epsilon=1e-4
        )
        self.assertLess(checked["max_scaled_error"], 2e-7)

    def test_all_three_hypergradients_are_used_without_direct_query_theta(self):
        adapted, hyper, _ = bilevel_step(
            self.parameters, self.raw, self.support, self.query
        )
        self.assertTrue(np.all(np.abs(hyper) > 1e-12))
        first = loss_gradient(adapted, self.query, self.raw, "standard", soft=True)[0]
        second = loss_gradient(
            adapted, self.query, self.raw + 0.1, "standard", soft=True
        )[0]
        self.assertEqual(first, second)

    def test_query_supervision_updates_weights_in_all_training_arms(self):
        for family, learn_theta in (
            ("standard", False),
            ("first_passage", False),
            ("first_passage", True),
        ):
            support_only, hyper, before = bilevel_step(
                self.parameters,
                self.raw,
                self.support,
                self.query,
                family=family,
                learn_theta=learn_theta,
            )
            both, after_hyper, after = bilevel_step(
                self.parameters,
                self.raw,
                self.support,
                self.query,
                family=family,
                learn_theta=learn_theta,
                query_weight_rate=0.01,
            )
            self.assertGreater(
                sum(np.sum((both[key] - support_only[key]) ** 2) for key in both), 0
            )
            np.testing.assert_array_equal(hyper, after_hyper)
            self.assertEqual(
                before["query_fixed_soft_bce"], after["query_fixed_soft_bce"]
            )
            self.assertIsNotNone(after["query_weight_update"])

    def test_checkpoint_export_roundtrip_preserves_actual_inference(self):
        payload = json.loads(
            json.dumps(
                model_payload(self.parameters, self.raw, "first_passage", "a" * 64)
            )
        )
        from_payload = {key: payload[key] for key in ("weights", "readout", "bias")}
        a = step(self.parameters, initial_state(), 1, 0.68, 0.04, 8, 1)
        b = step(
            from_payload,
            initial_state(),
            1,
            0.68,
            0.04,
            8,
            1,
            thresholds=payload["thresholds"],
        )
        self.assertEqual(a, b)
        with self.assertRaises(ValueError):
            model_payload(self.parameters, self.raw, "first_passage", "unbound")

    def test_support_and_query_are_disjoint_and_episode_keyed(self):
        support = make_batch(910001, 3, "support", (0.6, 0.08, 8), 4)
        query = make_batch(910001, 3, "query", (0.6, 0.08, 8), 4)
        larger = make_batch(910001, 3, "support", (0.6, 0.08, 8), 8)
        self.assertNotEqual(support.digest, query.digest)
        np.testing.assert_array_equal(support.observations, larger.observations[:4])
        np.testing.assert_array_equal(support.truth, larger.truth[:4])

    def test_training_changes_weights_and_only_meta_changes_all_three_parameters(self):
        protocol = {
            "datasets": {
                "train_reliability": [0.6, 0.75],
                "train_cost": [0.01, 0.04, 0.08, 0.12],
                "train_deadline": [8, 16],
            },
            "training": {
                "outer_steps": 4,
                "support_episodes": 8,
                "query_episodes": 8,
                "inner_learning_rate": 0.05,
                "outer_learning_rate": 0.2,
                "query_weight_learning_rate": 0.01,
                "gradient_norm_clip": 5.0,
                "hypergradient_norm_clip": 2.0,
            },
        }
        digests = []
        for arm in ("standard", "fixed_theta", "meta_theta"):
            _, _, result = train(910004, arm, protocol)
            self.assertGreater(result["weight_change_l2"], 0)
            changed = np.array(list(result["physical_theta_change"].values()))
            if arm == "meta_theta":
                self.assertTrue(np.all(np.abs(changed) > 1e-10))
            else:
                np.testing.assert_array_equal(changed, 0)
            digests.append(
                [
                    (row["support_dataset_sha256"], row["query_dataset_sha256"])
                    for row in result["history"]
                ]
            )
        self.assertEqual(digests[0], digests[1])
        self.assertEqual(digests[1], digests[2])


if __name__ == "__main__":
    unittest.main()
