"""Independent physical-time and complete boundary-chain checks for mechanism A."""

from dataclasses import replace
import importlib.util
import unittest

TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None
if TORCH_AVAILABLE:
    import numpy as np
    import torch
    from scipy.integrate import solve_ivp
    from ..cells import ValueKernelCell
    from ..stream_time import (stream_held_inputs, refinement_diagnostic,
                               boundary_gradient_diagnostic)


@unittest.skipUnless(TORCH_AVAILABLE, "PyTorch unavailable; no stream qualification claimed")
class StreamTimeTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(193)
        torch.set_num_threads(1)
        self.cell = ValueKernelCell(2, 2).double()
        self.inputs = torch.tensor([[[.3, -.2], [.6, .1], [-.2, .4]]], dtype=torch.float64)
        self.edges = (7., 7.25, 7.75, 8.5)

    def test_variable_intervals_match_original_cell_and_zero_duration_is_identity(self):
        edges = (0., .25, .25, 1.)
        expected = self.cell.initial_state(1, like=self.inputs)
        for value, left, right in zip(self.inputs.unbind(1), edges, edges[1:]):
            expected = self.cell.step(value, expected, right-left)
        actual = stream_held_inputs(self.cell, self.inputs, edges)
        torch.testing.assert_close(actual.state.memory, expected[0], rtol=0, atol=0)
        torch.testing.assert_close(actual.state.recovery, expected[1], rtol=0, atol=0)
        torch.testing.assert_close(actual.memory[:, 1], actual.memory[:, 0], rtol=0, atol=0)
        self.assertEqual(actual.times_seconds, edges[1:])

    def test_chunk_resume_matches_uninterrupted_stream_with_gradients(self):
        complete = stream_held_inputs(self.cell, self.inputs, self.edges, subdivisions=2)
        first = stream_held_inputs(self.cell, self.inputs[:, :1], self.edges[:2], subdivisions=2)
        last = stream_held_inputs(self.cell, self.inputs[:, 1:], self.edges[1:],
                                  initial_state=first.state, subdivisions=2)
        torch.testing.assert_close(last.state.memory, complete.state.memory, rtol=0, atol=0)
        torch.testing.assert_close(last.state.recovery, complete.state.recovery, rtol=0, atol=0)
        complete_gradient = torch.autograd.grad(complete.memory.square().sum(), self.cell.boundary_input.weight)[0]
        joined = torch.cat((first.memory, last.memory), 1)
        chunk_gradient = torch.autograd.grad(joined.square().sum(), self.cell.boundary_input.weight)[0]
        torch.testing.assert_close(chunk_gradient, complete_gradient, rtol=1e-12, atol=1e-14)

    def test_seconds_conversion_and_time_origin_do_not_change_dynamics(self):
        one = stream_held_inputs(self.cell, self.inputs, (0., .25, .75, 1.5), subdivisions=3)
        two = stream_held_inputs(self.cell, self.inputs, (40., 40.5, 41.5, 43.),
                                 seconds_per_model_time=2., subdivisions=3)
        torch.testing.assert_close(one.memory, two.memory, rtol=0, atol=0)
        torch.testing.assert_close(one.recovery, two.recovery, rtol=0, atol=0)

    def test_constant_vector_field_matches_independent_closed_solution(self):
        cell = ValueKernelCell(2, 2, recovery=False).double()
        with torch.no_grad():
            cell.candidate_memory.weight.zero_()
            cell.rate_features.zero_()
            cell.value_features.zero_()
        inputs = self.inputs[:, :1].expand(-1, 3, -1)
        target = torch.tanh(cell.candidate_input(inputs[:, 0]))
        rate = .1+4.9*torch.sigmoid(cell.rate_input(inputs[:, 0]))
        expected = target*(-torch.expm1(-rate*1.5))
        for factor in (1, 3, 8):
            trace = stream_held_inputs(cell, inputs, self.edges, subdivisions=factor)
            torch.testing.assert_close(trace.state.memory, expected, rtol=3e-14, atol=3e-15)

    def test_nonlinear_refinement_approaches_independent_ode_solver(self):
        cell = self.cell
        params = cell.financial_parameters()
        boundary = cell._base_boundary(params)
        state = np.zeros(4)
        expected = []
        with torch.no_grad():
            for value, left, right in zip(self.inputs.unbind(1), self.edges, self.edges[1:]):
                def rhs(t, y):
                    memory = torch.tensor(y[:2], dtype=torch.float64)[None]
                    recovery = torch.tensor(y[2:], dtype=torch.float64)[None]
                    feature = cell._features(value, memory, params, boundary)
                    rate = .1+4.9*torch.sigmoid(cell.rate_input(value)+(feature*cell.rate_features[:, None]).sum(0))
                    target = torch.tanh(cell.candidate_input(value)+cell.candidate_memory(memory)
                                        +(feature*cell.value_features[:, None]).sum(0)
                                        -torch.sigmoid(cell.recovery_strength)*recovery)
                    tau = .2+2.8*torch.sigmoid(cell.raw_recovery_time)
                    return torch.cat(((rate*(target-memory)).ravel(), ((memory.abs()-recovery)/tau).ravel())).numpy()
                solved = solve_ivp(rhs, (left, right), state, method="DOP853", rtol=1e-10, atol=1e-12)
                self.assertTrue(solved.success)
                state = solved.y[:, -1]
                expected.append(state.copy())
            target = torch.tensor(np.stack(expected), dtype=torch.float64)[None]
            errors = []
            for factor in (1, 2, 4, 8):
                trace = stream_held_inputs(cell, self.inputs, self.edges, subdivisions=factor)
                combined = torch.cat((trace.memory, trace.recovery), -1)
                errors.append(float((combined-target).square().mean().sqrt()))
        self.assertTrue(all(b < a for a, b in zip(errors, errors[1:])), errors)
        self.assertLess(errors[-1], errors[0]/5, errors)

    def test_complete_boundary_chain_matches_independent_parameter_perturbations(self):
        for parameter in self.cell.parameters():
            parameter.grad = torch.ones_like(parameter)
        saved = {name: parameter.detach().clone() for name, parameter in self.cell.named_parameters()}
        report = boundary_gradient_diagnostic(self.cell, self.inputs, self.edges, subdivisions=2)
        self.assertEqual(report['status'], 'passed', report)
        for name, parameter in self.cell.named_parameters():
            torch.testing.assert_close(parameter, saved[name], rtol=0, atol=0)
            torch.testing.assert_close(parameter.grad, torch.ones_like(parameter), rtol=0, atol=0)
        inactive = ValueKernelCell(2, 2, boundary='fixed', kernel='softplus').double()
        report = boundary_gradient_diagnostic(inactive, self.inputs, self.edges)
        self.assertEqual([row['status'] for row in report['rows']], ['inactive', 'inactive'])

    def test_readout_and_hidden_errors_are_distinct_metrics(self):
        report = refinement_diagnostic(self.cell, self.inputs, self.edges, factors=(1, 2, 4),
                                        readout=lambda value: 3*value)
        for row in report['rows'][1:]:
            self.assertTrue(row['finite'])
            self.assertAlmostEqual(row['terminal_prediction_rms_change'],
                                   3*row['terminal_memory_rms_change'], places=14)
        self.assertFalse(report['continuum_error_known'])
        self.assertIsNone(report['moving_boundary_first_passage_error'])

    def test_invalid_time_state_and_input_rejected_before_advancing(self):
        good = stream_held_inputs(self.cell, self.inputs, self.edges)
        for edges in ((0., .2, .1, 1.), (0., 1.), (0., .2, float('nan'), 1.)):
            with self.assertRaises(ValueError):
                stream_held_inputs(self.cell, self.inputs, edges)
        for state in (good.state, replace(good.state, time_seconds=7., seconds_per_model_time=2.),
                      replace(good.state, time_seconds=7., memory=good.state.memory+4)):
            with self.assertRaises(ValueError):
                stream_held_inputs(self.cell, self.inputs, self.edges, initial_state=state)
        for factor in (0, True, 1.5):
            with self.assertRaises(ValueError):
                stream_held_inputs(self.cell, self.inputs, self.edges, subdivisions=factor)
        for scale, subdivisions in ((1e300, 1), (1., 10**30)):
            with self.subTest(scale=scale, subdivisions=subdivisions), self.assertRaisesRegex(ValueError, "underflows"):
                stream_held_inputs(self.cell, self.inputs, (0., 1e-300, 2e-300, 3e-300),
                                   seconds_per_model_time=scale, subdivisions=subdivisions)
        with self.assertRaises(ValueError):
            stream_held_inputs(self.cell, self.inputs.float(), self.edges)
        with self.assertRaises(ValueError):
            refinement_diagnostic(self.cell, self.inputs, self.edges, factors=(1, 1))


if __name__ == '__main__':
    unittest.main()
