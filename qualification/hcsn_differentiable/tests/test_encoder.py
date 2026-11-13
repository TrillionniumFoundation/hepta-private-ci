"""Clock, missingness and chunk-continuation tests for the sensor adapter."""

import unittest

import torch

from qualification.hcsn_differentiable.encoder import IrregularSensorEncoder


class EncoderTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(1701)
        self.encoder = IrregularSensorEncoder(2, 4).double()

    def test_per_example_time_missingness_and_padding_are_distinct(self):
        values = torch.tensor(
            [[[1., float("nan")], [float("nan"), float("nan")], [2., 3.]],
             [[4., 5.], [float("nan"), float("nan")], [6., 7.]]], dtype=torch.float64)
        observed = torch.tensor(
            [[[True, False], [False, False], [True, True]],
             [[True, True], [False, False], [True, True]]])
        valid = torch.tensor([[True, True, True], [True, False, True]])
        timestamps = torch.tensor([[.1, .4, .9], [.2, float("nan"), .7]], dtype=torch.float64)
        result = self.encoder(values, timestamps, observed, valid)
        torch.testing.assert_close(result.dt, torch.tensor([[.1, .3, .5], [.2, 0., .5]], dtype=torch.float64))
        self.assertTrue(bool(torch.isfinite(result.features).all()))
        self.assertFalse(bool(result.observed[:, 1].any()))
        self.assertTrue(bool((result.features[:, 1] == 0).all()))
        torch.testing.assert_close(result.last_timestamp, torch.tensor([.9, .7], dtype=torch.float64))

    def test_chunk_continuation_uses_exact_previous_clock(self):
        values = torch.arange(16, dtype=torch.float64).reshape(2, 4, 2) / 10
        timestamps = torch.tensor([[.1, .3, .7, 1.], [.2, .5, .55, 1.2]], dtype=torch.float64)
        whole = self.encoder(values, timestamps)
        first = self.encoder(values[:, :2], timestamps[:, :2])
        last = self.encoder(values[:, 2:], timestamps[:, 2:], start_time=first.last_timestamp)
        torch.testing.assert_close(torch.cat((first.dt, last.dt), 1), whole.dt, rtol=0, atol=0)
        torch.testing.assert_close(torch.cat((first.features, last.features), 1), whole.features)
        torch.testing.assert_close(last.last_timestamp, whole.last_timestamp, rtol=0, atol=0)

    def test_missing_channels_have_zero_input_gradient(self):
        values = torch.tensor([[[.7, 12345.], [.1, .2]]], dtype=torch.float64, requires_grad=True)
        mask = torch.tensor([[[True, False], [True, True]]])
        result = self.encoder(values, torch.tensor([[.1, .4]], dtype=torch.float64), mask)
        result.features.square().sum().backward()
        self.assertEqual(float(values.grad[0, 0, 1]), 0.)
        self.assertGreater(float(values.grad[mask].abs().sum()), 0.)

    def test_invalid_observed_values_and_backward_time_reject(self):
        with self.assertRaisesRegex(ValueError, "observed sensor"):
            self.encoder(torch.tensor([[[float("nan"), 0.]]], dtype=torch.float64),
                         torch.tensor([[.1]], dtype=torch.float64))
        with self.assertRaisesRegex(ValueError, "nondecreasing"):
            self.encoder(torch.zeros(1, 2, 2, dtype=torch.float64),
                         torch.tensor([[.2, .1]], dtype=torch.float64))

    def test_fp64_absolute_times_differenced_before_model_cast(self):
        encoder = IrregularSensorEncoder(2, 4).float()
        timestamp = torch.tensor([[1_000_000_000.125, 1_000_000_000.5]], dtype=torch.float64)
        result = encoder(torch.zeros(1, 2, 2), timestamp, start_time=1_000_000_000.)
        torch.testing.assert_close(result.dt, torch.tensor([[.125, .375]]), rtol=0, atol=0)
        self.assertEqual(result.last_timestamp.dtype, torch.float64)

    def test_continuation_never_rounds_a_retained_fp64_clock_down_to_fp32(self):
        values = torch.zeros(1, 1, 2, dtype=torch.float64)
        rounded_back = torch.tensor([[2.**24]], dtype=torch.float32)
        retained = torch.tensor([2.**24 + .5], dtype=torch.float64)
        for predecessor in (retained, float(retained[0])):
            with self.subTest(predecessor_type=type(predecessor).__name__):
                with self.assertRaisesRegex(ValueError, "nondecreasing"):
                    self.encoder(values, rounded_back, start_time=predecessor)
        ahead = torch.tensor([[2.**24 + 2.]], dtype=torch.float32)
        result = self.encoder(values, ahead, start_time=retained)
        torch.testing.assert_close(result.dt, torch.tensor([[1.5]], dtype=torch.float64), rtol=0, atol=0)
        self.assertEqual(result.last_timestamp.dtype, torch.float64)


if __name__ == "__main__":
    unittest.main()
