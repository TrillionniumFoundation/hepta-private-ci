"""Bellman continuation tests, including the terminal double-payment bug."""

import math
import unittest

import torch

from qualification.hcsn_differentiable.contract import GridSpec, PhysicalParameters
from qualification.hcsn_differentiable.operator import DifferentiableDistributionOperator
from qualification.hcsn_differentiable.value import finite_basis_value, perpetual_basis_value


def parameters(grad=False):
    return PhysicalParameters(*(torch.tensor(v, dtype=torch.float64, requires_grad=grad)
                                for v in (0.0, -0.2, 0.4, math.exp(0.237), 0.3)))


class ValueTests(unittest.TestCase):
    def test_terminal_is_paid_once_even_with_zero_duration_padding(self):
        params = parameters()
        operator = DifferentiableDistributionOperator(GridSpec(active_cells=8, phase_cells=4),
                                                     active_reward=0, hit_reward=0)
        schedule = (0.025, 0.0, 0.05, 0.025)
        matrix = torch.eye(operator.state_count, dtype=torch.float64)
        wrong = params.mu.new_zeros(operator.state_count)
        elapsed = 0.0
        for duration in schedule:
            table = operator(*params.tensors()[:4], duration, params.discount)
            wrong = wrong + torch.exp(-params.discount * elapsed) * (matrix @ table.call)
            matrix = matrix @ table.matrix
            elapsed += duration
        terminal = finite_basis_value(operator, params, ())
        expected = torch.exp(-params.discount * elapsed) * (matrix @ terminal)
        actual = finite_basis_value(operator, params, schedule)
        torch.testing.assert_close(actual, expected, atol=1e-14, rtol=1e-13)
        self.assertGreater(float((wrong - actual).max()), 0.2)
        torch.testing.assert_close(finite_basis_value(operator, params, (0, 0)), terminal)
        self.numerical_evidence = {"terminal_once_max_error": float((actual - expected).abs().max()),
                                   "repeated_call_overpayment": float((wrong - actual).max())}

    def test_variable_schedule_matches_independent_forward_accounting(self):
        params = parameters()
        operator = DifferentiableDistributionOperator(GridSpec(active_cells=8, phase_cells=4))
        p = operator.initial_probability(math.exp(0.3), params.log_boundary)
        initial = p.clone()
        total, elapsed = params.mu.new_zeros(()), 0.0
        schedule = (0.031, 0.078, 0.013)
        for duration in schedule:
            table = operator(*params.tensors()[:4], duration, params.discount)
            reward = operator.active_reward * table.rewards[:, 2] + operator.hit_reward * table.rewards[:, 1]
            total = total + torch.exp(-params.discount * elapsed) * (p @ reward)
            p = p @ table.matrix
            elapsed += duration
        total = total + torch.exp(-params.discount * elapsed) * operator.terminal_reward * p[:operator.grid.active_count].sum()
        torch.testing.assert_close(initial @ finite_basis_value(operator, params, schedule), total)

    def test_perpetual_continuation_and_terminal_independence(self):
        params = parameters()
        grid = GridSpec(active_cells=8, phase_cells=4)
        operator = DifferentiableDistributionOperator(grid, terminal_reward=0)
        changed_terminal = DifferentiableDistributionOperator(grid, terminal_reward=200)
        dt, count = 0.05, 20
        solved = perpetual_basis_value(operator, params, dt)
        other = perpetual_basis_value(changed_terminal, params, dt)
        torch.testing.assert_close(solved.value, other.value, atol=0, rtol=0)
        table = operator(*params.tensors()[:4], dt, params.discount)
        finite = finite_basis_value(operator, params, [dt] * count)
        remainder = torch.exp(-params.discount * count * dt) * torch.linalg.matrix_power(table.matrix, count) @ solved.value
        torch.testing.assert_close(finite + remainder, solved.value, atol=2e-12, rtol=2e-12)
        self.assertLess(float(solved.residual_error_estimate), 1e-10)
        self.numerical_evidence = {"solver_residual": float(solved.bellman_residual.abs().max()),
                                   "arithmetic_error_estimate": float(solved.residual_error_estimate),
                                   "finite_plus_continuation_error": float((finite + remainder - solved.value).abs().max())}

    def test_projected_value_physical_gradient(self):
        params = parameters(grad=True)
        operator = DifferentiableDistributionOperator(GridSpec(active_cells=8, phase_cells=4))
        value = perpetual_basis_value(operator, params, 0.073).value.mean()
        ad = torch.autograd.grad(value, params.tensors())
        records = []
        for index in range(5):
            low = [v.detach().clone() for v in params.tensors()]
            high = [v.detach().clone() for v in params.tensors()]
            step = 1e-5
            low[index] -= step
            high[index] += step
            fd = (perpetual_basis_value(operator, PhysicalParameters(*high), 0.073).value.mean()
                  - perpetual_basis_value(operator, PhysicalParameters(*low), 0.073).value.mean()) / (2 * step)
            error = abs(float(ad[index] - fd))
            records.append({"parameter": index, "AD": float(ad[index]), "FD": float(fd), "absolute_error": error})
            self.assertLess(error, 2e-5 * max(1.0, abs(float(fd))))
        self.numerical_evidence = {"projected_value_gradients": records}

    def test_zero_duration_cannot_define_perpetual_chain(self):
        with self.assertRaisesRegex(ValueError, "positive duration"):
            perpetual_basis_value(DifferentiableDistributionOperator(), parameters(), 0)


if __name__ == "__main__":
    unittest.main()
