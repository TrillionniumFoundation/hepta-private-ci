import unittest

import numpy as np

from control import Controller, fit_controller


class ControllerTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(73)
        self.p = rng.dirichlet(np.ones(3), size=120)
        self.q = rng.dirichlet(np.ones(3), size=120)
        self.delta = 0.4 - 0.8 * self.p[:, 0] + 0.2 * self.q[:, 1]
        self.controller = fit_controller(self.p, self.q, self.delta, 1e-5)

    def test_training_only_continuation_fit_generalizes(self):
        p = np.array([[0.05, 0.45, 0.50], [0.9, 0.05, 0.05]])
        q = np.array([[0.3, 0.4, 0.3], [0.3, 0.4, 0.3]])
        predicted = self.controller.predict_gain(p, q)
        np.testing.assert_allclose(predicted, 0.4 - 0.8 * p[:, 0] + 0.2 * q[:, 1], atol=0.002)
        np.testing.assert_array_equal(self.controller.decide(p, q, 1), [True, False])

    def test_budget_and_price_control_continuation(self):
        action = self.controller.decide(self.p, self.q, 1)
        self.assertTrue(action.any())
        np.testing.assert_array_equal(self.controller.decide(self.p, self.q, 0), False)
        np.testing.assert_array_equal(self.controller.decide(self.p, self.q, 1, price=2), False)
        with self.assertRaises(ValueError):
            self.controller.decide(self.p, self.q, 2)

    def test_deployment_action_has_no_outcome_input(self):
        # Changing external labels does not change the first-pass distributions.
        labels = np.arange(len(self.p)) % 3
        before = self.controller.decide(self.p, self.q, 1)
        labels[:] = (labels + 1) % 3
        np.testing.assert_array_equal(self.controller.decide(self.p, self.q, 1), before)
        with self.assertRaises(TypeError):
            self.controller.decide(self.p, self.q, 1, targets=labels)

    def test_safe_artifact_roundtrip_preserves_decisions(self):
        restored = Controller.from_arrays(self.controller.to_arrays())
        np.testing.assert_array_equal(restored.decide(self.p, self.q, 1),
                                      self.controller.decide(self.p, self.q, 1))
        broken = dict(self.controller.to_arrays(), extra=np.ones(1))
        with self.assertRaises(ValueError):
            Controller.from_arrays(broken)

    def test_invalid_probability_or_target_rejects(self):
        invalid = self.p.copy()
        invalid[0, 0] = np.nan
        with self.assertRaises(ValueError):
            self.controller.decide(invalid, self.q, 1)
        with self.assertRaises(ValueError):
            fit_controller(self.p, self.q, np.full(len(self.p), np.inf))


if __name__ == "__main__":
    unittest.main()
