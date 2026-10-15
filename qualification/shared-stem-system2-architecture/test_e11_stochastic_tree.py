"""E11 substantive finite stochastic/martingale controls (never production)."""
from dataclasses import replace
from fractions import Fraction as F
from pathlib import Path
import sys
import unittest

from e11_dense_reference import exact_dense_system
from e11_stochastic_tree import (
    Law, State, Trace, affine_trace, certify, cheap_root, gains,
    incomplete_martingale_counterexample, number,
)

# Independent original #1923 P4 conditional-moment oracle, not reimplemented
# in the E11 scorer. A mismatch or absent original source fails the CI.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments" / "ndu_tree_fbsde_gates"))
from conditional_moments import calculate  # noqa: E402


class E11DiscreteStochastic(unittest.TestCase):
    def test_nonzero_driver_and_exact_dense_parity_for_six_profiles(self):
        for steps in (1, 2, 3):
            for coupling in ("0", "1/3"):
                with self.subTest(steps=steps, coupling=coupling):
                    law = Law(steps=steps, a=coupling)
                    trace = affine_trace(law)
                    dense, meta = exact_dense_system(law)
                    self.assertEqual(trace, dense)
                    self.assertEqual(cheap_root(law), number(dense.states[0].y))
                    self.assertTrue(certify(law, dense).globally_consistent_registered_law)
                    self.assertEqual(meta["equation_count"], 2 * len(trace.states))
                    self.assertEqual(meta["physical_model_forwards"], 0)
                    self.assertNotEqual(trace.states[1].x, trace.states[2].x)
                    self.assertEqual(len(trace.z), 2**steps - 1)

    def test_orig_p4_covariance_and_martingale_representation(self):
        law = Law(steps=3, driver_scale="2", sigma="1/2")
        trace = affine_trace(law)
        m = number(law.driver_scale)
        for i in range(2**law.steps-1):
            left = number(trace.states[2*i+1].y)
            right = number(trace.states[2*i+2].y)
            cert = calculate((F(1, 2), F(1, 2)), ((-m,), (m,)), (left, right))
            self.assertEqual(cert.z, (number(trace.z[i]),))
            self.assertEqual(cert.covariance, ((m*m,),))
            self.assertEqual(cert.covariance_regression_residual, (F(0),))
            self.assertEqual(cert.martingale_representation_residual, (F(0), F(0)))
            self.assertTrue(cert.martingale_complete)

    def test_global_leaf_terminal_mismatch(self):
        law = Law()
        t = affine_trace(law)
        states = list(t.states)
        states[-1] = replace(states[-1], y=str(number(states[-1].y)+F(1, 4)))
        result = certify(law, replace(t, states=tuple(states)))
        self.assertFalse(result.globally_consistent_registered_law)
        self.assertNotEqual(result.terminal, "0")

    def test_backward_interface_reset_not_a_global_solution(self):
        law = Law()
        t = affine_trace(law)
        states = list(t.states)
        states[1] = replace(states[1], y="0")
        result = certify(law, replace(t, states=tuple(states)))
        self.assertFalse(result.globally_consistent_registered_law)
        self.assertNotEqual(result.backward, "0")

    def test_future_branch_state_tamper_is_detected(self):
        law = Law()
        t = affine_trace(law)
        states = list(t.states)
        states[2] = replace(states[2], x=str(number(states[2].x)+F(1, 2)))
        r = certify(law, replace(t, states=tuple(states)))
        self.assertFalse(r.globally_consistent_registered_law)
        self.assertNotEqual(r.forward, "0")

    def test_wrong_noise_sensitivity_even_if_xy_stays_correct(self):
        law = Law()
        t = affine_trace(law)
        bad_z = list(t.z)
        bad_z[0] = str(number(bad_z[0])+F(1))
        cert = certify(law, replace(t, z=tuple(bad_z)))
        self.assertFalse(cert.globally_consistent_registered_law)
        self.assertNotEqual(cert.covariance, "0")
        self.assertNotEqual(cert.martingale, "0")

    def test_full_rank_covariance_is_not_martingale_completeness(self):
        counter = incomplete_martingale_counterexample()
        self.assertEqual(counter["covariance"], "2/3")
        self.assertEqual(counter["z"], "0")
        self.assertTrue(counter["z_sigma_equals_b"])
        self.assertFalse(counter["martingale_complete"])
        self.assertEqual(counter["orthogonal_residual"], ("1/3", "-2/3", "1/3"))
        self.assertFalse(counter["stochastic_fbsde_global_qualified"])

    def test_unqualified_global_decoupling_rejects_before_any_solve(self):
        law = Law(steps=1, horizon="1", a="1", lam="0",
                  beta="0", terminal_gain="1", sigma="1")
        for call in (lambda: gains(law), lambda: affine_trace(law),
                     lambda: exact_dense_system(law)):
            with self.assertRaises(ValueError):
                call()

    def test_missing_or_extra_prefix_or_z_rejects(self):
        law = Law()
        t = affine_trace(law)
        for bad in (replace(t, states=t.states[:-1]),
                    replace(t, states=t.states+t.states[-1:]),
                    replace(t, z=t.z[:-1]),
                    replace(t, states=tuple(list(t.states[:-1])+[None]))):
            with self.assertRaises(ValueError):
                certify(law, bad)

    def test_bad_types_and_noncanonical_values(self):
        for value in ("01", "-0", "+1", "2/4", "1.0", "NaN", "1e-2",
                      "00/1", "1/0", "1/" + "9"*60):
            with self.subTest(value=value), self.assertRaises(ValueError):
                number(value)
        for bad in (Law(steps=True), Law(steps=5), Law(sigma="0"),
                    Law(driver_scale="0"), Law(horizon="-1")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                affine_trace(bad)

    def test_dense_control_is_bounded_and_no_silent_fallback(self):
        with self.assertRaises(ValueError):
            exact_dense_system(Law(steps=4))
        self.assertEqual(certify(Law(), affine_trace(Law())).authority, "DENY_ALL")
        self.assertFalse(certify(Law(), affine_trace(Law())).independent_future_task_utility)

    def test_no_equation_false_positive_for_orthogonal_noise(self):
        law = Law(steps=2, sigma="1/3", driver_scale="3/2")
        result = certify(law, affine_trace(law))
        self.assertTrue(result.globally_consistent_registered_law)
        self.assertEqual(result.covariance, "0")
        self.assertEqual(result.martingale, "0")
        self.assertFalse(result.continuous_fbsde_qualified)


if __name__ == "__main__":
    unittest.main()
