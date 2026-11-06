"""Mechanism and accounting tests, not confirmation-bank tuning."""
import unittest
import numpy as np
from .model import OUTCOMES, Kernel, Task, Policy, estimate, evaluate, rollouts, quality, tv_error, value_radius
from .study import world_kernel, acquisition


def deterministic(event):
    p = np.zeros((2, 2, 2, 12))
    p[..., OUTCOMES.index(event)] = 1
    return Kernel(p)


class Forced:
    def __init__(self, kernel, cap):
        self.kernel, self.cap = kernel, cap

    def __call__(self, belief, z, remaining, steps):
        return (0, min(self.cap, remaining)) if steps and remaining else (-1, int(belief > .5))

    def update(self, belief, z, action, cap, event):
        return self.kernel.posterior(belief, z, action, cap, event)


class Mechanisms(unittest.TestCase):
    def test_atomic_cancel_charged_once_no_state_or_label_leak(self):
        kernel, task = deterministic((0, 3, 1)), Task(1, .1, .02, 1)
        stats = evaluate(kernel, task, Forced(kernel, 1))
        np.testing.assert_allclose(stats, [.155, .275, .1, 1, 1, 0, 1])
        positive = [event for event, a, b in kernel.events(0, 0, 1) if a + b]
        self.assertEqual(positive, [(-2, 1, 0)])

    def test_completed_failure_can_change_state_and_is_paid(self):
        kernel, task = deterministic((-1, 1, 1)), Task(1, .1, .02, 1)
        np.testing.assert_allclose(evaluate(kernel, task, Forced(kernel, 1)), [.38, .5, .1, 1, 1, 1, 0])

    def test_completion_at_cap_is_not_cancelled(self):
        kernel, task = deterministic((0, 3, 1)), Task(3, .1, .02, 1)
        np.testing.assert_allclose(evaluate(kernel, task, Forced(kernel, 3)), [.34, .5, .1, 3, 1, 0, 0])

    def test_joint_duration_updates_when_label_marginal_does_not(self):
        p = np.zeros((2, 2, 2, 12))
        for h, z, a in np.ndindex(2, 2, 2):
            for y, d in ((0, 1), (0, 3), (1, 1), (1, 3)):
                p[h, z, a, OUTCOMES.index((y, d, 0))] = .4 if ((y == h) == (d == 1)) else .1
        k = Kernel(p)
        self.assertAlmostEqual(k.posterior(.5, 0, 0, 3, (1, 1, 0)), .8)
        self.assertAlmostEqual(k.posterior(.5, 0, 0, 3, (1, 3, 0)), .2)
        self.assertAlmostEqual(k.posterior(.5, 0, 0, 3, (1, 1, 0), True), .5)

    def test_two_step_state_control_defeats_myopic(self):
        p = np.zeros((2, 2, 2, 12))
        for h, z, a in np.ndindex(2, 2, 2):
            outcome = (0, 1, 1) if a == 1 else ((h, 1, 1) if z else (0, 1, 0))
            p[h, z, a, OUTCOMES.index(outcome)] = 1
        k, task = Kernel(p), Task(2, .23, 0, 2)
        exact, myopic = Policy(k, task), Policy(k, task, "myopic")
        self.assertEqual(exact(.5, 0, 2, 2)[0], 1)
        self.assertEqual(myopic(.5, 0, 2, 2)[0], -1)
        self.assertAlmostEqual(evaluate(k, task, exact)[0], .54)
        self.assertAlmostEqual(evaluate(k, task, myopic)[0], .275)

    def test_full_ledger_and_smoothing_from_only_purchased_rows(self):
        draws = np.full((2, 2, 2, 4), OUTCOMES.index((-1, 3, 1)), dtype=np.uint8)
        ledger = acquisition(draws, {"launch": .1, "label": .2, "state_reset": .3, "per_simulated_time": .01})
        self.assertEqual(ledger["draws"], 32)
        self.assertAlmostEqual(ledger["total"], 32 * .6 + 96 * .01)
        fitted = estimate(draws)
        self.assertAlmostEqual(fitted.p[0, 0, 0, OUTCOMES.index((-1, 3, 1))], .45)
        self.assertTrue((fitted.p > 0).all())
        self.assertFalse(fitted.p.flags.writeable)

    def test_dp_exact_trajectory_value_and_nested_deadlines(self):
        kernel = world_kernel("restoring", .6)
        values = []
        for deadline in range(5):
            task = Task(deadline)
            policy = Policy(kernel, task)
            exact = evaluate(kernel, task, policy)
            self.assertAlmostEqual(exact[0], policy.solve(.5, 0, deadline, 2)[0], places=12)
            self.assertAlmostEqual(exact[0], exact[1] - exact[2] - .02 * exact[3], places=12)
            values.append(exact[0])
        self.assertTrue(all(a <= b + 1e-12 for a, b in zip(values, values[1:])))

    def test_zero_deadline_or_high_fee_stops(self):
        kernel = world_kernel("restoring", .9)
        for task in (Task(0), Task(4, 2)):
            np.testing.assert_allclose(evaluate(kernel, task, Policy(kernel, task)), [.275, .275, 0, 0, 0, 0, 0])

    def test_realized_and_exact_cancellation_ledgers_match(self):
        kernel, task = deterministic((-1, 3, 1)), Task(1, .1, .02, 1)
        hidden = np.array([0, 1])
        records = rollouts(kernel, task, Forced(kernel, 1), hidden, np.zeros((2, 1, 2, 2)))
        np.testing.assert_allclose(records.mean(axis=0), evaluate(kernel, task, Forced(kernel, 1)))

    def test_fixed_policy_coupling_bound_without_belief_normalization(self):
        a, b, task = world_kernel("restoring", .6), world_kernel("damaging", .9), Task(4)
        epsilon = tv_error(a, b)
        for mode in ("plugin_dp", "no_duration", "no_state", "myopic"):
            policy = Policy(a, task, mode)
            error = abs(evaluate(a, task, policy)[0] - evaluate(b, task, policy)[0])
            self.assertLessEqual(error, value_radius(task, epsilon) + 1e-12)


if __name__ == "__main__":
    unittest.main()
