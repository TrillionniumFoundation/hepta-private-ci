"""Phase and future-innovation tests; these do not generate study audit fixtures."""

import unittest

import numpy as np
import torch

from .audits import COMPUTE_PRICE, FUTURE_POLICY_OFFSET, conditional_returns, future_policy
from .model import JointCell
from .policy import Policy, keyed_uniform
from .task import conditional_episode, generate_episode, initial_state, step


class AuditTests(unittest.TestCase):
    def test_future_rng_is_replaced_while_conditioned_mass_and_clock_are_preserved(self):
        model = JointCell("clocked", n_grid=5, hidden=4)
        episode = generate_episode(12)
        state = initial_state(episode)
        policy = Policy(model, head=1, deployment="hard", seed=12)
        policy.act(state)
        snapshot = policy.snapshot()
        one = future_policy(model, snapshot, 8001)
        two = future_policy(model, snapshot, 8002)
        self.assertEqual(one.calls, policy.calls)
        self.assertEqual(two.calls, policy.calls)
        self.assertTrue(torch.equal(one.mass, policy.mass))
        self.assertTrue(torch.equal(two.mass, policy.mass))
        self.assertNotEqual(keyed_uniform(one.seed, one.calls, "latent"),
                            keyed_uniform(two.seed, two.calls, "latent"))
        self.assertEqual(snapshot["seed"], 12)

    def test_STOP_conditional_value_charges_compute_but_not_sunk_current_event(self):
        model = JointCell("clocked", n_grid=5, hidden=4)
        episode = generate_episode(13)
        state = initial_state(episode)
        policy = Policy(model, head=1, deployment="hard", seed=13)
        policy.act(state)
        snapshot = policy.snapshot()
        # The phase is after a current transition; the sampled event may already
        # have occurred. No current event value is accepted by the audit API.
        values, future_seeds = conditional_returns(model, state, episode, snapshot,
                                                   base_seed=1000, count=8)
        expected = []
        for index in range(8):
            fixture = conditional_episode(state, 1000 + index, episode)
            expected.append(step(state, "STOP", fixture).reward - COMPUTE_PRICE)
        np.testing.assert_array_equal(values["STOP"], expected)
        self.assertEqual(future_seeds, [FUTURE_POLICY_OFFSET + 1000 + i for i in range(8)])
        self.assertEqual(len(set(future_seeds)), 8)


if __name__ == "__main__":
    unittest.main()
