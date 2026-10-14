"""R10 schedule, derivative, monitor and frozen-terminal mechanism tests."""
import unittest
from unittest.mock import patch

import numpy as np
import torch

from refine import (
    gaussian_rule,
    schedule_stages,
    stage_rule,
    fit,
    WidePolicy,
    Graph,
    make_problem,
    TARGET,
    TOLERANCE,
)

torch.set_num_threads(1)


class RefinementTests(unittest.TestCase):
    def test_gaussian_rules_positive_and_exact_moments(self):
        for order in (3, 5):
            states, weights = gaussian_rule(order)
            self.assertEqual(states.shape, (order**4, 4))
            self.assertTrue((weights > 0).all())
            self.assertAlmostEqual(weights.sum(), 1.0)
            x = states[:, 0] / 0.25
            for degree in range(2*order):
                expected = 0.0 if degree % 2 else 1/(degree+1)
                self.assertAlmostEqual(float(weights @ x**degree), expected, places=13)

    def test_schedule_is_frozen(self):
        self.assertEqual(schedule_stages("fixed_gl5"), (("gl5", 12.0),))
        self.assertEqual(schedule_stages("stage_gl3_gl5"), (("gl3", 4.0), ("gl5", 12.0)))
        self.assertEqual(len(stage_rule("gl3")[0]), 81)
        self.assertEqual(len(stage_rule("gl5")[0]), 625)

    def test_identical_initial_bytes_across_factorial(self):
        for width in (64, 256):
            for seed in (11, 23, 47):
                first = WidePolicy(width, seed).initial
                for _ in range(8):
                    np.testing.assert_array_equal(first, WidePolicy(width, seed).initial)

    def test_explicit_gradient_and_hvp_both_rules(self):
        policy = WidePolicy(64, 11)
        problem = make_problem()
        for rule_name in ("gl3", "gl5"):
            states, weights = stage_rule(rule_name)
            theta = torch.tensor(policy.initial, requires_grad=True)
            value, grad = policy.adjoint(theta, problem, states, weights)
            auto = torch.autograd.grad(value, theta)[0]
            np.testing.assert_allclose(grad.detach(), auto.detach(), atol=4e-13, rtol=2e-10)
            counts = dict(cache_hits=0, graphs=0, hvp=0, objectives=0)
            graph = Graph(policy, states[:20], weights[:20]/weights[:20].sum(), True, lambda: None, counts)
            v = np.random.default_rng(88).normal(size=len(policy.initial)); v /= np.linalg.norm(v)
            hv = graph.hvp(policy.initial, v)
            fd = (graph.jac(policy.initial+1e-5*v)-graph.jac(policy.initial-1e-5*v))/(2e-5)
            np.testing.assert_allclose(hv, fd, atol=2e-8, rtol=2e-5)

    def test_terminal_gate_does_not_change_weights(self):
        theta, monitors, switches, info = fit(64, 11, "adam", "fixed_gl5", "terminal_only", cap=4.2)
        self.assertEqual(len(monitors), 0)
        self.assertEqual(len(switches), 0)
        self.assertTrue(np.isfinite(theta).all())
        self.assertGreater(info["terminal_wall"], 0)
        self.assertEqual(info["final_qualification"],
                         max(info["terminal_cc5"], info["terminal_cc9"]) <= TARGET and
                         abs(info["terminal_cc9"]-info["terminal_cc5"]) <= TOLERANCE)

    def test_frequent_monitor_never_early_stops(self):
        calls = {"n": 0}
        def zero_eval(policy, theta, problem, states, chunk):
            calls["n"] += 1
            return np.zeros((len(states), 2))
        with patch("refine.evaluate", side_effect=zero_eval):
            theta, monitors, switches, info = fit(64, 11, "adam", "fixed_gl5", "frequent_lazy", cap=4.2)
        self.assertGreater(len(monitors), 1)
        self.assertGreater(info["counts"]["updates"], 0)
        self.assertTrue(all(row["predicate"] for row in info["monitor_checks"]))
        self.assertGreater(info["fit_wall"], 4.0)
        self.assertTrue(info["final_qualification"])

    def test_staged_fit_records_one_switch_and_restarts(self):
        theta, monitors, switches, info = fit(64, 23, "lbfgs", "stage_gl3_gl5", "terminal_only", cap=4.3)
        self.assertEqual(len(switches), 1)
        self.assertEqual(info["counts"]["stage_restarts"], 1)
        self.assertEqual([s["name"] for s in info["stages"]], ["gl3", "gl5"])
        self.assertTrue(np.isfinite(theta).all())

    def test_no_dense_hessian_fallback(self):
        with patch("torch.func.hessian", side_effect=AssertionError("dense fallback")), \
             patch("torch.func.jacfwd", side_effect=AssertionError("dense fallback")):
            theta, _, _, info = fit(64, 47, "adjoint_ncg", "stage_gl3_gl5", "terminal_only", cap=4.2)
        self.assertEqual(info["counts"]["full_hessians"], 0)
        self.assertTrue(np.isfinite(theta).all())

    def test_invalid_requests(self):
        with self.assertRaises(ValueError): gaussian_rule(4)
        with self.assertRaises(ValueError): schedule_stages("adaptive")
        with self.assertRaises(ValueError): fit(64, 11, "bad", "fixed_gl5", "terminal_only")
        with self.assertRaises(ValueError): fit(64, 11, "adam", "bad", "terminal_only")
        with self.assertRaises(ValueError): fit(64, 11, "adam", "fixed_gl5", "bad")


if __name__ == "__main__":
    unittest.main(verbosity=2)
