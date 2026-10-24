import unittest
import numpy as np
from temporal_diagnostics import temporal_diagnostics


class TemporalTests(unittest.TestCase):
    def setUp(self):
        self.x = np.array([0., .1, .6, 1.]).reshape(4, 1, 1, 1)
        self.times = [0., 1., 2., 3.]

    def test_identity(self):
        result = temporal_diagnostics(self.x, self.x, self.times, self.times)
        self.assertEqual(result['ordered_delta_mae'], 0.)
        self.assertIsNone(result['acceptance_threshold'])

    def test_reverse_keeps_magnitude_not_order(self):
        result = temporal_diagnostics(self.x, self.x[::-1], self.times, self.times)
        self.assertEqual(result['reference_temporal_magnitude'], result['reconstruction_temporal_magnitude'])
        self.assertGreater(result['ordered_delta_mae'], 0.)

    def test_freeze_has_zero_motion_not_zero_residual(self):
        result = temporal_diagnostics(self.x, np.repeat(self.x[:1], 4, axis=0), self.times, self.times)
        self.assertEqual(result['reconstruction_temporal_magnitude'], 0.)
        self.assertGreater(result['ordered_delta_mae'], 0.)

    def test_timestamp_mismatch_or_disorder_rejected(self):
        for times in ([0., 1., 2., 4.], [0., 2., 1., 3.], [0., 1., 1., 3.], [0., 1., 2., float('nan')]):
            with self.assertRaises(ValueError):
                temporal_diagnostics(self.x, self.x, self.times, times)

    def test_shape_and_nonfinite_rejected(self):
        for y in (self.x[:1], self.x * float('nan'), self.x.astype('int64')):
            with self.assertRaises(ValueError):
                temporal_diagnostics(self.x, y, self.times, self.times)

    def test_extreme_finite_difference_overflow_rejected(self):
        x = np.array([-1e308, 1e308]).reshape(2, 1, 1, 1)
        with self.assertRaises(ValueError):
            temporal_diagnostics(x, x, [0, 1], [0, 1])

    def test_finite_difference_but_reduction_overflow_rejected(self):
        x = np.zeros((3, 1, 1, 2))
        y = np.full_like(x, 1e308)
        with self.assertRaises(ValueError):
            temporal_diagnostics(x, y, [0, 1, 2], [0, 1, 2])

    def test_finite_timestamp_interval_overflow_rejected(self):
        times = [-1e308, 1e308]
        with self.assertRaises(ValueError):
            temporal_diagnostics(self.x[:2], self.x[:2], times, times)


if __name__ == '__main__':
    unittest.main()
