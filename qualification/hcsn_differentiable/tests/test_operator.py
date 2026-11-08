"""New numerical fixtures, independent of all old S81 qualification results.

The runner can serialize ``test.numerical_evidence`` after each test. Numerical
fixtures also print one JSON line so the values survive a plain unittest run.
This module intentionally fails to import when Torch is missing; a missing
dependency must not become a successful skipped qualification.
"""

from dataclasses import replace
import json
import math
import unittest

import torch

from qualification.hcsn_differentiable.contract import GridSpec, PhysicalParameters
from qualification.hcsn_differentiable.operator import DifferentiableDistributionOperator


def _phi_cdf(value):
    return 0.5 * math.erfc(-value / math.sqrt(2.0))


def _first_hit_reference(x, time, mu, sigma):
    """Reflection-principle reference using Python math, not the Torch kernel."""
    if time <= 0:
        return 0.0
    scale = sigma * math.sqrt(time)
    return (_phi_cdf((-x - mu * time) / scale)
            + math.exp(-2.0 * mu * x / (sigma * sigma))
            * _phi_cdf((-x + mu * time) / scale))


def _simpson(function, left, right, intervals=4000):
    if intervals % 2:
        raise ValueError("Simpson reference requires an even interval count")
    width = (right - left) / intervals
    values = [function(left + i * width) for i in range(intervals + 1)]
    return width / 3.0 * (values[0] + values[-1]
                          + 4.0 * math.fsum(values[1:-1:2])
                          + 2.0 * math.fsum(values[2:-1:2]))


def _discounted_hit_reference(x, time, mu, sigma, discount):
    def density(t):
        if t == 0:
            return 0.0
        return (x / (sigma * math.sqrt(2.0 * math.pi * t**3))
                * math.exp(-discount * t - (x + mu * t)**2 / (2.0 * sigma**2 * t)))
    return _simpson(density, 0.0, time)


def _occupation_reference(x, time, mu, sigma, discount):
    return _simpson(lambda t: math.exp(-discount * t)
                    * (1.0 - _first_hit_reference(x, t, mu, sigma)), 0.0, time)


def _prior_hit_reference(mean, std, horizon, mu, sigma):
    denominator = _phi_cdf(mean / std)
    upper = mean + 10.0 * std
    return _simpson(lambda x: math.exp(-0.5 * ((x - mean) / std)**2)
                    / (std * math.sqrt(2.0 * math.pi) * denominator)
                    * _first_hit_reference(x, horizon, mu, sigma), 0.0, upper, 6000)


def _params(log_boundary=0.02, mu=-0.25, sigma=0.45,
            absolute_reset=math.exp(0.18), discount=0.2):
    return PhysicalParameters(*(torch.tensor(value, dtype=torch.float64)
                                for value in (log_boundary, mu, sigma, absolute_reset, discount)))


class OperatorNumericalTests(unittest.TestCase):
    def setUp(self):
        self.numerical_evidence = {}
        self.params = _params()

    def tearDown(self):
        if self.numerical_evidence:
            print("HCSN_NUMERICAL_EVIDENCE " + json.dumps(
                {"test": self.id(), **self.numerical_evidence}, sort_keys=True, allow_nan=False))

    def _table(self, operator, params=None, dt=0.075):
        p = self.params if params is None else params
        return operator(p.log_boundary, p.mu, p.sigma, p.absolute_reset, dt, p.discount)

    def test_contract_and_episode_snapshot_reject_changes(self):
        grid = GridSpec()
        self.assertEqual(grid.state_count, 25)
        self.assertEqual(grid.active_count, 17)
        snapshot = self.params.snapshot()
        self.params.assert_matches_snapshot(snapshot)
        changed = replace(self.params, log_boundary=self.params.log_boundary + 0.01)
        with self.assertRaisesRegex(ValueError, "within an episode"):
            changed.assert_matches_snapshot(snapshot)
        with self.assertRaises(ValueError):
            GridSpec(refractory=torch.tensor(0.1))
        with self.assertRaises(ValueError):
            GridSpec(quadrature_order=12)
        operator = DifferentiableDistributionOperator(grid)
        with self.assertRaises(ValueError):
            self._table(operator, replace(self.params, sigma=self.params.sigma.float()))
        with self.assertRaises(ValueError):
            self._table(operator, replace(self.params, absolute_reset=torch.exp(self.params.log_boundary)))
        with self.assertRaises(ValueError):
            self._table(operator, dt=0.101)
        with self.assertRaises(ValueError):
            self._table(operator, dt=torch.tensor(0.05, dtype=torch.float64, requires_grad=True))

    def test_point_law_against_independent_first_passage_integrals(self):
        grid = GridSpec(quadrature_order=64)
        operator = DifferentiableDistributionOperator(grid)
        params = _params(mu=-0.1, sigma=0.5, discount=0.3)
        x, time = 0.2, 0.08
        row, reward = operator._point_row(torch.tensor(x, dtype=torch.float64), time, params)
        reference = [_first_hit_reference(x, time, -0.1, 0.5),
                     _discounted_hit_reference(x, time, -0.1, 0.5, 0.3),
                     _occupation_reference(x, time, -0.1, 0.5, 0.3)]
        actual = reward.detach().tolist()
        errors = [abs(a - b) for a, b in zip(actual, reference)]
        self.numerical_evidence = {"x": x, "dt": time, "mu": -0.1, "sigma": 0.5,
                                   "discount": 0.3, "torch": actual, "independent_reference": reference,
                                   "absolute_errors": errors,
                                   "point_row_mass_residual": float(row.sum() - 1.0)}
        self.assertLess(max(errors), 3e-9)
        self.assertLess(abs(float(row.sum() - 1.0)), 5e-12)
        self.assertLess(float(reward[1]), float(reward[0]))
        self.assertAlmostEqual(float(row[:grid.active_count].sum()), 1.0 - reference[0], delta=3e-12)

    def test_initial_absolute_mapping_has_real_boundary_derivative(self):
        operator = DifferentiableDistributionOperator()
        boundary = torch.tensor(0.07, dtype=torch.float64, requires_grad=True)
        initial = torch.tensor([math.exp(0.27), math.exp(0.43)], dtype=torch.float64)
        coefficients = operator.initial_probability(initial, boundary)
        weight = operator._margin_feature(boundary)
        loss = (coefficients @ weight).sum()
        derivative = float(torch.autograd.grad(loss, boundary)[0])
        step = 1e-6
        plus = operator.initial_probability(initial, boundary.detach() + step) @ weight
        minus = operator.initial_probability(initial, boundary.detach() - step) @ weight
        finite_difference = float((plus.sum() - minus.sum()) / (2.0 * step))
        self.numerical_evidence = {"d_initial_mean_d_log_boundary": derivative,
                                   "finite_difference": finite_difference,
                                   "absolute_error": abs(derivative - finite_difference),
                                   "fixed_initial_log_std": operator.grid.initial_log_std}
        self.assertLess(abs(derivative - finite_difference), 2e-8)
        self.assertLess(derivative, -0.5)
        torch.testing.assert_close(coefficients.sum(-1), torch.ones(2, dtype=torch.float64), atol=2e-14, rtol=0)
        # Translating both physical log locations by the same constant leaves x
        # invariant. This identifies the coordinate convention, not a free b.
        translated = operator.initial_probability(initial * math.exp(0.2), boundary + 0.2)
        torch.testing.assert_close(coefficients, translated, atol=3e-15, rtol=2e-13)

    def test_conservation_content_transport_and_zero_duration(self):
        operator = DifferentiableDistributionOperator()
        initial = torch.tensor([math.exp(0.29), math.exp(0.35), math.exp(0.42)], dtype=torch.float64)
        p = operator.initial_probability(initial, self.params.log_boundary)
        values = torch.tensor([1.0, -0.7, 2.3], dtype=torch.float64)
        content = p[..., None] * values
        old_p, old_content = p.clone(), content.clone()
        receipt = operator.advance(p, content, torch.tensor([0.0, 0.037, 0.1], dtype=torch.float64), self.params)
        self.numerical_evidence = {"maximum_mass_residual": float(receipt.mass_residual.abs().max()),
                                   "minimum_probability": float(receipt.probability.min()),
                                   "events_by_duration": receipt.expected_events.tolist(),
                                   "maximum_content_total_error": float((receipt.content_mass.sum(1) - content.sum(1)).abs().max())}
        torch.testing.assert_close(receipt.content_mass, receipt.probability[..., None] * values,
                                   atol=5e-14, rtol=2e-13)
        torch.testing.assert_close(receipt.probability.sum(-1), p.sum(-1), atol=5e-12, rtol=0)
        torch.testing.assert_close(receipt.content_mass.sum(1), content.sum(1), atol=5e-12, rtol=0)
        self.assertTrue(torch.equal(receipt.probability[0], p[0]))
        self.assertTrue(torch.equal(receipt.content_mass[0], content[0]))
        self.assertEqual(float(receipt.expected_events[0]), 0.0)
        self.assertEqual(float(receipt.discounted_active_time[0]), 0.0)
        self.assertTrue(torch.equal(old_p, p))
        self.assertTrue(torch.equal(old_content, content))
        self.assertGreaterEqual(float(receipt.probability.min()), 0.0)

    def test_call_is_one_interval_reward_with_terminal_paid_once(self):
        operator = DifferentiableDistributionOperator(active_reward=0.4, hit_reward=1.0, terminal_reward=0.2)
        table = self._table(operator, dt=0.075)
        reference = (0.4 * table.rewards[:, 2] + table.rewards[:, 1]
                     + 0.2 * torch.exp(-self.params.discount * 0.075)
                     * table.matrix[:, :operator.grid.active_count].sum(-1))
        zero = self._table(operator, dt=0.0)
        self.numerical_evidence = {"maximum_interval_value_difference": float((table.call - reference).abs().max()),
                                   "maximum_risk_count_difference": float((table.risk - table.rewards[:, 0]).abs().max()),
                                   "zero_duration_active_terminal_value": float(zero.call[0]),
                                   "zero_duration_refractory_terminal_value": float(zero.call[-1]),
                                   "zero_duration_total_rewards": float(zero.rewards.sum())}
        torch.testing.assert_close(table.call, reference, atol=0, rtol=0)
        torch.testing.assert_close(table.risk, table.rewards[:, 0], atol=0, rtol=0)
        self.assertEqual(float(zero.call[0]), 0.2)
        self.assertEqual(float(zero.call[-1]), 0.0)
        self.assertEqual(float(zero.rewards.sum()), 0.0)

    def test_tail_mass_can_return_and_hit(self):
        grid = GridSpec(active_cells=12, endpoint=0.3, tail_rate=4.0, quadrature_order=32)
        operator = DifferentiableDistributionOperator(grid)
        params = _params(mu=-0.3, sigma=0.7)
        table = self._table(operator, params=params, dt=0.1)
        tail_index = grid.active_cells
        returned = float(table.matrix[tail_index, :grid.active_cells].sum())
        hits = float(table.rewards[tail_index, 0])
        self.numerical_evidence = {"tail_to_finite_active_probability": returned,
                                   "tail_first_hit_probability": hits,
                                   "tail_retained_probability": float(table.matrix[tail_index, tail_index])}
        self.assertGreater(returned, 0.03)
        self.assertGreater(hits, 0.002)
        self.assertLess(float(table.matrix[tail_index, tail_index]), 0.97)
        self.assertAlmostEqual(float(table.matrix[tail_index].sum()), 1.0, delta=5e-12)

    def test_aligned_remaining_time_transport_does_not_use_erlang_release(self):
        operator = DifferentiableDistributionOperator(GridSpec(phase_cells=8))
        grid = operator.grid
        table = self._table(operator, dt=0.025)
        source = grid.active_count + 7  # remaining time uniform on [.0875,.1]
        target = grid.active_count + 5  # remaining time uniform on [.0625,.075]
        expected = torch.zeros(grid.state_count, dtype=torch.float64)
        expected[target] = 1.0
        self.numerical_evidence = {"aligned_phase_row_l1_error": float((table.matrix[source] - expected).abs().sum()),
                                   "initial_phase_row_reward_sum": float(table.rewards[source].sum())}
        torch.testing.assert_close(table.matrix[source], expected, atol=0, rtol=0)
        self.assertEqual(float(table.rewards[source].sum()), 0.0)
        state = torch.zeros(grid.state_count, dtype=torch.float64)
        state[source] = 1.0
        for _ in range(3):
            state = state @ table.matrix
        self.numerical_evidence["active_after_0.075"] = float(state[:grid.active_count].sum())
        self.assertEqual(float(state[:grid.active_count].sum()), 0.0)
        state = state @ table.matrix
        self.numerical_evidence["active_after_0.1"] = float(state[:grid.active_count].sum())
        self.assertGreater(float(state[:grid.active_count].sum()), 0.1)

    def test_no_reset_control_is_explicit_permanent_absorption(self):
        grid = GridSpec()
        killed = DifferentiableDistributionOperator(grid, reset_enabled=False)
        regenerative = DifferentiableDistributionOperator(grid)
        a = self._table(killed, dt=0.1)
        b = self._table(regenerative, dt=0.1)
        absorbed = grid.active_count
        self.numerical_evidence = {"absorbed_self_probability": float(a.matrix[absorbed, absorbed]),
                                   "absorbed_reward_sum": float(a.rewards[absorbed].sum()),
                                   "unreachable_phase_mass": float(a.matrix[:grid.active_count, absorbed + 1:].sum()),
                                   "regenerative_release_active_mass": float(b.matrix[absorbed, :grid.active_count].sum()),
                                   "maximum_absorption_hit_error": float((a.matrix[:grid.active_count, absorbed]
                                                                          - a.rewards[:grid.active_count, 0]).abs().max())}
        self.assertEqual(float(a.matrix[absorbed, absorbed]), 1.0)
        self.assertEqual(float(a.rewards[absorbed].sum()), 0.0)
        self.assertEqual(float(a.matrix[:grid.active_count, absorbed + 1:].sum()), 0.0)
        self.assertGreater(float(b.matrix[absorbed, :grid.active_count].sum()), 0.1)
        torch.testing.assert_close(a.matrix[:grid.active_count, absorbed], a.rewards[:grid.active_count, 0],
                                   atol=3e-14, rtol=2e-13)











if __name__ == "__main__":
    unittest.main()
