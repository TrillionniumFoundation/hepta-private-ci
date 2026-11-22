"""Independent review-clock mathematics; fixed toy data, no formal namespace."""

import math
import json
import unittest
from unittest import mock

import torch

from .control import enumerate_review_policies, fit_lookup_gate, policy_value
from .control import residual_bound, return_affine, review_model, solve_review_control


def toy_model(active=5, interval=0.5):
    generator = torch.zeros(active + 1, active + 1, dtype=torch.float64)
    for i in range(active):
        if i:
            generator[i, i - 1] = 0.7
        if i + 1 < active:
            generator[i, i + 1] = 0.6
        generator[i, active] = 0.2
    generator[active, active // 2] = 2.0
    generator -= torch.diag(generator.sum(1))
    model = review_model(
        generator,
        torch.full((active,), -0.1, dtype=generator.dtype),
        discount=0.3,
        interval=interval,
        active_count=active,
        reset_entry=active,
    )
    initial = torch.full((active + 1,), 1 / (active + 1), dtype=generator.dtype)
    return generator, model, initial


class ReviewControlTests(unittest.TestCase):
    def test_reset_and_continue_both_spend_a_full_review_interval(self):
        rate, rho, interval, payoff = 2.0, 0.3, 0.5, -0.2
        g = torch.tensor([[0.0, 0.0], [rate, -rate]], dtype=torch.float64)
        model = review_model(
            g,
            g.new_tensor([payoff]),
            discount=rho,
            interval=interval,
            active_count=1,
            reset_entry=1,
        )
        beta, survival = math.exp(-rho * interval), math.exp(-rate * interval)
        integral = (1 - beta) / rho
        phase_integral = (1 - math.exp(-(rho + rate) * interval)) / (rho + rate)
        expected_d = g.new_tensor(
            [[beta, 0.0], [beta * (1 - survival), beta * survival]]
        )
        expected_h = g.new_tensor(
            [[integral, 0.0], [integral - phase_integral, phase_integral]]
        )
        torch.testing.assert_close(
            model.discounted_transition, expected_d, atol=1e-13, rtol=1e-13
        )
        torch.testing.assert_close(
            model.reward_integral, expected_h, atol=1e-13, rtol=1e-13
        )
        reward = g.new_tensor([2.0, -1.0])
        phase_value = (expected_h[1] @ reward + expected_d[1, 0] * payoff) / (1 - beta)
        expected = torch.stack((phase_value + payoff, phase_value))
        torch.testing.assert_close(policy_value(model, reward, g.new_ones(1)), expected)
        # The distinct instantaneous-observation impulse value omits active rewards
        # earned after release but before the next review; it must not be substituted.
        impulse_phase_value = (reward[1] + rate * payoff) / rho
        self.assertGreater(float((phase_value - impulse_phase_value).abs()), 0.1)

    def test_reward_integral_matches_an_independent_augmented_exponential(self):
        g, model, _ = toy_model(2, interval=0.125)
        reward = g.new_tensor([-0.8, 0.9, -0.03])
        augmented = g.new_zeros(4, 4)
        augmented[:3, :3] = g - 0.3 * torch.eye(3, dtype=g.dtype)
        augmented[:3, 3] = reward
        expected = torch.matrix_exp(0.125 * augmented)[:3, 3]
        torch.testing.assert_close(
            model.reward_integral @ reward, expected, rtol=1e-12, atol=1e-13
        )
        never = policy_value(model, reward, g.new_zeros(2))
        torch.testing.assert_close(
            never, torch.linalg.solve(0.3 * torch.eye(3, dtype=g.dtype) - g, reward)
        )

    def test_all_hard_and_bounded_corners_match_independent_numpy_evaluation(self):
        _, model, initial = toy_model()
        reward = initial.new_tensor([-2.0, 1.0, -3.0, 1.0, 1.0, -0.05])
        for floor in (0.0, 0.1):
            oracle = enumerate_review_policies(
                model, reward, initial, probability_floor=floor
            )
            for probability, value in zip(
                oracle["all_probabilities"], oracle["all_values"]
            ):
                torch.testing.assert_close(
                    policy_value(model, reward, probability),
                    value,
                    atol=1e-11,
                    rtol=1e-11,
                )
            actual = solve_review_control(model, reward, probability_floor=floor)
            self.assertEqual(actual["status"], "converged")
            torch.testing.assert_close(
                actual["value"],
                oracle["all_values"].max(0).values,
                atol=1e-10,
                rtol=1e-10,
            )
            self.assertEqual(oracle["linear_solves"], 32)

    def test_full_return_gradient_matches_finite_differences(self):
        _, model, initial = toy_model()
        reward = initial.new_tensor([-0.8, 0.3, -0.4, 0.7, 0.4, -0.05])
        logits = torch.linspace(-0.5, 0.5, 5, dtype=initial.dtype, requires_grad=True)
        (gradient,) = torch.autograd.grad(
            initial @ policy_value(model, reward, logits.sigmoid()), logits
        )
        estimates = []
        for i in range(5):
            delta = torch.zeros_like(logits)
            delta[i] = 1e-6
            plus = initial @ policy_value(model, reward, (logits + delta).sigmoid())
            minus = initial @ policy_value(model, reward, (logits - delta).sigmoid())
            estimates.append((plus - minus) / 2e-6)
        torch.testing.assert_close(
            gradient, torch.stack(estimates), atol=1e-8, rtol=1e-6
        )

    def test_one_adjoint_solve_matches_separate_full_return_solves(self):
        _, model, initial = toy_model(2)
        probability = initial.new_tensor([0.2, 0.8])
        rewards = initial.new_tensor(
            [[-0.8, 0.3, -0.03], [0.2, -0.4, 0.6], [0.0, 0.0, 0.0]]
        )
        coefficient, offset = return_affine(model, probability, initial)
        expected = torch.stack(
            [initial @ policy_value(model, row, probability) for row in rewards]
        )
        torch.testing.assert_close(
            rewards @ coefficient + offset, expected, atol=1e-12, rtol=1e-12
        )

    def test_parameterization_gap_and_optimization_gap_are_separate(self):
        _, model, initial = toy_model()
        reward = initial.new_tensor([-2.0, 1.0, -3.0, 1.0, 1.0, -0.05])
        hard = enumerate_review_policies(model, reward, initial)["value"]
        bounded = enumerate_review_policies(
            model, reward, initial, probability_floor=0.1
        )["value"]
        actual = policy_value(model, reward, initial.new_full((5,), 0.5))
        parameter_gap, optimization_gap = (
            initial @ (hard - bounded),
            initial @ (bounded - actual),
        )
        self.assertGreater(float(parameter_gap), 0.0)
        self.assertGreater(float(optimization_gap), 0.0)
        torch.testing.assert_close(
            initial @ (hard - actual), parameter_gap + optimization_gap
        )
        bound = residual_bound(model, reward, actual, probability_floor=0.1)[
            "residual_bound"
        ]
        self.assertLessEqual(float((bounded - actual).abs().max()), bound + 1e-12)

    def test_bp_converges_to_bounded_optimum_without_teacher_values(self):
        _, model, initial = toy_model(1)
        reward = initial.new_tensor([-2.0, 1.0])
        result = fit_lookup_gate(model, reward, initial, logit_limit=2.0, max_steps=256)
        floor = torch.sigmoid(initial.new_tensor(-2.0)).item()
        oracle = enumerate_review_policies(
            model, reward, initial, probability_floor=floor
        )
        self.assertEqual(result["status"], "converged")
        self.assertLessEqual(result["residual_bound"], 1e-8)
        torch.testing.assert_close(
            result["value"], oracle["value"], rtol=1e-9, atol=1e-9
        )
        self.assertEqual(result["linear_solves"], result["backward_passes"] + 1)

    def test_zero_update_budget_is_not_reported_as_convergence(self):
        _, model, initial = toy_model(1)
        reward = initial.new_tensor([-2.0, 1.0])
        result = fit_lookup_gate(model, reward, initial, logit_limit=2.0, max_steps=0)
        self.assertEqual(
            (result["status"], result["steps"], result["backward_passes"]),
            ("budget_exhausted", 0, 0),
        )
        self.assertGreater(result["residual_bound"], 1e-8)
        self.assertEqual(result["trace"][0]["steps"], 0)

    def test_runner_fit_only_reads_train_dev_and_rejects_unbound_final(self):
        from . import control_run

        cfg = {
            "namespace": "unit-only/review-control-v2/fixed-toy-fixture-0000",
            "control": {
                "intervals": [0.5],
                "logit_limits": [2.0],
                "train_count": 4,
                "dev_count": 4,
                "final_count": 4,
                "max_steps": 0,
                "learning_rate": 0.1,
                "value_tolerance": 1e-8,
                "checkpoints": [0],
                "arm_wall_seconds": 30.0,
            },
        }
        with mock.patch.object(
            control_run, "observations", wraps=control_run.observations
        ) as data:
            record = control_run.fit_case(7, cfg)
            self.assertEqual(
                [call.args[2] for call in data.call_args_list], ["train", "dev"]
            )
            with self.assertRaisesRegex(ValueError, "original bound fit record"):
                control_run.final_case(record, 8, cfg)
            self.assertEqual(data.call_count, 2)
        roundtrip = json.loads(json.dumps(record, allow_nan=False))
        box = roundtrip["clocks"][0]["boxes"][0]
        self.assertEqual(
            box["methods"]["lookup_gate_bp"]["solver"]["status"], "budget_exhausted"
        )
        gap = box["training_gap_decomposition"]
        self.assertAlmostEqual(
            gap["hard_optimum_minus_bp"],
            gap["hard_minus_bounded_optimum"] + gap["bounded_optimum_minus_bp"],
            places=12,
        )
        self.assertEqual(record["cost"]["oracle_linear_solves"], 64)


if __name__ == "__main__":
    unittest.main()
