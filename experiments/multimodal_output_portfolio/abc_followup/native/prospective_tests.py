"""Ensure the supplemental adapter never treats copied observations as forecasts."""

import unittest

import numpy as np

from .forecast_tests import ForecastBoundaries
from .forecast import Q, public_input
from .prospective import predictions
from ...abc_recovery.runtime import public_frame


class ProspectiveBoundaries(ForecastBoundaries):
    def test_observation_copy_cannot_change_future_probability_or_forecast(self):
        x = public_input(self.generator, public_frame(self.run), self.observation, "couple") / Q
        calibration = {"cuts": [.2, .8], "probabilities": [.8] * 8}
        left = predictions(self.weights, calibration, x, np.zeros((2, 32)))
        right = predictions(self.weights, calibration, x, np.ones((2, 32)))
        for index in (0, 1, 4, 5):
            np.testing.assert_array_equal(left[index], right[index])
        self.assertFalse(np.array_equal(left[2][:, 1:], right[2][:, 1:]))
        np.testing.assert_array_equal(left[2][:, 1:], left[3][:, 1:])
        np.testing.assert_array_equal(right[2][:, 1:], right[3][:, 1:])


if __name__ == "__main__":
    unittest.main()
