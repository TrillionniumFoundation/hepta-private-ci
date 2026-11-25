"""Numerical and causal checks, independent of the downstream task labels."""

from dataclasses import replace
import unittest
import torch

from .model import ModelConfig, SmallHCSN


class KernelTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(3107)
        torch.set_num_threads(1)

    def test_true_population_axes_and_absolute_reset(self):
        for neurons in (8, 32, 64):
            model = SmallHCSN(ModelConfig(neurons=neurons))
            margin = torch.linspace(.27, .83, neurons, dtype=torch.float64)[None].expand(2, -1)
            state = model.initial_state(2, margin)
            x = torch.randn(4, 2, 6, dtype=torch.float64)*.4
            logits, features, end = model(x, return_features=True, state=state)
            self.assertEqual(tuple(end.density.shape), (2, neurons, 2, 10))
            self.assertEqual(tuple(features.shape), (4, 2, 5*(neurons//2)))
            self.assertEqual(tuple(logits.shape), (4, 2, 2))
            torch.testing.assert_close(end.density[..., 0, :].sum(-1), torch.ones(2, neurons, dtype=torch.float64), atol=2e-11, rtol=0)
            _, centers = model._geometry(end.boundary)
            deposit = model._deposit(model.reset_absolute-end.boundary)
            torch.testing.assert_close(end.boundary+(deposit*centers).sum(-1), model.reset_absolute.expand_as(end.boundary), atol=2e-13, rtol=0)
            self.assertGreater(float((end.density[0, :, 0]-end.density[1, :, 0]).abs().max()), 1e-7)

    def test_batching_and_complete_detached_continuation(self):
        model = SmallHCSN(ModelConfig(feature_normalization="population"))
        x = torch.randn(5, 2, 6, dtype=torch.float64)*.3
        joined, _, final = model(x, return_features=True)
        independent = torch.cat([model(x[:, i:i+1]) for i in range(2)], 1)
        torch.testing.assert_close(joined, independent, atol=3e-12, rtol=3e-12)
        first, _, middle = model(x[:3], return_features=True)
        second, _, cold = model(x[3:], state=middle.detach(), return_features=True)
        torch.testing.assert_close(joined, torch.cat((first, second)), atol=0, rtol=0)
        for name in ("density", "boundary", "drift", "cost", "message"):
            torch.testing.assert_close(getattr(final, name), getattr(cold, name), atol=0, rtol=0)

    def test_point_projection_center_first_moment_derivative(self):
        model = SmallHCSN(ModelConfig(bins=4))
        margin = torch.full((1, 8), .75, dtype=torch.float64, requires_grad=True)
        _, centers = model._geometry(margin)
        derivative = torch.autograd.grad((model._deposit(margin)*centers).sum(), margin)[0]
        torch.testing.assert_close(derivative, torch.ones_like(margin), atol=0, rtol=0)

    def test_receiver_has_no_direct_input_and_late_input_is_causal(self):
        model = SmallHCSN()
        x = torch.randn(6, 1, 6, dtype=torch.float64, requires_grad=True)*.4
        original = model(x)
        changed = x.detach().clone()
        changed[3, 0, 1] += 1.5
        altered = model(changed)
        torch.testing.assert_close(original[:4], altered[:4], atol=0, rtol=0)
        self.assertGreater(float((original[4:]-altered[4:]).abs().max()), 1e-8)
        early = torch.autograd.grad(original[0].sum(), x, retain_graph=True)[0]
        later = torch.autograd.grad(original[-1].sum(), x)[0]
        self.assertEqual(float(early.abs().max()), 0.)
        self.assertGreater(float(later[0].abs().max()), 1e-8)

    def test_frozen_semigroup_and_multiple_event_accounting(self):
        model = SmallHCSN(ModelConfig(dt=.5))
        half = SmallHCSN(replace(model.config, dt=.25))
        state = model.initial_state(1, torch.full((1, 8), .27, dtype=torch.float64))
        density = torch.stack((state.density[..., 0, :], .4*state.density[..., 0, :]), -2)
        generator, event = model._generator(state.drift, state.boundary)
        zero = density.new_zeros(1, 8, 2)
        one = model._flow(density, zero, generator, event, state.boundary, state.cost)
        left = half._flow(density, zero, generator, event, state.boundary, state.cost)
        right = half._flow(left[0], zero, generator, event, state.boundary, state.cost)
        torch.testing.assert_close(one[0], right[0], atol=2e-12, rtol=2e-12)
        torch.testing.assert_close(one[1], left[1]+right[1], atol=2e-12, rtol=2e-12)
        self.assertTrue(bool((one[1][..., 0] >= one[3]-1e-12).all()))
        self.assertTrue(bool(((one[3] >= 0) & (one[3] <= 1)).all()))

    def test_uniformization_forward_and_vjp(self):
        dense = SmallHCSN()
        sparse = SmallHCSN(replace(dense.config, backend="uniformized"))
        sparse.load_state_dict(dense.state_dict())
        x = torch.randn(3, 2, 6, dtype=torch.float64)*.3
        a = dense(x)
        b = sparse(x)
        torch.testing.assert_close(a, b, atol=3e-11, rtol=3e-11)
        ga = torch.autograd.grad(a.square().sum(), dense.recurrent.weight)[0]
        gb = torch.autograd.grad(b.square().sum(), sparse.recurrent.weight)[0]
        torch.testing.assert_close(ga, gb, atol=2e-9, rtol=2e-7)

    def test_actual_recurrent_and_boundary_gradients_against_fd(self):
        model = SmallHCSN(ModelConfig(feature_normalization="population"))
        # Ordinary derivatives are checked inside a differentiability stratum.
        with torch.no_grad():
            model.raw_cost.fill_(.23)
        x = torch.randn(4, 1, 6, dtype=torch.float64)*.4
        loss = model(x)[-1, 0, 0]
        ad = torch.autograd.grad(loss, (model.raw_cost, model.recurrent.weight))
        for parameter, index, derivative in ((model.raw_cost, (4,), ad[0][4]),
                                             (model.recurrent.weight, (4, 0), ad[1][4, 0])):
            original = float(parameter[index].detach())
            values = []
            for offset in (1e-5, -1e-5):
                with torch.no_grad():
                    parameter[index] = original+offset
                values.append(float(model(x)[-1, 0, 0].detach()))
            with torch.no_grad():
                parameter[index] = original
            fd = (values[0]-values[1])/2e-5
            self.assertGreater(abs(float(derivative)), 1e-9)
            self.assertLess(abs(fd-float(derivative)), 2e-6*max(1., abs(fd)))

    def test_coincident_grid_remap_generalized_derivative_and_mass(self):
        model = SmallHCSN()
        state = model.initial_state(1, torch.full((1, 8), .47, dtype=torch.float64))
        boundary = state.boundary.clone().requires_grad_()
        weights = torch.arange(6, dtype=torch.float64).square()
        def scores(b):
            density = model._remap(state, b)[0]
            return (density[0, 4, 0, :6]*weights).sum(), density[..., 0, :].sum()
        score, mass = scores(boundary)
        gradient = torch.autograd.grad(score, boundary, retain_graph=True)[0][0, 4]
        mass_gradient = torch.autograd.grad(mass, boundary)[0]
        epsilon = torch.zeros_like(boundary)
        epsilon[0, 4] = 1e-6
        left = (score-scores(boundary-epsilon)[0])/1e-6
        right = (scores(boundary+epsilon)[0]-score)/1e-6
        self.assertGreater(float((left-right).abs().detach()), 1.)
        torch.testing.assert_close(gradient, (left+right)/2, atol=2e-8, rtol=0)
        torch.testing.assert_close(mass_gradient, torch.zeros_like(mass_gradient), atol=2e-14, rtol=0)

    def test_mixed_precision_keeps_physical_state_double(self):
        model = SmallHCSN(ModelConfig(precision="mixed"))
        x = torch.randn(4, 2, 6, dtype=torch.float32)*.2
        output, features, state = model(x, return_features=True)
        self.assertEqual((output.dtype, features.dtype, state.density.dtype),
                         (torch.float32, torch.float32, torch.float64))
        output.square().sum().backward()
        for name in ("input_drive", "input_mark", "recurrent", "readout"):
            self.assertTrue(bool(torch.isfinite(getattr(model, name).weight.grad).all()))


if __name__ == "__main__":
    unittest.main()
