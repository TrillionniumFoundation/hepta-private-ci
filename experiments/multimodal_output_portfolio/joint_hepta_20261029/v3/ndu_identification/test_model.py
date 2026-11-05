"""Behavioral checks for posterior filtration, timing, and exact decision values."""
from fractions import Fraction as F
import math
import unittest
from .model import Task, branches, evaluate, kernel, outcomes, planner, update


class IdentificationTests(unittest.TestCase):
    def test_joint_likelihood_has_information_absent_from_either_marginal(self):
        laws = [kernel("joint", h) for h in (0, 1)]
        for coordinate in (0, 1):
            marginals = [{x: sum((p for *event, p in law if event[coordinate] == x), F(0))
                          for x in {e[coordinate] for e in law}} for law in laws]
            self.assertEqual(marginals[0], marginals[1])
        joint = dict(outcomes("joint", 3))
        self.assertEqual(update(F(1, 2), joint[("0", 1)]), F(1, 9))
        self.assertEqual(update(F(1, 2), joint[("0", 3)]), F(8, 9))
        rows = list(branches("joint", F(1, 2), 3, label_only=True))
        self.assertTrue(all(posterior == F(1, 2) for *_, posterior in rows))

    def test_timeout_censors_unavailable_labels(self):
        self.assertEqual(outcomes("slow", 1), ((("timeout", 1), (F(1), F(1))),))
        self.assertEqual(update(F(3, 5), outcomes("slow", 1)[0][1]), F(3, 5))
        for remaining in (1, 2, 3, 4):
            law = outcomes("joint", remaining)
            self.assertTrue(all(e[1] <= remaining for e, _ in law))
            self.assertEqual([sum((p[h] for _, p in law), F(0)) for h in (0, 1)], [F(1), F(1)])

    def test_known_hypotheses_require_opposite_interventions(self):
        policy, _ = planner(Task(0))
        self.assertEqual([policy(F(h), 0, 3) for h in (0, 1)], ["commit_0", "commit_1"])
        self.assertEqual([evaluate(Task(0), policy, initial=F(h))["utility"] for h in (0, 1)], [1.0, 1.0])

    def test_single_probe_dp_matches_hand_enumeration(self):
        task = Task(deadline=1, max_probes=1)
        policy, solve = planner(task)
        expected = 0.68*math.exp(-task.rho)-task.fee
        self.assertEqual(policy(F(1, 2), 1, 1), "fast:1")
        self.assertAlmostEqual(solve(F(1, 2), 1, 1)[0], expected, places=13)
        self.assertAlmostEqual(evaluate(task, policy)["utility"], expected, places=13)

    def test_wrong_clock_buys_a_tool_that_always_times_out(self):
        task = Task(deadline=1)
        policy, _ = planner(task, "fixed_step")
        result = evaluate(task, policy)
        self.assertEqual(policy(F(1, 2), 1, 3), "slow:1")
        self.assertEqual(result["timeout_probability"], 1)
        self.assertAlmostEqual(result["utility"], .5*math.exp(-task.rho)-task.fee, places=13)
        self.assertLess(result["utility"], .5)

    def test_launch_fees_paid_once_including_timeouts(self):
        task = Task(deadline=2, fee=.1, max_probes=2)
        policy = lambda p, remaining, available: "slow:1" if available else "commit_0"
        result = evaluate(task, policy)
        expected = .5*math.exp(-2*task.rho)-task.fee*(1+math.exp(-task.rho))
        self.assertAlmostEqual(result["utility"], expected, places=13)
        self.assertEqual(result["expected_probes"], 2)
        self.assertEqual(result["timeout_probability"], 1)

    def test_cancellation_preserves_nested_feasible_horizons(self):
        values = []
        for deadline in range(7):
            _, solve = planner(Task(deadline))
            values.append(solve(F(1, 2), deadline, 3)[0])
        self.assertTrue(all(b >= a-1e-13 for a, b in zip(values, values[1:])))

    def test_full_enumeration_matches_dp_and_high_fees_stop(self):
        for task in (Task(2), Task(4), Task(6), Task(4, fee=.6)):
            policy, solve = planner(task)
            self.assertAlmostEqual(evaluate(task, policy)["utility"],
                                   solve(F(1, 2), task.deadline, task.max_probes)[0], places=13)
        policy, _ = planner(Task(4, fee=.6))
        self.assertEqual(evaluate(Task(4, fee=.6), policy)["expected_probes"], 0)

    def test_myopic_policy_is_falsified_on_registered_case(self):
        task = Task(2)
        exact, _ = planner(task)
        myopic, _ = planner(task, "myopic")
        self.assertGreater(evaluate(task, exact)["utility"]-evaluate(task, myopic)["utility"], .02)


if __name__ == "__main__":
    unittest.main()
