"""Causal content feedback, equal-capacity switches and physical pooling checks."""

from dataclasses import replace
import unittest

import torch

from .feedback import pool_features
from .model import ModelConfig, SequenceModel


class FeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.threads)

    def pair(self, mode="all"):
        config = ModelConfig(
            "hcsn",
            2,
            3,
            1.0,
            write_law="continuous_write",
            write_rate=0.7,
            feedback_mode=mode,
            pooling="exposure",
        )
        torch.manual_seed(23)
        enabled = SequenceModel(config)
        torch.manual_seed(23)
        disabled = SequenceModel(replace(config, feedback_mode="none"))
        for model in (enabled, disabled):
            with torch.no_grad():
                model.encoder.writer.weight.fill_(0.1)
                model.encoder.writer.bias.fill_(0.5)
                model.feedback.projection.weight.fill_(0.6)
        return enabled, disabled

    def test_content_changes_later_dynamics_and_has_real_gradients(self):
        enabled, disabled = self.pair()
        sequence = torch.tensor(
            [[0.2, 0.1], [0.3, -0.2], [0.4, 0.1]], dtype=torch.float64
        )
        intervals = [0.1, 0.2, 0.1]
        actual = enabled.encode_one(sequence, intervals)
        control = disabled.encode_one(sequence, intervals)
        torch.testing.assert_close(actual[0], control[0], atol=0, rtol=0)
        self.assertGreater(float((actual[1:] - control[1:]).detach().abs().max()), 1e-8)
        actual[-1].square().sum().backward()
        gradient = enabled.feedback.projection.weight.grad
        self.assertTrue(bool(torch.isfinite(gradient).all()))
        self.assertTrue(bool((gradient.abs().sum(-1) > 1e-10).all()))
        self.assertGreater(float(enabled.encoder.writer.weight.grad.norm()), 1e-10)

    def test_off_switch_keeps_initial_parameters_width_and_state_bytes(self):
        enabled, disabled = self.pair()
        disabled.load_state_dict(enabled.state_dict())
        self.assertEqual(disabled.feedback.routes.tolist(), [0.0, 0.0, 0.0])
        self.assertEqual(
            enabled.identity()["all_trainable_parameters"],
            disabled.identity()["all_trainable_parameters"],
        )
        self.assertEqual(
            enabled.identity()["streaming_state_bytes_per_sample"],
            disabled.identity()["streaming_state_bytes_per_sample"],
        )
        for a, b in zip(enabled.parameters(), disabled.parameters(), strict=True):
            torch.testing.assert_close(a, b, atol=0, rtol=0)

    def test_grouped_physical_clocks_preserve_independent_outputs_and_gradients(self):
        model, _ = self.pair()
        windows = torch.tensor(
            [
                [[0.2, 0.1], [0.3, -0.2]],
                [[0.1, -0.3], [0.4, 0.2]],
                [[-0.1, 0.3], [0.2, 0.4]],
            ],
            dtype=torch.float64,
        )
        intervals = torch.tensor(
            [[0.1, 0.2], [0.2, 0.1], [0.1, 0.2]], dtype=torch.float64
        )
        batched = model.encode_batch(windows, intervals)
        separate = torch.stack(
            [model.encode_one(x, dt) for x, dt in zip(windows, intervals)]
        )
        torch.testing.assert_close(batched, separate, atol=2e-12, rtol=2e-12)
        parameters = tuple(model.parameters())[:-2]
        grouped_grad = torch.autograd.grad(batched.square().sum(), parameters)
        scalar_grad = torch.autograd.grad(separate.square().sum(), parameters)
        for actual, expected in zip(grouped_grad, scalar_grad):
            torch.testing.assert_close(actual, expected, atol=2e-11, rtol=2e-10)

    def test_reward_feedback_changes_value_without_changing_population_dynamics(self):
        enabled, disabled = self.pair("reward")
        sequence = torch.tensor(
            [[0.2, 0.1], [0.3, -0.2], [0.4, 0.1]], dtype=torch.float64
        )
        a, b = (
            model.encode_one(sequence, [0.1, 0.2, 0.1]) for model in (enabled, disabled)
        )
        torch.testing.assert_close(a[:, :-1], b[:, :-1], atol=0, rtol=0)
        self.assertGreater(float((a[1:, -1] - b[1:, -1]).detach().abs().max()), 1e-8)

    def test_feature_ablations_preserve_parameter_count_and_width(self):
        reference, _ = self.pair()
        sequence = torch.tensor([[0.2, 0.1], [0.3, -0.2]], dtype=torch.float64)
        for bank in ("drop_value_risk", "ordinary_tanh"):
            model = SequenceModel(replace(reference.config, feature_bank=bank))
            model.load_state_dict(reference.state_dict())
            values = model.encode_one(sequence, [0.1, 0.2])
            self.assertEqual(values.shape, (2, reference.feature_width))
            self.assertEqual(
                model.identity()["all_trainable_parameters"],
                reference.identity()["all_trainable_parameters"],
            )
            if bank == "drop_value_risk":
                self.assertEqual(
                    values[
                        :,
                        [
                            model.encoder.feature_names.index(n)
                            for n in ("risk", "call")
                        ],
                    ].tolist(),
                    [[0.0, 0.0], [0.0, 0.0]],
                )

    def test_exposure_pool_uses_duration_and_increment_units(self):
        values = torch.tensor([[2.0, -1.0, 0.1], [3.0, 6.0, 0.9]], dtype=torch.float64)
        actual = pool_features(
            values, [1.0, 3.0], ("event", "content_0", "margin"), "exposure"
        )
        expected = torch.tensor([1.0, 2.0, 0.9, 1.25, 1.25, 0.7], dtype=torch.float64)
        torch.testing.assert_close(actual, expected, atol=1e-15, rtol=0)
        split = torch.tensor(
            [[2.0, -1.0, 0.1], [1.0, 2.0, 0.9], [1.0, 2.0, 0.9], [1.0, 2.0, 0.9]],
            dtype=torch.float64,
        )
        refined = pool_features(
            split, [1.0, 1.0, 1.0, 1.0], ("event", "content_0", "margin"), "exposure"
        )
        torch.testing.assert_close(refined, actual, atol=1e-15, rtol=0)


if __name__ == "__main__":
    unittest.main()
