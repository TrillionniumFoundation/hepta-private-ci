"""Global inequalities, independent maximization, and full-resolve gradients."""

import math
import unittest

import numpy as np
from scipy.optimize import minimize_scalar

from experiments.free_boundary_neuron.math.finite_horizon import (
    build_readout,
    solve_bermudan,
)
from experiments.free_boundary_neuron.math.one_shot import one_shot_solution
from experiments.free_boundary_neuron.math.renewal import (
    renewal_objective,
    renewal_solution,
)


class OneShotTests(unittest.TestCase):
    def test_whole_domain_obstacle_and_superharmonic_verification(self):
        for mu in (-0.4, 0.0, 0.6):
            answer = one_shot_solution(mu, 0.7, 0.2, 0.3, killing=0.1)
            b = answer.boundary
            x = np.linspace(b - 6, b + 6, 801)
            self.assertGreaterEqual(float(np.min(answer.value(x) - (x - 0.3))), -1e-12)
            self.assertLessEqual(float(np.max(answer.generator_residual(x))), 1e-12)
            self.assertAlmostEqual(float(answer.derivative_x(b - 1e-9)), 1.0, places=8)
            # Derive the continuation generator from numerical value differences.
            interior = np.linspace(b - 3, b - 0.2, 30)
            h = 1e-4
            up, center, down = (
                answer.value(interior + h),
                answer.value(interior),
                answer.value(interior - h),
            )
            residual = (
                mu * (up - down) / (2 * h)
                + 0.5 * 0.7**2 * (up - 2 * center + down) / h**2
                - 0.3 * center
            )
            self.assertLess(float(np.max(np.abs(residual))), 2e-7)

    def test_global_threshold_maximization_and_full_resolve_sensitivities(self):
        kwargs = dict(mu=0.4, sigma=0.8, discount=0.2, cost=0.3, killing=0.1)
        answer = one_shot_solution(**kwargs)
        initial = -0.5

        def objective(b):
            return -(b - kwargs["cost"]) * math.exp(-answer.roots.kappa * (b - initial))

        opt = minimize_scalar(
            objective, bounds=(kwargs["cost"], answer.boundary + 10), method="bounded"
        )
        self.assertAlmostEqual(opt.x, answer.boundary, places=5)
        for key, reference in answer.boundary_derivatives.items():
            plus, minus = kwargs.copy(), kwargs.copy()
            plus[key] += 1e-5
            minus[key] -= 1e-5
            fd = (
                one_shot_solution(**plus).boundary - one_shot_solution(**minus).boundary
            ) / 2e-5
            np.testing.assert_allclose(fd, reference, rtol=2e-8, atol=1e-9)
            states = np.array([-0.5, answer.boundary - 0.3, answer.boundary + 0.3])
            fd_value = (
                one_shot_solution(**plus).value(states)
                - one_shot_solution(**minus).value(states)
            ) / 2e-5
            np.testing.assert_allclose(
                fd_value, answer.value_sensitivities(states)[key], rtol=2e-7, atol=1e-8
            )

    def test_constrained_threshold_does_not_claim_smooth_fit(self):
        answer = one_shot_solution(0.4, 0.8, 0.2, 0.3, bounds=(0.4, 0.7))
        self.assertEqual(answer.regime, "upper_bound")
        self.assertEqual(answer.boundary, 0.7)
        self.assertNotAlmostEqual(float(answer.derivative_x(0.7 - 1e-9)), 1.0, places=4)


class RenewalTests(unittest.TestCase):
    def test_independent_solver_and_global_optimizer(self):
        for pars in (
            (0.5, 1.0, 0.2, 0.0, 0.5, 0.4),
            (-0.4, 0.8, 0.3, 0.0, 0.0, 1.0),
            (1.0, 0.5, 0.2, 0.0, 1.0, 0.0),
        ):
            answer = renewal_solution(*pars)
            independent = renewal_solution(*pars, method="brent")
            self.assertAlmostEqual(answer.boundary, independent.boundary, places=11)
            mu, sigma, rho, reset, cost, refractory = pars
            opt = minimize_scalar(
                lambda b: -renewal_objective(b, *pars),
                bounds=(max(reset, cost) + 1e-8, answer.boundary + 10),
                method="bounded",
            )
            self.assertAlmostEqual(opt.x, answer.boundary, places=5)
            x = np.linspace(answer.boundary - 6, answer.boundary + 6, 1001)
            obstacle = x - cost + answer.delta * answer.reset_value
            self.assertGreaterEqual(float(np.min(answer.value(x) - obstacle)), -1e-12)
            self.assertLessEqual(float(np.max(answer.generator_residual(x))), 1e-12)
            interior = np.linspace(answer.boundary - 3, answer.boundary - 0.2, 30)
            step = 1e-4
            up, center, down = (
                answer.value(interior + step),
                answer.value(interior),
                answer.value(interior - step),
            )
            residual = (
                mu * (up - down) / (2 * step)
                + 0.5 * sigma**2 * (up - 2 * center + down) / step**2
                - rho * center
            )
            self.assertLess(float(np.max(np.abs(residual))), 2e-7)
            stopping = np.linspace(answer.boundary + 0.2, answer.boundary + 3, 30)
            up, center, down = (
                answer.value(stopping + step),
                answer.value(stopping),
                answer.value(stopping - step),
            )
            residual = (
                mu * (up - down) / (2 * step)
                + 0.5 * sigma**2 * (up - 2 * center + down) / step**2
                - rho * center
            )
            self.assertLess(float(np.max(residual)), 0.0)

    def test_every_derivative_recomputes_entire_renewal_solution(self):
        kwargs = dict(
            mu=0.5, sigma=1.0, discount=0.2, reset=0.0, cost=0.5, refractory=0.4
        )
        answer = renewal_solution(**kwargs)
        for key in kwargs:
            plus, minus = kwargs.copy(), kwargs.copy()
            plus[key] += 1e-5
            minus[key] -= 1e-5
            a, b = (
                renewal_solution(**plus, method="brent"),
                renewal_solution(**minus, method="brent"),
            )
            for measured, reference in (
                ((a.boundary - b.boundary) / 2e-5, answer.boundary_derivatives[key]),
                ((a.reset_value - b.reset_value) / 2e-5, answer.value_derivatives[key]),
            ):
                np.testing.assert_allclose(measured, reference, rtol=3e-7, atol=2e-8)
            states = np.array([-0.3, answer.boundary - 0.3, answer.boundary + 0.3])
            fd_value = (a.value(states) - b.value(states)) / 2e-5
            np.testing.assert_allclose(
                fd_value, answer.value_sensitivities(states)[key], rtol=3e-7, atol=2e-8
            )

    def test_degeneracy_constraints_and_conditioning_are_explicit(self):
        self.assertEqual(
            renewal_solution(0.2, 0.8, 0.2, 1.0, 0.5, 0.0).regime, "unbounded"
        )
        self.assertEqual(
            renewal_solution(0.2, 0.8, 0.2, 0.0, 0.0, 0.0).regime, "chattering_supremum"
        )
        immediate = renewal_solution(0.2, 0.8, 0.2, 0.0, -2.0, 1.0)
        self.assertEqual(immediate.regime, "immediate_after_refractory")
        self.assertAlmostEqual(immediate.reset_value, 2 / (1 - math.exp(-0.2)))
        constrained = renewal_solution(0.2, 0.8, 0.2, 1.0, 0.5, 0.0, min_gap=0.1)
        self.assertEqual(constrained.regime, "lower_bound")
        self.assertTrue(math.isfinite(constrained.reset_value))
        near = renewal_solution(0.3, 0.8, 0.2, 0.0, 1e-12, 0.0)
        reference = renewal_solution(0.3, 0.8, 0.2, 0.0, 1e-12, 0.0, method="brent")
        np.testing.assert_allclose(near.boundary, reference.boundary, rtol=1e-8)
        self.assertGreater(near.condition_index, 1e5)

    def test_constrained_abstain_policy_has_zero_derivatives(self):
        answer = renewal_solution(0.2, 0.8, 0.2, 0.0, 2.0, 0.5, max_gap=0.2)
        self.assertEqual(answer.regime, "abstain")
        states = np.array([-1.0, 0.0, 0.2, 3.0])
        np.testing.assert_array_equal(answer.value(states), np.zeros(4))
        np.testing.assert_array_equal(answer.derivative_x(states), np.zeros(4))
        np.testing.assert_array_equal(answer.generator_residual(states), np.zeros(4))


class BermudanTests(unittest.TestCase):
    def test_exported_transition_and_bellman_equation(self):
        data = build_readout()
        transition = np.asarray(data["transition"])
        value, continuation = (
            np.asarray(data["value"]),
            np.asarray(data["continuation"]),
        )
        stop, action = np.asarray(data["stop_value"]), np.asarray(data["action"])
        self.assertTrue(np.all(transition >= 0))
        np.testing.assert_allclose(
            transition.sum(1), math.exp(-data["killing_rate"] * data["dt"]), atol=1e-15
        )
        # Independent scalar loops also detect orientation and survival double counting.
        for remaining in (1, 7, 32):
            for state in (0, 17, 50, 83, 100):
                future = sum(
                    float(p) * float(v)
                    for p, v in zip(transition[state], value[remaining - 1])
                )
                candidate = (
                    -data["running_cost"] * data["dt"]
                    + math.exp(-data["rho"] * data["dt"]) * future
                )
                self.assertAlmostEqual(
                    candidate, continuation[remaining, state], places=13
                )
                self.assertAlmostEqual(
                    max(0, stop[state], candidate), value[remaining, state], places=13
                )
                expected = (
                    "abstain"
                    if max(stop[state], candidate) <= 0
                    else ("stop" if stop[state] >= candidate else "continue")
                )
                self.assertEqual(action[remaining, state], expected)
        self.assertTrue(np.all(value[1:] >= value[:-1] - 1e-12))

    def test_policy_evaluation_recovers_bellman_value(self):
        data = solve_bermudan(
            np.linspace(-1, 1, 21), 6, 0.05, 0.1, 0.5, 0.2, 0.1, 0.2, 0.03
        )
        evaluated = np.maximum(data["stop_value"], 0)
        for n in range(1, 7):
            wait = -0.03 * 0.05 + math.exp(-0.2 * 0.05) * data["transition"].dot(
                evaluated
            )
            evaluated = np.where(
                data["action"][n] == "stop",
                data["stop_value"],
                np.where(data["action"][n] == "continue", wait, 0),
            )
        np.testing.assert_allclose(evaluated, data["value"][-1], atol=1e-14)


if __name__ == "__main__":
    unittest.main()
