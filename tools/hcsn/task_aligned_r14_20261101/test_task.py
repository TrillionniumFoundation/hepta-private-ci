"""Independent numerical, causal-execution and intervention task checks."""

import unittest

import numpy as np
from scipy.linalg import expm_frechet

from ..unified_cell_r12_20261031.cell import Cell
from ..unified_cell_r12_20261031.task_value import ExactBeliefDP, choose_values
from .task import TaskModel, run_validation


class MaintenanceTaskTests(unittest.TestCase):
    def test_reachable_repair_witness_and_negative_controls(self):
        result = run_validation()
        self.assertTrue(all(result["checks"].values()), result)

    def test_factorized_transition_derivative_matches_independent_frechet(self):
        task = TaskModel()
        transition, derivative = task.transition(.43, with_grad=True)
        for index in range(3):
            expected = expm_frechet(task.Q * .43, task.dQ[index] * .43, compute_expm=False)
            np.testing.assert_allclose(derivative[index], expected, atol=3e-12, rtol=2e-11)
        np.testing.assert_allclose(transition.sum(1), 1., atol=3e-14, rtol=0)

    def test_task_emission_jacobian_matches_parameter_perturbation(self):
        task = TaskModel()
        jacobian = task.parameter_jacobians()
        step = 1e-5
        for index in (0, 7, 11):
            plus = task.cell.emission_logits.copy()
            minus = plus.copy()
            plus.flat[index] += step
            minus.flat[index] -= step
            forward = TaskModel(Cell(task.cell.theta, plus)).E
            backward = TaskModel(Cell(task.cell.theta, minus)).E
            np.testing.assert_allclose((forward - backward) / (2 * step),
                                       jacobian["E"][3 + index], atol=3e-11, rtol=2e-8)
        np.testing.assert_array_equal(jacobian["reward"], np.zeros_like(jacobian["reward"]))
        np.testing.assert_array_equal(jacobian["read_cost"], np.zeros_like(jacobian["read_cost"]))

    def test_no_sensor_information_leaks_without_read(self):
        task = TaskModel()
        for action in ("WAIT", "RESET"):
            with self.assertRaises(ValueError):
                task.posterior([(action, .2, 7)])
        for dt in (0., -.1, np.inf, np.nan):
            with self.assertRaises(ValueError):
                task.posterior([("READ", dt, 0)])
        ordinary = task.posterior([("WAIT", .2, None)])
        np.testing.assert_allclose(ordinary, task.prior @ task.transition(.2), atol=1e-15)

    def test_owner_execution_matches_actual_q_pi_with_all_fees(self):
        task = TaskModel()
        dp = ExactBeliefDP(task, reset_cost=task.reset_cost, latency_price=task.latency_price)
        belief = task.posterior([("READ", .15, 7)])
        schedule = (.25, .35, .45)

        def policy(p, rest, budget):
            if rest and budget:
                return "READ"
            return choose_values({a: float(p @ task.reward[:, i])
                                  for i, a in enumerate(("STOP0", "STOP1"))})

        truth = dp.paired_q_pi(belief, schedule, budget=2, policy=policy)
        for initial_action in ("RESET", "WAIT"):
            rng = np.random.default_rng(7081421)
            returns = []
            for _ in range(8000):
                state = int(rng.choice(task.state_count, p=belief))
                p, rest, budget = belief.copy(), schedule, 2
                action, total = initial_action, 0.
                while True:
                    dt = rest[0] if rest else 0.
                    state, token, reward, fee = task.sample_step(state, action, dt, rng)
                    total += reward - fee
                    if action.startswith("STOP"):
                        returns.append(total)
                        break
                    p = task.posterior([(action, dt, token)], prior=p)
                    rest = rest[1:]
                    budget -= int(action == "READ")
                    action = policy(p, rest, budget)
            error = abs(np.mean(returns) - truth[initial_action])
            se = np.std(returns, ddof=1) / np.sqrt(len(returns))
            self.assertLess(error, 6 * se + 1e-12, (initial_action, error, se))

    def test_same_marginals_different_fault_content_correlation_remains_visible(self):
        task = TaskModel()
        first = np.zeros(40)
        second = np.zeros(40)
        # Same fault and bit marginals, different cross-correlation.
        first[8], first[29] = .5, .5
        second[9], second[28] = .5, .5
        np.testing.assert_array_equal(first.reshape(2, 10, 2).sum(1).sum(0),
                                      second.reshape(2, 10, 2).sum(1).sum(0))
        observed_first = task.posterior([("READ", .1, 7)], prior=first)
        observed_second = task.posterior([("READ", .1, 7)], prior=second)
        bit_first = observed_first[1::2].sum()
        bit_second = observed_second[1::2].sum()
        self.assertGreater(abs(bit_first - bit_second), .9)


if __name__ == "__main__":
    unittest.main()
