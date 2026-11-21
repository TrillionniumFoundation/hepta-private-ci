"""Paired execution and gradients against the unchanged serial implementation."""

import unittest

import torch

from qualification.hcsn_scale.model import ModelConfig, SequenceModel
from .model import PreparedSequenceModel


class PreparedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.old_threads)

    def fixture(self, kind="hcsn", dtype="float64", batch=3, steps=7):
        generator = torch.Generator().manual_seed(7733)
        x = torch.randn(batch, steps, 3, generator=generator, dtype=getattr(torch, dtype))
        # Every sample has a distinct clock. Boundaries repeatedly move both ways.
        dt = torch.randint(10_000, 900_000, (batch, steps), generator=generator).double() / 1_000_000
        config = ModelConfig(kind, 3, 4, 2.0, bins=4, stages=3, dtype=dtype)
        torch.manual_seed(9973)
        serial, prepared = SequenceModel(config), PreparedSequenceModel(config)
        prepared.load_state_dict(serial.state_dict())
        return serial, prepared, x, dt

    def test_all_features_equal_for_independent_clocks_and_moving_boundaries(self):
        for kind in ("hcsn", "gru"):
            with self.subTest(kind=kind):
                serial, prepared, x, dt = self.fixture(kind)
                expected = torch.stack([serial.encode_one(a, b) for a, b in zip(x, dt)])
                actual = prepared.encode_batch(x, dt)
                torch.testing.assert_close(actual, expected, rtol=1e-10, atol=1e-11)
                prefix = prepared.encode_batch(x[:, :3], dt[:, :3])
                torch.testing.assert_close(prefix, actual[:, :3], rtol=1e-10, atol=1e-11)
                for index in range(len(x)):
                    single = prepared.encode_one(x[index], dt[index])
                    torch.testing.assert_close(single, actual[index], rtol=1e-10, atol=1e-11)
                changed = dt.clone()
                changed[1] *= 2
                other = prepared.encode_batch(x, changed)
                torch.testing.assert_close(other[[0, 2]], actual[[0, 2]], rtol=1e-10, atol=1e-11)
                self.assertGreater(float((other[1] - actual[1]).detach().abs().max()), 1e-8)

    def test_full_parameter_and_input_gradients_and_adam_update_match(self):
        for kind in ("hcsn", "gru"):
            with self.subTest(kind=kind):
                serial, prepared, x, dt = self.fixture(kind)
                a, b = x.clone().requires_grad_(), x.clone().requires_grad_()
                reference = serial.next_sensor_loss(a, dt)
                candidate = prepared.next_sensor_loss(b, dt)
                reference.backward()
                candidate.backward()
                torch.testing.assert_close(candidate, reference, rtol=1e-10, atol=1e-11)
                torch.testing.assert_close(b.grad, a.grad, rtol=1e-9, atol=1e-10)
                for (name, before), (other, after) in zip(serial.named_parameters(), prepared.named_parameters()):
                    self.assertEqual(name, other)
                    self.assertIsNotNone(before.grad)
                    torch.testing.assert_close(after.grad, before.grad, rtol=1e-9, atol=1e-10)
                torch.optim.Adam(serial.parameters(), lr=.003).step()
                torch.optim.Adam(prepared.parameters(), lr=.003).step()
                for name, value in serial.state_dict().items():
                    torch.testing.assert_close(prepared.state_dict()[name], value, rtol=1e-9, atol=1e-10)

    def test_mixed_precision_preserves_fp64_transport_and_reference_features(self):
        serial, prepared, x, dt = self.fixture(dtype="float32")
        operators = prepared.prepare_windows(x, dt)
        self.assertEqual(operators.actions.dtype, torch.float64)
        expected = torch.stack([serial.encode_one(a, b) for a, b in zip(x, dt)])
        actual = prepared.propagate_prepared(operators)
        self.assertEqual(actual.dtype, torch.float32)
        torch.testing.assert_close(actual, expected, rtol=3e-5, atol=3e-6)

    def test_chunked_representation_preserves_all_windows_and_loss(self):
        serial, prepared, x, dt = self.fixture(batch=35, steps=3)
        expected, before = serial.representations(x, dt)
        actual, after = prepared.representations(x, dt)
        torch.testing.assert_close(actual, expected, rtol=1e-10, atol=1e-11)
        self.assertAlmostEqual(after, before, places=10)

    def test_invalid_time_and_capacity_are_rejected_before_transport(self):
        _, prepared, x, dt = self.fixture()
        for bad in (dt[:, :-1], torch.zeros_like(dt), dt + .0000001):
            with self.assertRaises(ValueError):
                prepared.encode_batch(x, bad)
        with self.assertRaises(ValueError):
            prepared.encode_batch(x[:, :1].expand(3, 257, 3), torch.ones(3, 257))


if __name__ == "__main__":
    unittest.main()
