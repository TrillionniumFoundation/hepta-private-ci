"""Small CPU mechanism fixtures, not the frozen S81 fidelity or task study.

Every finite-difference check records its actual AD/FD values in the runner's
JSON through ``measurements``. The coarse 6/3 basis here establishes graph and
state semantics only; it does not inherit a 64/16 physical-fidelity result.
"""

import io
import copy
import math
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import torch

from qualification.hcsn_differentiable.contract import GridSpec
from qualification.hcsn_differentiable.network import ContinuousSpikingNetwork, IrregularHCSNEncoder
from qualification.hcsn_differentiable.operator import DifferentiableDistributionOperator


def mechanism_grid():
    return GridSpec(active_cells=6, phase_cells=3, quadrature_order=8)


def make_network():
    torch.manual_seed(1027)
    return ContinuousSpikingNetwork(3, content_dim=3, output_dim=1,
                                    layer_count=2, grid=mechanism_grid()).double()


def example():
    values = torch.tensor([
        [[.4, -.2, .7], [.1, .6, -.1], [-.3, .2, .5], [.8, -.1, .1], [.2, .9, -.4], [.6, .1, .2]],
        [[-.2, .5, .1], [.7, -.3, .4], [.2, .6, -.5], [.4, .3, .2], [-.1, .5, .8], [.9, -.2, .3]],
    ], dtype=torch.float64)
    dt = torch.tensor([[.04, .08, .035, .07, .06, .08],
                       [.03, .05, .075, .04, .065, .09]], dtype=torch.float64)
    return values, dt


def fresh_state(model, batch):
    # A short-distance initial prior exercises hits, refractory mass and release
    # within this bounded fixture; it is not the default network initial prior.
    return model.initial_state(batch, absolute_initial=math.exp(.18))


def task_loss(result):
    target = result.predictions.new_full((result.predictions.shape[0],), .3)
    return ((result.predictions[:, -1, 0] - target).square().mean()
            + .05 * result.predictions[:, -2, 0].square().mean())


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.measurements = {"scope": "coarse 6-active/3-phase mechanism fixture; no high-resolution fidelity credit"}
        self.model = make_network()
        self.features, self.dt = example()

    def assert_states_close(self, left, right, atol=2e-12, *, compare_position=True):
        self.assertEqual(len(left.layers), len(right.layers))
        if compare_position:
            self.assertEqual(left.sequence_position, right.sequence_position)
        self.assertEqual(left.truncate_every, right.truncate_every)
        self.assertEqual(left.configuration_snapshot, right.configuration_snapshot)
        torch.testing.assert_close(left.elapsed, right.elapsed, rtol=0, atol=atol)
        torch.testing.assert_close(left.steps, right.steps, rtol=0, atol=0)
        for lhs, rhs in zip(left.layers, right.layers):
            torch.testing.assert_close(lhs.probability, rhs.probability, rtol=0, atol=atol)
            torch.testing.assert_close(lhs.content_mass, rhs.content_mass, rtol=0, atol=atol)

    def objective(self):
        return task_loss(self.model(self.features, self.dt, state=fresh_state(self.model, 2)))

    def finite_difference(self, parameter, index=(), step=2e-5):
        original = parameter.detach().clone()
        try:
            with torch.no_grad():
                parameter[index] = original[index] + step
                plus = float(self.objective())
                parameter[index] = original[index] - step
                minus = float(self.objective())
            return (plus - minus) / (2 * step)
        finally:
            with torch.no_grad():
                parameter.copy_(original)

    def test_two_layers_all_four_physical_parameters_have_task_fd_gradients(self):
        self.objective().backward()
        rows = []
        self.measurements["physical_finite_differences"] = rows
        names = ("raw_mu", "raw_sigma", "raw_log_boundary", "raw_absolute_reset")
        for depth, layer in enumerate(self.model.layers):
            for name in names:
                parameter = getattr(layer.physics, name)
                ad = float(parameter.grad)
                fd = self.finite_difference(parameter)
                relative = abs(ad - fd) / max(abs(ad), abs(fd), 1e-12)
                rows.append(dict(layer=depth, parameter=name, raw_parameter_step=2e-5,
                                 autograd=ad, finite_difference=fd, absolute_error=abs(ad-fd),
                                 relative_error=relative))
                with self.subTest(layer=depth, parameter=name):
                    self.assertTrue(math.isfinite(ad) and math.isfinite(fd))
                    self.assertGreater(abs(ad), 1e-10)
                    self.assertGreater(abs(fd), 1e-10)
                    self.assertLess(relative, 3e-3)
                    self.assertLess(abs(ad - fd), 3e-7)

    def test_first_layer_content_parameter_reaches_final_task_loss(self):
        self.objective().backward()
        parameter = self.model.layers[0].content_proposal.weight
        ad = float(parameter.grad[0, 0])
        fd = self.finite_difference(parameter, (0, 0))
        relative = abs(ad - fd) / max(abs(ad), abs(fd), 1e-12)
        self.measurements["cross_layer_fd"] = dict(autograd=ad, finite_difference=fd,
                                                    relative_error=relative, raw_parameter_step=2e-5)
        self.assertGreater(abs(ad), 1e-8)
        self.assertLess(relative, 3e-3)


    def test_chunk_continuation_preserves_full_layer_content_and_clocks(self):
        whole = self.model(self.features, self.dt, state=fresh_state(self.model, 2))
        first = self.model(self.features[:, :3], self.dt[:, :3], state=fresh_state(self.model, 2))
        second = self.model(self.features[:, 3:], self.dt[:, 3:], state=first.state)
        torch.testing.assert_close(torch.cat((first.predictions, second.predictions), 1), whole.predictions,
                                   rtol=0, atol=2e-12)
        self.assert_states_close(second.state, whole.state)
        self.assertTrue(all(float(layer.content_mass.abs().sum()) > 0 for layer in second.state.layers))
        self.measurements["chunk_prediction_max_error"] = float((second.predictions-whole.predictions[:, 3:]).abs().max())












if __name__ == "__main__":
    unittest.main()
