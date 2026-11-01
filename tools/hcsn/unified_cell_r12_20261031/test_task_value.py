"""Independent unnormalized policy-tree checks of the finite task controller."""
import unittest

import numpy as np
from scipy.linalg import expm

from .task_value import ExactBeliefDP


class TinyCell:
    """Two active content states and two recovering content states."""
    def __init__(self):
        self.Q = np.array([[-.6, 0, .6, 0], [0, -.2, 0, .2],
                           [.64, .16, -.8, 0], [.16, .64, 0, -.8]])
        self.E = np.array([[.8, .2, 0], [.15, .85, 0], [0, 0, 1], [0, 0, 1]])
        self.R = np.array([[0, 0, 1, 0], [0, 0, 0, 1],
                           [0, 0, 1, 0], [0, 0, 0, 1]])
        self.reward = np.array([[1.03, .03], [.03, 1.03], [1., 0.], [0., 1.]])
        self.read_cost = np.array([.04, .05, .08, .09])
        self.prior = np.array([.35, .35, .15, .15])


def enumerate_tree(cell, mass, schedule, budget, reset_cost=.04, latency_price=.01,
                   read_multiplier=1., policy="optimal"):
    """Unnormalized path masses: no Bayes division or controller methods.

    Each observation branch carries its full joint probability to the leaves.
    The maximum is outside the latent-state expectation, so this enumeration
    cannot choose an action separately for hidden states.
    """
    q = {f"STOP{answer}": float(mass @ cell.reward[:, answer]) for answer in (0, 1)}
    if not schedule:
        return q
    dt, rest = schedule[0], schedule[1:]
    matrix = expm(cell.Q*dt)
    total_mass = float(mass.sum())
    successor = mass @ matrix

    def leaf(weight, remaining_budget):
        values = enumerate_tree(cell, weight, rest, remaining_budget, reset_cost,
                                latency_price, read_multiplier, policy)
        if policy == "wait" and rest:
            return values["WAIT"]
        if policy == "wait":
            return max(values["STOP0"], values["STOP1"])
        return max(values.values())

    q["WAIT"] = leaf(successor, budget)-total_mass*latency_price*dt
    if budget:
        q["READ"] = (-total_mass*latency_price*dt-read_multiplier*float(successor @ cell.read_cost)
                     +sum(leaf(successor*cell.E[:, o], budget-1) for o in range(cell.E.shape[1])))
    q["RESET"] = leaf(mass @ cell.R @ matrix, budget)-total_mass*(reset_cost+latency_price*dt)
    return q


class TaskValueTests(unittest.TestCase):
    def setUp(self):
        self.cell = TinyCell()
        self.dp = ExactBeliefDP(self.cell)

    def test_exact_observation_policy_tree(self):
        for schedule, budget in [((.21,), 1), ((.13, .67), 2), ((.3, .1), 0)]:
            expected = enumerate_tree(self.cell, self.cell.prior, schedule, budget)
            actual = self.dp.action_values(self.cell.prior, schedule, budget)
            self.assertEqual(actual.keys(), expected.keys())
            np.testing.assert_allclose(list(actual.values()), list(expected.values()), rtol=0, atol=3e-13)

    def test_terminal_and_budget_contract(self):
        terminal = self.dp.channels(self.cell.prior, (), 2)
        self.assertEqual(set(terminal["q"]), {"STOP0", "STOP1"})
        self.assertIsNone(terminal["A"])
        self.assertIsNone(terminal["B"])
        self.assertIsNone(terminal["advantage"])
        self.assertNotIn("READ", self.dp.action_values(self.cell.prior, (.1,), 0))

    def test_reset_uses_remaining_time_and_content(self):
        belief = np.array([.1, .9, 0, 0])
        dt = 1.3
        exact_state = belief @ self.cell.R @ expm(self.cell.Q*dt)
        end_reset_state = belief @ expm(self.cell.Q*dt) @ self.cell.R
        q = self.dp.action_values(belief, (dt,), 0)["RESET"]
        expected = max(exact_state @ self.cell.reward)-.04-.01*dt
        wrong_order = max(end_reset_state @ self.cell.reward)-.04-.01*dt
        self.assertAlmostEqual(q, expected, places=13)
        self.assertGreater(np.linalg.norm(exact_state-end_reset_state, ord=1), .1)
        self.assertGreater(abs(expected-wrong_order), .001)
        self.assertGreater(exact_state[:2].sum(), 0.)

    def test_read_is_at_end_and_charges_end_state(self):
        belief = np.array([.5, .5, 0, 0])
        dt = .8
        end = belief @ expm(self.cell.Q*dt)
        reward = sum(max((end*self.cell.E[:, o]) @ self.cell.reward) for o in range(3))
        expected = reward-end @ self.cell.read_cost-.01*dt
        actual = self.dp.action_values(belief, (dt,), 1)["READ"]
        self.assertAlmostEqual(actual, expected, places=13)
        before_observation = sum(max((belief*self.cell.E[:, o]) @ expm(self.cell.Q*dt)
                                     @ self.cell.reward) for o in range(3))
        self.assertGreater(abs(reward-before_observation), .001)

    def test_q_pi_uses_actual_tail_instead_of_oracle(self):
        def wait_policy(belief, schedule, budget):
            return "WAIT" if schedule else f"STOP{int((belief @ self.cell.reward).argmax())}"

        schedule = (.2, .4)
        actual = self.dp.paired_q_pi(self.cell.prior, schedule, 2, wait_policy)
        expected = enumerate_tree(self.cell, self.cell.prior, schedule, 2, policy="wait")
        np.testing.assert_allclose(list(actual.values()), list(expected.values()), rtol=0, atol=3e-13)
        optimal = self.dp.action_values(self.cell.prior, schedule, 2)
        self.assertTrue(all(actual[key] <= optimal[key]+1e-12 for key in actual))
        self.assertGreater(optimal["WAIT"]-actual["WAIT"], .01)
        value = self.dp.evaluate_policy(self.cell.prior, schedule, 2, wait_policy)
        self.assertAlmostEqual(value, actual["WAIT"], places=13)

    def test_common_controller_freezes_model_arrays(self):
        before = self.dp.action_values(self.cell.prior, (.17,), 1)
        self.cell.reward[:] = -50
        self.assertEqual(before, self.dp.action_values(self.cell.prior, (.17,), 1))

    def test_no_latent_state_oracle_in_terminal_value(self):
        terminal = self.dp.value(self.cell.prior, (), 0)
        clairvoyant = self.cell.prior @ self.cell.reward.max(1)
        self.assertLess(terminal, clairvoyant-.4)

    def test_invalid_inputs_and_infeasible_tail_reject(self):
        for belief in (np.array([1., 1., 0., 0.]), np.array([1., 0., 0., np.nan])):
            with self.assertRaises(ValueError):
                self.dp.action_values(belief, (.1,), 1)
        with self.assertRaises(ValueError):
            self.dp.action_values(self.cell.prior, (0.,), 1)
        with self.assertRaises(ValueError):
            self.dp.evaluate_policy(self.cell.prior, (), 0, lambda *args: "READ")


if __name__ == "__main__":
    unittest.main()
