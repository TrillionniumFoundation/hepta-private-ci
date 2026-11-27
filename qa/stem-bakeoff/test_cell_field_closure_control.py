"""Synthetic mechanism checks only; never counted as new task evidence."""

from types import SimpleNamespace
import unittest

import numpy as np

from cell_field_action_control import build_action_model
from cell_field_closure_control import closure_maps, fixed_actions, history_maps


def fixture(horizon=8):
    rng = np.random.default_rng(501)
    parameters, dimension = 36, 108
    A = np.array([0.94 * np.eye(dimension) + rng.normal(0, 0.015, (dimension, dimension))
                  for _ in range(8)])[:horizon]
    C = rng.normal(size=(9, 4, dimension))[:horizon + 1]
    E = np.tile(np.vstack((0.02 * np.eye(parameters), np.zeros((72, 36)))), (horizon, 1, 1))
    return SimpleNamespace(A=A, C=C, states=np.zeros((horizon + 1, dimension)),
                           observations=np.zeros((horizon + 1, 4)), horizon=horizon,
                           state=SimpleNamespace(parameter_count=parameters),
                           action_matrix=lambda mask: (np.eye(parameters), E.copy()))


class ClosureTests(unittest.TestCase):
    def test_one_history_step_matches_original_memoryless_model(self):
        ref = fixture()
        actual, _ = history_maps(ref, 1)
        expected = build_action_model(ref, observation="loss2")["loss_maps"]
        np.testing.assert_allclose(actual, expected, rtol=2e-13, atol=2e-15)

    def test_retaining_entire_input_window_recovers_full_tangent(self):
        ref = fixture()
        actual, _ = history_maps(ref, 8)
        expected = build_action_model(ref, observation="full")["loss_maps"]
        np.testing.assert_allclose(actual, expected, rtol=2e-13, atol=2e-15)

    def test_prediction_prefix_does_not_read_future_reference(self):
        short, long = fixture(4), fixture(8)
        for arm in ("loss2", "history2", "history4", "moment4", "full"):
            left, _ = closure_maps(short, arm)
            right, _ = closure_maps(long, arm)
            np.testing.assert_array_equal(left, right[:5])

    def test_history_is_exact_until_its_known_impulse_leaves_the_window(self):
        ref = fixture()
        full = build_action_model(ref, observation="full")["loss_maps"]
        for lag in (2, 4):
            actual, _ = history_maps(ref, lag)
            np.testing.assert_allclose(actual[:lag + 1], full[:lag + 1], atol=2e-15, rtol=2e-13)
            self.assertGreater(np.linalg.norm(actual[lag + 1] - full[lag + 1]), 1e-6)

    def test_all_arms_agree_at_first_impulse_and_preserve_reference(self):
        ref = fixture()
        originals = [x.copy() for x in (ref.A, ref.C, ref.states)]
        expected = (ref.C[1, :2] @ ref.action_matrix("all")[1][0])
        for arm in ("loss2", "history2", "history4", "moment4", "full"):
            maps, _ = closure_maps(ref, arm)
            np.testing.assert_allclose(maps[1], expected, rtol=2e-13, atol=2e-15)
        for previous, current in zip(originals, (ref.A, ref.C, ref.states)):
            np.testing.assert_array_equal(previous, current)

    def test_directions_are_antipodal_equal_effort_and_within_box(self):
        for p in (36, 52):
            actions = fixed_actions(p)
            np.testing.assert_array_equal(actions[1::2], -actions[2::2])
            np.testing.assert_allclose(np.linalg.norm(actions[1:], axis=1), 0.1)
            self.assertLessEqual(float(np.max(np.abs(actions))), 1 / np.sqrt(p))
            np.testing.assert_array_equal(actions, fixed_actions(p))


if __name__ == "__main__":
    unittest.main()
