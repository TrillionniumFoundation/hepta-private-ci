"""Meaningful independent finite-reference and tamper validation."""

from copy import deepcopy
from fractions import Fraction
import unittest

from experiments.continuous_boundary_flow.math_model import solve_dp
from .dp_reference import (
    enumerate_optimum,
    evaluate_policy_exact,
    fixture,
    verify_production_solver,
)


class ExactFiniteReferenceTests(unittest.TestCase):
    def test_exhaustive_policies_and_real_production_solver_agree(self):
        task = fixture()
        optimal = enumerate_optimum(task)
        self.assertEqual(optimal["initial_value"], Fraction(2563, 3200))
        realized = evaluate_policy_exact(task, optimal["policy"])[-1]
        self.assertEqual(realized, optimal["value"])
        receipt = verify_production_solver()
        self.assertTrue(receipt["passed"])
        self.assertLess(receipt["max_abs_value_error"], 2e-13)

    def test_suboptimal_and_stopping_policies_are_not_hidden(self):
        task = fixture()
        optimal = enumerate_optimum(task)
        all_wait = evaluate_policy_exact(task, ((0, 0, 0), (0, 0, 0)))[-1]
        all_stop = evaluate_policy_exact(task, ((2, 2, 2), (2, 2, 2)))[-1]
        self.assertEqual(all_stop, (Fraction(0),) * task["states"])
        wait_value = sum(p * v for p, v in zip(task["initial"], all_wait))
        self.assertLess(wait_value, optimal["initial_value"])

    def test_tampered_production_values_or_action_values_rejected(self):
        for field in ("value", "q", "q_keep"):

            def corrupted(model, field=field):
                result = solve_dp(model)
                result[field].flat[-1] += 0.1
                return result

            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_production_solver(corrupted)

    def test_nonstochastic_fixture_is_rejected(self):
        task = deepcopy(fixture())
        task["repair_transition"] = (Fraction(1), Fraction(1), Fraction(0))
        with self.assertRaises(ValueError):
            enumerate_optimum(task)


if __name__ == "__main__":
    unittest.main()
