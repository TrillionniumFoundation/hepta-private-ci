"""Independent safety and policy-equivalence witnesses for R15 planners."""

import unittest

import numpy as np

from ..unified_cell_r12_20261031.task_value import ExactBeliefDP
from ..unified_cell_r12_20261031.test_task_value import TinyCell, enumerate_tree
from .planner import BatchedBeliefDP, CheckedBeliefDP


PLANNERS = (CheckedBeliefDP, BatchedBeliefDP)
NUMERICAL_ERRORS = (ArithmeticError, ValueError)


class NoResetExact(ExactBeliefDP):
    @staticmethod
    def legal_actions(schedule, budget):
        return tuple(action for action in ExactBeliefDP.legal_actions(schedule, budget)
                     if action != "RESET")


class NoResetChecked(CheckedBeliefDP):
    legal_actions = staticmethod(NoResetExact.legal_actions)


class NoResetBatched(BatchedBeliefDP):
    legal_actions = staticmethod(NoResetExact.legal_actions)


class SensorCell:
    """Two clean and two faulty content states with explicit repair semantics."""

    def __init__(self):
        self.Q = np.zeros((4, 4))
        self.E = np.array([[1., 0.], [0., 1.], [.5, .5], [.5, .5]])
        self.R = np.eye(4)[[0, 1, 0, 1]]
        self.reward = (np.arange(4)[:, None] % 2 == np.arange(2)).astype(float)
        self.read_cost = np.array([.03, .05, .07, .09])
        self.prior = np.array([0., 0., .5, .5])


class TieCell:
    """WAIT wins the original sequential tolerance rule, unlike max-minus-eps."""

    def __init__(self):
        self.Q = np.array([[-1., 1.], [0., 0.]])
        self.E = np.ones((2, 1))
        self.R = np.eye(2)
        self.reward = np.array([[0., .75e-12], [1.5e-12 / -np.expm1(-1.), 0.]])
        self.read_cost = np.zeros(2)
        self.prior = np.array([1., 0.])


class PlannerSafetyTests(unittest.TestCase):
    def test_nonfinite_matrix_exponential_is_rejected(self):
        """Finite Q and duration can still exceed the numerical expm domain."""
        cell = TinyCell()
        for planner_type in PLANNERS:
            for duration in (1e100, 1e300):
                with self.subTest(planner=planner_type.__name__, duration=duration):
                    planner = planner_type(cell)
                    with np.errstate(all="ignore"), self.assertRaises(NUMERICAL_ERRORS):
                        planner.action_values(cell.prior, (duration,), 1)
                    with np.errstate(all="ignore"), self.assertRaises(NUMERICAL_ERRORS):
                        planner.choose(cell.prior, (duration,), 1)

    def test_finite_inputs_cannot_silently_overflow_action_fees(self):
        cell = TinyCell()
        for planner_type in PLANNERS:
            with self.subTest(planner=planner_type.__name__):
                planner = planner_type(cell, latency_price=np.finfo(float).max)
                with np.errstate(all="ignore"), self.assertRaises(NUMERICAL_ERRORS):
                    planner.action_values(cell.prior, (2.,), 0)

                def wait_policy(belief, remaining, budget):
                    return "WAIT" if remaining else "STOP0"

                for operation in (planner.evaluate_policy, planner.paired_q_pi):
                    with np.errstate(all="ignore"), self.assertRaises(NUMERICAL_ERRORS):
                        operation(cell.prior, (2.,), 0, wait_policy)
                costly = TinyCell()
                costly.read_cost[:] = np.finfo(float).max
                planner = planner_type(costly, read_multiplier=2.)
                with np.errstate(all="ignore"), self.assertRaises(NUMERICAL_ERRORS):
                    planner.action_values(costly.prior, (.2,), 1)

    def test_invalid_belief_and_schedule_are_not_normalized_into_valid_work(self):
        cell = TinyCell()
        for planner_type in PLANNERS:
            planner = planner_type(cell)
            for belief in (np.array([1., 1., 0., 0.]),
                           np.array([1.1, -.1, 0., 0.]),
                           np.array([1., 0., 0., np.nan])):
                with self.subTest(planner=planner_type.__name__, belief=belief):
                    with self.assertRaises(ValueError):
                        planner.action_values(belief, (.2,), 1)
            for schedule, budget in (((0.,), 1), ((np.inf,), 1), ((.2,), True),
                                     ((.2,), -1), ((.2,) * 9, 1)):
                with self.subTest(planner=planner_type.__name__, schedule=schedule, budget=budget):
                    with self.assertRaises(ValueError):
                        planner.action_values(cell.prior, schedule, budget)

    def test_no_reset_channels_and_future_policy_remain_constrained(self):
        cell = SensorCell()
        options = dict(reset_cost=.02, latency_price=.01)
        reference = NoResetExact(cell, **options)
        unrestricted = ExactBeliefDP(cell, **options)
        schedule = (.2, .3, .4)
        expected = reference.action_values(cell.prior, schedule, 1)
        # Waiting leaves time for repair and a useful READ only in the full policy.
        self.assertGreater(unrestricted.action_values(cell.prior, schedule, 1)["WAIT"]
                           - expected["WAIT"], .4)
        for planner_type in (NoResetChecked, NoResetBatched):
            planner = planner_type(cell, **options)
            with self.subTest(planner=planner_type.__name__):
                actual = planner.action_values(cell.prior, schedule, 1)
                self.assertNotIn("RESET", actual)
                np.testing.assert_allclose(list(actual.values()), list(expected.values()),
                                           rtol=2e-13, atol=5e-14)
                channels = planner.channels(cell.prior, schedule, 1)
                self.assertIsNone(channels["B"])
                self.assertIsNone(channels["advantage"])
                self.assertFalse(channels["reset_strictly_optimal"])
                self.assertEqual(channels["action"], reference.choose(cell.prior, schedule, 1))
                terminal = planner.channels(cell.prior, (), 0)
                self.assertIsNone(terminal["A"])
                self.assertIsNone(terminal["B"])

    def test_sequential_tie_rule_is_not_first_action_near_global_maximum(self):
        cell = TieCell()
        options = dict(reset_cost=1., latency_price=0.)
        reference = ExactBeliefDP(cell, **options)
        expected = reference.action_values(cell.prior, (1.,), 0)
        self.assertEqual(reference.choose(cell.prior, (1.,), 0), "WAIT")
        near_maximum = next(action for action, value in expected.items()
                            if value >= max(expected.values()) - 1e-12)
        self.assertEqual(near_maximum, "STOP1")
        for planner_type in PLANNERS:
            planner = planner_type(cell, **options)
            with self.subTest(planner=planner_type.__name__):
                actual = planner.action_values(cell.prior, (1.,), 0)
                for action in ("STOP0", "STOP1", "WAIT"):
                    self.assertAlmostEqual(actual[action], expected[action], delta=1e-26)
                self.assertEqual(planner.choose(cell.prior, (1.,), 0), "WAIT")

    def test_channels_use_the_same_guarded_action_as_execution(self):
        cell = TinyCell()
        cell.reward = np.column_stack((np.arange(4) * 6.147804351208078e-12,
                                       np.full(4, -1.)))
        belief, schedule = np.array([.7, .1, .1, .1]), (.37,)
        options = dict(reset_cost=1., latency_price=0.)
        reference = ExactBeliefDP(cell, **options)
        expected = reference.choose(belief, schedule, 0)
        for planner_type in PLANNERS:
            planner = planner_type(cell, **options)
            with self.subTest(planner=planner_type.__name__):
                self.assertEqual(planner.choose(belief, schedule, 0), expected)
                self.assertEqual(planner.channels(belief, schedule, 0)["action"], expected)

    def test_values_and_actions_match_reference_and_independent_tree(self):
        cell = TinyCell()
        options = dict(reset_cost=.073, latency_price=.021, read_multiplier=1.7)
        reference = ExactBeliefDP(cell, **options)
        rng = np.random.default_rng(151107)
        beliefs = [cell.prior, np.eye(4)[0], np.eye(4)[3],
                   *rng.dirichlet(np.ones(4), size=3)]
        cases = [((), 0), ((.23,), 0), ((.23,), 1), ((.13, .67), 2),
                 ((.11, .31, .17), 0), ((.11, .31, .17), 1),
                 ((.11, .31, .17), 2), ((.13, .21, .17, .19), 0)]
        for planner_type in PLANNERS:
            planner = planner_type(cell, **options)
            for schedule, budget in cases:
                for index, belief in enumerate(beliefs):
                    with self.subTest(planner=planner_type.__name__, schedule=schedule,
                                      budget=budget, belief=index):
                        actual = planner.action_values(belief, schedule, budget)
                        expected = reference.action_values(belief, schedule, budget)
                        independent = enumerate_tree(cell, belief, schedule, budget, **options)
                        self.assertEqual(tuple(actual), tuple(expected))
                        self.assertEqual(actual.keys(), independent.keys())
                        np.testing.assert_allclose(list(actual.values()), list(expected.values()),
                                                   rtol=2e-13, atol=5e-14)
                        np.testing.assert_allclose([actual[a] for a in independent],
                                                   list(independent.values()), rtol=2e-13, atol=5e-14)
                        self.assertEqual(planner.choose(belief, schedule, budget),
                                         reference.choose(belief, schedule, budget))

    def test_actual_sequence_charges_repair_all_elapsed_time_and_read_multiplier(self):
        cell = SensorCell()
        schedule = (.2, .3, .4)
        options = dict(reset_cost=.02, latency_price=.01, read_multiplier=1.7)

        def policy(belief, remaining, budget):
            if len(remaining) == 3:
                return "RESET"
            if len(remaining) == 2:
                return "WAIT"
            if len(remaining) == 1:
                return "READ" if budget else "WAIT"
            return "STOP" + str(int(np.argmax(belief @ cell.reward)))

        repaired = cell.prior @ cell.R
        # Q=0 and clean observations reveal the bit exactly; all three slots are paid.
        expected = (1. - options["reset_cost"]
                    - options["latency_price"] * sum(schedule)
                    - options["read_multiplier"] * float(repaired @ cell.read_cost))
        self.assertAlmostEqual(expected, .903, places=14)
        for planner_type in PLANNERS:
            planner = planner_type(cell, **options)
            with self.subTest(planner=planner_type.__name__):
                actual = planner.evaluate_policy(cell.prior, schedule, 1, policy)
                self.assertAlmostEqual(actual, expected, places=13)
                forced = planner.paired_q_pi(cell.prior, schedule, 1, policy)
                self.assertAlmostEqual(forced["RESET"], expected, places=13)


if __name__ == "__main__":
    unittest.main()
