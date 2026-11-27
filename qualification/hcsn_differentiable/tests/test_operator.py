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

    def _gradient_fixture(self, grid):
        operator = DifferentiableDistributionOperator(grid)
        initial_absolute = math.exp(0.29)
        base = torch.tensor([0.02, -0.25, 0.45, math.exp(0.18)], dtype=torch.float64)
        records = []
        self.numerical_evidence = {
            "grid": {"active": grid.active_cells, "phase": grid.phase_cells,
                     "K": grid.state_count, "quadrature": grid.quadrature_order},
            "physical_values": dict(zip(("log_boundary", "mu", "sigma", "absolute_reset"), base.tolist())),
            "dt": 0.08, "gradients": records, "old_S81_pass_credit": 0,
        }

        def loss(values):
            params = PhysicalParameters(values[0], values[1], values[2], values[3], values.new_tensor(0.2))
            prior = operator.initial_probability(values.new_tensor([initial_absolute]), params.log_boundary)
            phase = torch.zeros_like(prior)
            phase[0, grid.active_count] = 1.0
            # A valid mixed initial law exercises both active and immediate
            # refractory-release paths, including unquantized reset gradients.
            p = 0.65 * prior + 0.35 * phase
            weight = torch.linspace(-0.3, 0.9, grid.state_count, dtype=torch.float64)
            content = p[..., None] * torch.stack((weight, weight.square()), dim=-1)[None, ...]
            receipt = operator.advance(p, content, 0.08, params)
            return ((receipt.probability * weight).sum()
                    + 0.33 * (receipt.content_mass[..., 0] * weight).sum()
                    + 0.29 * receipt.expected_events.sum() + 0.41 * receipt.call.sum())

        differentiable = base.clone().requires_grad_()
        value = loss(differentiable)
        self.numerical_evidence["synthetic_loss"] = float(value.detach())
        ad = torch.autograd.grad(value, differentiable)[0].detach()
        self.numerical_evidence["all_ad_values"] = ad.tolist()
        for i, name in enumerate(("log_boundary", "mu", "sigma", "absolute_reset")):
            step = 2e-6 * max(1.0, abs(float(base[i])))
            plus, minus = base.clone(), base.clone()
            plus[i] += step
            minus[i] -= step
            with torch.no_grad():
                fd = float((loss(plus) - loss(minus)) / (2.0 * step))
            actual = float(ad[i])
            error = abs(actual - fd)
            relative = error / max(abs(actual), abs(fd), 1e-12)
            records.append({"parameter": name, "ad": actual, "central_fd": fd,
                            "fd_step": step, "absolute_error": error, "relative_error": relative})
        # Retain *all* measured AD/FD values before testing any numerical gate.
        for row in records:
            actual, fd, error, name = row["ad"], row["central_fd"], row["absolute_error"], row["parameter"]
            self.assertTrue(math.isfinite(actual))
            self.assertGreater(abs(actual), 1e-6, msg=f"{name} path must be materially exercised")
            self.assertLess(error, 2e-7 + 2e-5 * max(abs(actual), abs(fd)), msg=name)
        return self.numerical_evidence

    def test_all_four_physical_parameter_gradients_against_fd(self):
        self.numerical_evidence = self._gradient_fixture(GridSpec())

    def test_81_state_physical_gradient_fixture_is_new_evidence(self):
        self.numerical_evidence = self._gradient_fixture(GridSpec(active_cells=64, phase_cells=16,
                                                                 quadrature_order=16))
        self.numerical_evidence["old_S81_pass_credit"] = 0

    def test_quadrature_refinement_records_actual_table_discrepancy(self):
        records, tables = [], []
        # The continuous reset point is deliberately off the active-cell grid.
        params = _params(mu=-0.15, sigma=0.4, absolute_reset=math.exp(0.237))
        for order in (16, 32, 64):
            operator = DifferentiableDistributionOperator(GridSpec(quadrature_order=order))
            tables.append(self._table(operator, params=params, dt=0.073))
        for lo, hi, first, second in zip((16, 32), (32, 64), tables[:-1], tables[1:]):
            records.append({"orders": [lo, hi],
                            "max_row_l1": float((first.matrix - second.matrix).abs().sum(-1).max()),
                            "maximum_reward_difference": float((first.rewards - second.rewards).abs().max())})
        self.numerical_evidence = {"refinement": records, "claim": "observed quadrature agreement, not a certified error bound"}
        self.assertLess(records[-1]["max_row_l1"], 5e-4)
        self.assertLess(records[-1]["maximum_reward_difference"], 2e-5)

    def test_spatial_refinement_against_continuum_first_hit(self):
        mean, std, dt, steps = 0.25, 0.08, 0.075, 4
        params = _params(log_boundary=0.0, mu=-0.2, sigma=0.4)
        reference = _prior_hit_reference(mean, std, steps * dt, -0.2, 0.4)
        records = []
        for cells in (16, 32, 64):
            grid = GridSpec(active_cells=cells, phase_cells=16, quadrature_order=32, initial_log_std=std)
            operator = DifferentiableDistributionOperator(grid, reset_enabled=False)
            state = operator.initial_probability(torch.tensor(math.exp(mean), dtype=torch.float64), params.log_boundary)
            table = self._table(operator, params=params, dt=dt)
            for _ in range(steps):
                state = state @ table.matrix
            observed = float(state[grid.active_count])
            records.append({"active_cells": cells, "expected_first_hits": observed,
                            "absolute_error": abs(observed - reference)})
        self.numerical_evidence = {"continuum_reference": reference, "mu": -0.2, "sigma": 0.4,
                                   "initial_log_mean": mean, "initial_log_std": std,
                                   "elapsed": steps * dt, "steps": steps, "refinement": records}
        self.assertLess(records[-1]["absolute_error"], records[0]["absolute_error"])
        self.assertLess(records[-1]["absolute_error"], 0.01)

    def test_phase_projection_early_release_and_refinement_are_disclosed(self):
        # Start from one identical physical uniform remaining-time law [.06,.08]
        # at every resolution. Large reset distance makes another hit negligible.
        params = _params(log_boundary=0.0, mu=-0.1, sigma=0.15, absolute_reset=math.exp(1.0))
        dt, steps, lo, hi = 0.013, 6, 0.06, 0.08
        records = []
        for phases in (10, 20, 40, 80):
            grid = GridSpec(phase_cells=phases, quadrature_order=32)
            operator = DifferentiableDistributionOperator(grid)
            state = torch.zeros(grid.state_count, dtype=torch.float64)
            for j, (left, right) in enumerate(zip(grid.phase_edges[:-1], grid.phase_edges[1:])):
                state[grid.active_count + j] = max(0.0, min(hi, right) - max(lo, left)) / (hi - lo)
            table = self._table(operator, params=params, dt=dt)
            curve, errors = [], []
            for step in range(1, steps + 1):
                state = state @ table.matrix
                observed = float(state[:grid.active_count].sum())
                reference = max(0.0, min(1.0, (step * dt - lo) / (hi - lo)))
                curve.append({"elapsed": step * dt, "active_probability": observed,
                              "deterministic_release_reference": reference})
                errors.append(abs(observed - reference))
            records.append({"phase_cells": phases, "maximum_release_error": max(errors),
                            "early_release_at_0.052": curve[3]["active_probability"], "curve": curve})
        self.numerical_evidence = {"phase_projection": records,
                                   "warning": "QPR can release earlier through repeated phase projection; it is not exact per-path delay"}
        self.assertGreater(records[0]["early_release_at_0.052"], 0.0)
        self.assertLess(records[-1]["early_release_at_0.052"], 1e-12)
        self.assertLess(records[-1]["maximum_release_error"], records[0]["maximum_release_error"])
        self.assertLess(records[-1]["maximum_release_error"], 0.025)

    def test_stationary_rate_against_negative_drift_renewal_mean(self):
        params = _params(log_boundary=0.0, mu=-0.5, sigma=0.3, absolute_reset=math.exp(0.3))
        dt = 0.025
        reference = 1.0 / (0.1 + 0.3 / 0.5)
        records = []
        self.numerical_evidence = {"deterministic_renewal_reference": reference,
                                   "mu": -0.5, "sigma": 0.3, "reset_margin": 0.3,
                                   "fixed_delay": 0.1, "dt": dt, "refinement": records}
        for cells, phases in ((16, 8), (64, 16)):
            grid = GridSpec(active_cells=cells, phase_cells=phases, quadrature_order=32)
            operator = DifferentiableDistributionOperator(grid)
            table = self._table(operator, params=params, dt=dt)
            system = table.matrix.T - torch.eye(grid.state_count, dtype=torch.float64)
            system = system.clone()
            system[-1] = 1.0
            target = torch.zeros(grid.state_count, dtype=torch.float64)
            target[-1] = 1.0
            stationary = torch.linalg.solve(system, target)
            rate = float(stationary @ table.rewards[:, 0] / dt)
            balance = float((stationary @ table.matrix - stationary).abs().max())
            records.append({"active_cells": cells, "phase_cells": phases, "K": grid.state_count,
                            "rate": rate, "absolute_error": abs(rate - reference),
                            "relative_error": abs(rate - reference) / reference,
                            "stationarity_residual": balance,
                            "minimum_stationary_mass": float(stationary.min()),
                            "refractory_probability": float(stationary[grid.active_count:].sum())})
        for row in records:
            self.assertLess(row["stationarity_residual"], 2e-11)
            self.assertGreater(row["minimum_stationary_mass"], -1e-11)
        self.assertLess(records[-1]["relative_error"], 0.03)
        self.assertLess(records[-1]["absolute_error"], records[0]["absolute_error"] + 2e-4)

    def test_long_fixed_operator_conserves_mass_and_signed_content(self):
        # Numerical foundation only: no training, changing physics, observation
        # updates, or inference about a long-sequence neural-network advantage.
        grid = GridSpec(quadrature_order=32)
        operator = DifferentiableDistributionOperator(grid)
        params = _params(log_boundary=0.0, mu=-0.5, sigma=0.3, absolute_reset=math.exp(0.3))
        dt, count = 0.025, 4096
        checkpoints = []
        self.numerical_evidence = {"steps": count, "dt": dt, "elapsed": count * dt,
                                   "grid_K": grid.state_count, "checkpoints": checkpoints,
                                   "scope": "fixed numerical propagation only; no neural long-horizon superiority claim"}
        with torch.no_grad():
            table = self._table(operator, params=params, dt=dt)
            state = operator.initial_probability(torch.tensor(math.exp(0.35), dtype=torch.float64), params.log_boundary)
            coordinate = torch.linspace(0.0, 1.0, grid.state_count, dtype=torch.float64)
            signed_values = torch.stack((torch.sin(19.0 * coordinate),
                                         torch.cos(31.0 * coordinate),
                                         coordinate - 0.15), dim=-1)
            content = state[:, None] * signed_values
            initial_mass, initial_content = state.sum().clone(), content.sum(0).clone()
            cumulative_events = state.new_zeros(())
            maximum_mass_drift = 0.0
            maximum_content_error = 0.0
            for step in range(1, count + 1):
                cumulative_events = cumulative_events + state @ table.rewards[:, 0]
                state = state @ table.matrix
                content = table.matrix.T @ content
                if step in (1, 16, 256, 1024, count):
                    mass_drift = float((state.sum() - initial_mass).abs())
                    content_error = float((content.sum(0) - initial_content).abs().max())
                    maximum_mass_drift = max(maximum_mass_drift, mass_drift)
                    maximum_content_error = max(maximum_content_error, content_error)
                    checkpoints.append({"step": step, "mass_drift": mass_drift,
                                        "maximum_signed_content_total_error": content_error,
                                        "M_expected_cumulative_events": float(cumulative_events),
                                        "minimum_probability": float(state.min())})
            self.numerical_evidence.update(
                maximum_recorded_mass_drift=maximum_mass_drift,
                maximum_recorded_signed_content_total_error=maximum_content_error,
                initial_signed_content_totals=initial_content.tolist(),
                final_signed_content_totals=content.sum(0).tolist(),
                M_expected_cumulative_events=float(cumulative_events),
                average_event_rate_per_time_unit=float(cumulative_events) / (count * dt),
                final_minimum_probability=float(state.min()),
            )
        self.assertLess(maximum_mass_drift, 5e-10)
        self.assertLess(maximum_content_error, 5e-10)
        self.assertGreater(float(cumulative_events), 1.0)
        self.assertGreaterEqual(float(state.min()), 0.0)
        self.assertTrue(bool(torch.isfinite(content).all()))

    def test_projected_operator_does_not_claim_exact_semigroup(self):
        operator = DifferentiableDistributionOperator(GridSpec(quadrature_order=32))
        whole = self._table(operator, dt=0.08)
        half = self._table(operator, dt=0.04)
        error = float((whole.matrix - half.matrix @ half.matrix).abs().sum(-1).max())
        self.numerical_evidence = {"one_0.08_vs_two_0.04_max_row_l1": error,
                                   "interpretation": "finite-basis projection error, not an exact continuum semigroup"}
        self.assertTrue(math.isfinite(error))
        self.assertGreater(error, 1e-5)


if __name__ == "__main__":
    unittest.main()
