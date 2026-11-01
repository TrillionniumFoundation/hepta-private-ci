"""Discriminating numerical checks of event and post-event state propagation."""

import unittest

import numpy as np

from .propagation_audit import marked_uniformization, run_audit


class PropagationAuditTests(unittest.TestCase):
    def test_four_user_requirements_against_independent_references(self):
        result = run_audit()
        self.assertTrue(all(result["checks"].values()), result)

    def test_uniformization_on_an_independent_repeated_event_chain(self):
        # A two-state symmetric alternating chain has event count rate*t;
        # first-hit probability is 1-exp(-rate*t), not that event count.
        rate, duration = 2.3, 3.1
        generator = np.array([[-rate, rate], [rate, -rate]])
        events = np.array([[0., rate], [rate, 0.]])
        result = marked_uniformization(generator, events, np.array([1., 0.]), duration)
        np.testing.assert_allclose(result["count"], rate * duration, atol=1e-11)
        np.testing.assert_allclose(result["first"], -np.expm1(-rate * duration), atol=1e-12)
        expected = np.array([1 + np.exp(-2 * rate * duration), 1 - np.exp(-2 * rate * duration)]) / 2
        np.testing.assert_allclose(result["state"], expected, atol=1e-12)


if __name__ == "__main__":
    unittest.main()
