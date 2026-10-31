"""Numerical contract tests; independent re-optimization and scalar residuals."""

from dataclasses import replace
import unittest

import numpy as np

from ..hcsn_hx_unified_v3.coupled_qvi import TwoCell
from ..hcsn_hx_unified_v3.erlang_async_qvi import solve_erlang_policy
from .oracle import build, solve_jacobi, solve_policy
from .oracle_gradients import direction, one_sided_gradients
from .oracle_validation import configuration, independent_residual, task_model


class TaskValueOracleTests(unittest.TestCase):
    def test_exact_old_model_recovery(self):
        cells, rect, phases = configuration()
        for k in ((1, 1), phases, (3, 2)):
            new = solve_policy(build(cells, rect, k))
            old = solve_erlang_policy(cells, rect, k)
            # The same finite equations have different summation order after
            # generalizing recovery kernels; allow roundoff, not model error.
            np.testing.assert_allclose(new.values, old.values, rtol=0, atol=2e-13)
            np.testing.assert_array_equal(new.policy, old.policy)

    def test_signed_running_rewards_and_refractory_are_charged(self):
        cells, rect, phases = configuration()
        shape = (rect.n1+phases[0], rect.n2+phases[1])
        model = build(cells, rect, phases, running=np.full(shape, -2.),
                      impulse1=np.full(shape, -3.), impulse2=np.full(shape, -4.))
        result = solve_policy(model)
        np.testing.assert_allclose(result.values, -2/cells.first.discount, atol=2e-12)
        self.assertTrue(np.all(result.policy == 0))
        self.assertLess(independent_residual(model, result)["qvi"], 2e-12)

    def test_reward_and_general_kernel_against_scalar_jacobi(self):
        model = task_model()
        answer, reference = solve_policy(model), solve_jacobi(model)
        np.testing.assert_allclose(answer.values, reference.values, atol=2e-9, rtol=0)
        self.assertLess(independent_residual(model, answer)["qvi"], 2e-10)
        cells, rect, phases = configuration()
        zero_running = solve_policy(build(cells, rect, phases, reset1=model.reset1))
        self.assertGreater(np.max(np.abs(zero_running.values-answer.values)), .01)
        self.assertGreater(np.sum(zero_running.policy != answer.policy), 0)

    def test_general_impulse_can_have_disconnected_firing_regions(self):
        cells, rect, phases = configuration()
        base = build(cells, rect, phases)
        first = np.full(base.shape, -20.)
        for i, x in enumerate(base.x1):
            if x < -1 or x > 2:
                first[i, :] = 2.
        model = build(cells, rect, phases, impulse1=first,
                      impulse2=np.full(base.shape, -100.))
        answer = solve_policy(model)
        flags = answer.policy[:rect.n1, 0] == 1
        self.assertTrue(flags[0] and flags[-1])
        self.assertFalse(flags[4])
        self.assertLess(independent_residual(model, answer)["qvi"], 1e-10)

    def test_parameter_gradients_reoptimize_both_sides(self):
        cells, rect, phases = configuration()
        model = build(cells, rect, phases)
        result = solve_policy(model)
        eps = 2e-6
        for field, argument in (("drift", "drift"), ("diffusion", "diffusion"),
                                ("refractory", "refractory"), ("cost", "cost"),
                                ("reset", "reset")):
            with self.subTest(parameter=field):
                value = getattr(cells.first, field)
                plus = TwoCell(replace(cells.first, **{field: value+eps}), cells.second)
                minus = TwoCell(replace(cells.first, **{field: value-eps}), cells.second)
                fp = solve_policy(build(plus, rect, phases)).values
                fm = solve_policy(build(minus, rect, phases)).values
                derivative = one_sided_gradients(model, result,
                                                direction(model, **{argument: (1., 0.)}))
                np.testing.assert_allclose(derivative.right, (fp-fm)/(2*eps),
                                           atol=2e-7, rtol=2e-6)
                self.assertLess(derivative.kink_norm, 1e-10)
                self.assertGreater(derivative.tie_states, 0)
        plus = TwoCell(replace(cells.first, discount=cells.first.discount+eps),
                       replace(cells.second, discount=cells.second.discount+eps))
        minus = TwoCell(replace(cells.first, discount=cells.first.discount-eps),
                        replace(cells.second, discount=cells.second.discount-eps))
        fd = (solve_policy(build(plus, rect, phases)).values-
              solve_policy(build(minus, rect, phases)).values)/(2*eps)
        derivative = one_sided_gradients(model, result, direction(model, discount=1.))
        np.testing.assert_allclose(derivative.right, fd, atol=2e-7, rtol=2e-6)

    def test_softmax_general_reset_and_running_reward_gradients(self):
        model, eps = task_model(), 2e-6
        result = solve_policy(model)
        score = model.x1[None, :]
        dk = model.reset1*(score-(model.reset1*score).sum(axis=1, keepdims=True))
        derivative = one_sided_gradients(model, result, direction(model, reset1=dk))
        fp = solve_policy(task_model(reset_shift=eps)).values
        fm = solve_policy(task_model(reset_shift=-eps)).values
        np.testing.assert_allclose(derivative.right, (fp-fm)/(2*eps), atol=2e-7, rtol=2e-6)
        z, w = np.r_[model.x1, [0., 0.]], np.r_[model.x2, [0., 0.]]
        dg = np.sin(z[:, None]+.2*w[None, :])
        derivative = one_sided_gradients(model, result, direction(model, running=dg))
        fp = solve_policy(task_model(reward_shift=eps)).values
        fm = solve_policy(task_model(reward_shift=-eps)).values
        np.testing.assert_allclose(derivative.right, (fp-fm)/(2*eps), atol=2e-7, rtol=2e-6)

    def test_tangent_bellman_detects_genuine_kink_at_zero_event_reward(self):
        cells, rect, phases = configuration()
        shape = (rect.n1+phases[0], rect.n2+phases[1])
        zero = np.zeros(shape)
        model = build(cells, rect, phases, impulse1=zero, impulse2=np.full(shape, -100.))
        result = solve_policy(model)
        derivative = one_sided_gradients(model, result, direction(model, impulse1=np.ones(shape)))
        # Positive perturbation: fire whenever eligible. Negative: never fire.
        laplace = (1+cells.first.discount*cells.first.refractory/phases[0])**(-phases[0])
        np.testing.assert_allclose(derivative.right[:rect.n1], 1/(1-laplace), atol=3e-12)
        np.testing.assert_allclose(derivative.left, 0., atol=1e-12)
        np.testing.assert_allclose(derivative.fixed, 0., atol=1e-12)
        self.assertGreater(derivative.kink_norm, 1.)
        eps = 2e-6
        positive = solve_policy(build(cells, rect, phases, impulse1=np.full(shape, eps),
                                      impulse2=np.full(shape, -100.))).values
        negative = solve_policy(build(cells, rect, phases, impulse1=np.full(shape, -eps),
                                      impulse2=np.full(shape, -100.))).values
        np.testing.assert_allclose(derivative.right, positive/eps, atol=1e-10)
        np.testing.assert_allclose(derivative.left, -negative/eps, atol=1e-10)

    def test_kernel_and_derivative_domain_guards(self):
        cells, rect, phases = configuration()
        model = build(cells, rect, phases)
        bad = np.array(model.reset1)
        bad[0, 0] = -.01
        with self.assertRaises(ValueError):
            build(cells, rect, phases, reset1=bad)
        bad = np.array(model.reset1)*.9
        with self.assertRaises(ValueError):
            build(cells, rect, phases, reset1=bad)
        with self.assertRaises(ValueError):
            direction(model, reset1=np.ones_like(model.reset1))
        with self.assertRaises(ValueError):
            direction(task_model(), reset=(1., 0.))
        at_node = TwoCell(replace(cells.first, reset=float(model.x1[3])), cells.second)
        with self.assertRaises(ValueError):
            direction(build(at_node, rect, phases), reset=(1., 0.))
        with self.assertRaises(RuntimeError):
            solve_policy(model, max_iterations=1)
        with self.assertRaises(RuntimeError):
            solve_jacobi(model, max_iterations=1)

    def test_seeded_signed_reward_residuals(self):
        cells, rect, phases = configuration()
        rng = np.random.default_rng(613771)
        for _ in range(8):
            shape = (rect.n1+phases[0], rect.n2+phases[1])
            running = rng.normal(0., .2, shape)
            model = build(cells, rect, phases, running=running)
            answer = solve_policy(model)
            residual = independent_residual(model, answer)
            self.assertLess(max(residual.values()), 1e-9)


if __name__ == "__main__":
    unittest.main()
