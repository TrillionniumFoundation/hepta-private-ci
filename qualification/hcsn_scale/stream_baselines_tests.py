"""Causality and training fixtures for sensor comparison implementations."""

import unittest

import torch

from .stream_baselines import KINDS, StreamBaseline


class StreamBaselinesTests(unittest.TestCase):
    def test_future_sensor_changes_do_not_change_prefix_or_prefix_gradients(self):
        torch.manual_seed(74113)
        for kind in KINDS:
            with self.subTest(kind=kind):
                model = StreamBaseline(kind, 3, 4, 30.0)
                original = torch.randn(2, 5, 3, dtype=torch.float64, requires_grad=True)
                dt = torch.full((2, 5), 30.0, dtype=torch.float64)
                output = model.encode_batch(original, dt)
                changed = original.detach().clone()
                changed[:, 3:] += 50
                other = model.encode_batch(changed, dt)
                torch.testing.assert_close(
                    output[:, :3], other[:, :3], atol=1e-12, rtol=1e-12
                )
                gradient = torch.autograd.grad(output[:, :3].sum(), original)[0]
                self.assertEqual(float(gradient[:, 3:].abs().max()), 0.0)

    def test_all_models_train_and_use_physical_durations(self):
        torch.manual_seed(74117)
        for kind in KINDS:
            with self.subTest(kind=kind):
                model = StreamBaseline(kind, 3, 4, 30.0)
                x = torch.randn(3, 4, 3, dtype=torch.float64)
                dt = torch.full((3, 4), 30.0, dtype=torch.float64)
                first = model.encode_batch(x, dt)
                second = model.encode_batch(x, dt * 2)
                self.assertGreater(float((first - second).abs().max().detach()), 1e-10)
                loss = model.next_sensor_loss(x, dt)
                loss.backward()
                for name, parameter in model.named_parameters():
                    self.assertIsNotNone(parameter.grad, name)
                    self.assertTrue(bool(torch.isfinite(parameter.grad).all()), name)
                features, value = model.representations(x, dt)
                self.assertEqual(features.shape, (3, 8))
                self.assertGreaterEqual(value, 0.0)


if __name__ == "__main__":
    unittest.main()
