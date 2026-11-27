"""Hand-array algebra checks; no TRAIN input, model forward or fitting."""

import unittest

import numpy as np

from independent.learning import CONTENT_PARAMETERS
from ndu_training.mechanism_readout.anchor_cv import correct


class AnchorControlVariateTests(unittest.TestCase):
    def maps(self, vector):
        return {key: np.asarray(vector, dtype=np.float64).copy() for key in CONTENT_PARAMETERS}

    def test_weighted_enumeration_preserves_full_objective_mean(self):
        rng = np.random.default_rng(7021)
        probability = np.array([.1, .3, .6])
        ref, current, utility = (rng.normal(size=(3, 4)) for _ in range(3))
        mean_ref = probability @ ref
        expected = probability @ (.2*current+utility)
        actual = sum(probability[i]*correct(self.maps(.2*current[i]+utility[i]),
            self.maps(mean_ref), self.maps(ref[i]))["encoder"] for i in range(3))
        np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-15)

    def test_at_reference_anchor_noise_is_removed_without_changing_mean(self):
        values = [np.array([-2., 1.]), np.array([1., -1.]), np.array([4., 3.])]
        mean = np.mean(values, axis=0)
        outputs = [correct(self.maps(.2*x), self.maps(mean), self.maps(x))["text"] for x in values]
        for output in outputs:
            np.testing.assert_allclose(output, .2*mean, rtol=0, atol=1e-15)

    def test_total_variance_can_increase_when_utility_cancels_anchor(self):
        # This counterexample prevents claiming guaranteed total variance gain.
        ref = [np.array([-1., 2.]), np.array([1., -2.])]
        outputs = [correct(self.maps(np.zeros(2)), self.maps(np.zeros(2)), self.maps(x))["image"] for x in ref]
        self.assertGreater(float(np.var(outputs, axis=0).sum()), 0)

    def test_late_invalid_group_never_mutates_input_gradients(self):
        gradient, mean, batch = (self.maps([1., 2.]) for _ in range(3))
        before = {key: value.copy() for key, value in gradient.items()}
        batch["image_bias"] = np.array([np.nan, 0.])
        with self.assertRaises(ValueError):
            correct(gradient, mean, batch)
        for key in CONTENT_PARAMETERS:
            np.testing.assert_array_equal(gradient[key], before[key])


if __name__ == "__main__":
    unittest.main()
