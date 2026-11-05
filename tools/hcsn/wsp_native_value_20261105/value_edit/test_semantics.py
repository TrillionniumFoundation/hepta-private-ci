"""Hand-computable semantic checks; no real-fit optimization or held-out worlds."""
import unittest

import numpy as np

from task_graph import anchored_targets, backward_values, forward_occupancy, state_weights


class Semantics(unittest.TestCase):
    def setUp(self):
        self.order = [0, 1, 2, 3, 4]
        self.actions = np.array([2, 1, 4, 5, 5])
        self.edges = [[[(1., 1, .1)], [(.25, 2, .2), (.75, 3, .2)], []],
                      [[(1., 4, .1)], [], []], [[], [], []], [[], [], []], [[], [], []]]
        self.rewards = np.zeros((5, 6))
        self.rewards[2, 4], self.rewards[3, 5], self.rewards[4, 5] = .6, .4, .8

    def test_expected_fees_are_charged_once_per_outcome(self):
        values = backward_values(self.order, self.actions, self.rewards, self.edges)
        self.assertAlmostEqual(values[0], .25)
        self.assertAlmostEqual(values[1], .7)

    def test_occupancy_does_not_visit_incumbent_off_policy_branch(self):
        occupancy, mass = forward_occupancy(self.order, 0, self.actions, self.edges)
        np.testing.assert_array_equal(occupancy, [1., 0., .25, .75, 0.])
        self.assertEqual(mass, 1.)

    def test_uniform_floor_covers_unvisited_continuation(self):
        occupancy, _ = forward_occupancy(self.order, 0, self.actions, self.edges)
        mask = np.array([[True, True, True, False, True, True],
                         [True, True, False, False, True, True],
                         [True, False, False, False, True, True],
                         [True, False, False, False, True, True],
                         [True, False, False, False, True, True]])
        mixed, uniform, _ = state_weights(mask, occupancy, 1, .9)
        np.testing.assert_allclose(mixed[0], [.475, .475, 0.], rtol=0, atol=1e-15)
        self.assertAlmostEqual(mixed[1, 0], .05)
        self.assertAlmostEqual(uniform[1, 0], .5)
        self.assertAlmostEqual(mixed.sum(), 1.)

    def test_anchor_preserves_task_advantage_and_stop_tie(self):
        scores = np.array([[0., .1, .2, .3, -.4, .4], [0., .1, .2, .3, 0., 0.]])
        rewards = np.array([[0., 0., 0., 0., -.2, .2], [0., 0., 0., 0., -.1, .1]])
        q = np.array([[.25, .1, -.1], [.2, -.1, .1]])
        targets, actions, predicted, own = anchored_targets(q, scores, rewards)
        np.testing.assert_array_equal(actions, [5, 0])
        np.testing.assert_allclose(targets - predicted[:, None], q - own[:, None], rtol=0, atol=1e-15)
        self.assertGreater(targets[0, 0], predicted[0])
        self.assertLess(targets[0, 1], predicted[0])


if __name__ == "__main__":
    unittest.main()
