"""Numerical derivative and cache-lifetime controls for the candidate kernel."""

import math
import unittest

import torch

from qualification.hcsn_smallnet_20261124.model import ModelConfig, _QVI
from .fast_kernel import FastSignedHCSN, NewtonQVI
from .models import SignedHCSN


class FastKernelTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(74123)

    def test_root_and_implicit_derivative_over_declared_domain(self):
        for dtype in (torch.float64, torch.float32):
            mu = torch.linspace(-.35, -.05, 17, dtype=dtype)[:, None, None].expand(17, 7, 5).clone().requires_grad_()
            cost = torch.linspace(.13, .17, 7, dtype=dtype)[None, :, None].expand_as(mu).clone().requires_grad_()
            absolute = torch.linspace(1.17, 1.23, 5, dtype=dtype)[None, None, :].expand_as(mu).clone().requires_grad_()
            eta = math.exp(-3*math.log1p(.3*.2/3))
            args = (mu, cost, absolute, .55, .3, eta, .8, .25)
            old, new = _QVI.apply(*args), NewtonQVI.apply(*args)
            tolerance = 2e-12 if dtype == torch.float64 else 3e-6
            torch.testing.assert_close(new, old, atol=tolerance, rtol=tolerance)
            weight = torch.linspace(-1, 1, old.numel(), dtype=dtype).reshape_as(old)
            left = torch.autograd.grad((old*weight).sum(), (mu, cost, absolute))
            right = torch.autograd.grad((new*weight).sum(), (mu, cost, absolute))
            for a, b in zip(left, right):
                torch.testing.assert_close(a, b, atol=tolerance*4, rtol=tolerance*4)

    def test_newton_gradient_matches_finite_difference(self):
        c = ModelConfig(precision="float64")
        mu = torch.tensor([-.28, -.12], dtype=torch.float64, requires_grad=True)
        cost = torch.tensor([.14, .16], dtype=torch.float64)
        eta = math.exp(-3*math.log1p(.3*.2/3))
        absolute = torch.tensor([1.18, 1.22], dtype=torch.float64)
        def value(v):
            return NewtonQVI.apply(v, cost, absolute, c.sigma, c.discount, eta, c.gain, c.maintenance)
        derivative = torch.autograd.grad(value(mu).sum(), mu)[0]
        fd = (value(mu.detach()+1e-6)-value(mu.detach()-1e-6))/(2e-6)
        torch.testing.assert_close(derivative, fd, atol=1e-8, rtol=1e-8)

    def test_fp64_nominal_boundary_keeps_symmetric_remap_derivative(self):
        config = ModelConfig(precision="float64", message_mode="flow", backend="uniformized")
        original = SignedHCSN(config)
        candidate = FastSignedHCSN(config, scripted=True)
        candidate.load_state_dict(original.state_dict())
        x = torch.randn(12, 2, 6, dtype=torch.float64)*.3
        gradients = []
        for model in (original, candidate):
            data = x.clone().requires_grad_()
            model(data).square().mean().backward()
            gradients.append(torch.cat([p.grad.flatten() for p in model.parameters() if p.grad is not None]+[data.grad.flatten()]))
        torch.testing.assert_close(gradients[0], gradients[1], atol=2e-11, rtol=1e-8)

    def test_cached_and_scripted_full_forward_backward(self):
        config = ModelConfig(precision="mixed", message_mode="flow", backend="uniformized")
        original = SignedHCSN(config)
        x = torch.randn(7, 2, 6)*.3
        for scripted in (False, True):
            candidate = FastSignedHCSN(config, scripted=scripted)
            candidate.load_state_dict(original.state_dict())
            outputs, gradients = [], []
            for model in (original, candidate):
                model.zero_grad(set_to_none=True)
                data = x.clone().requires_grad_()
                logits, features, state = model(data, return_features=True)
                (logits.square().mean()+.001*features.square().mean()).backward()
                outputs.append((logits.detach(), features.detach(), state))
                gradients.append(([p.grad.clone() for p in model.parameters() if p.grad is not None], data.grad))
            for a, b in zip(outputs[0][:2], outputs[1][:2]):
                torch.testing.assert_close(a, b, atol=2e-6, rtol=2e-6)
            for key in ("density", "boundary", "drift", "cost", "message"):
                torch.testing.assert_close(getattr(outputs[0][2], key), getattr(outputs[1][2], key), atol=2e-10, rtol=2e-10)
            for a, b in zip(gradients[0][0]+[gradients[0][1]], gradients[1][0]+[gradients[1][1]]):
                torch.testing.assert_close(a, b, atol=3e-6, rtol=3e-5)
            self.assertIsNone(candidate._interval)

    def test_chunk_boundary_and_optimizer_change_do_not_reuse_stale_graph(self):
        config = ModelConfig(precision="mixed", message_mode="flow", backend="uniformized")
        model = FastSignedHCSN(config)
        x = torch.randn(8, 2, 6)*.3
        full, _, state = model(x, return_features=True)
        first, _, prefix = model(x[:3], return_features=True)
        second, _, resumed = model(x[3:], return_features=True, state=prefix)
        torch.testing.assert_close(torch.cat((first, second)), full, atol=0, rtol=0)
        torch.testing.assert_close(resumed.density, state.density, atol=0, rtol=0)
        optimizer = torch.optim.SGD(model.parameters(), lr=.01)
        for _ in range(2):
            optimizer.zero_grad(set_to_none=True)
            logits = model(x)
            logits.square().mean().backward()
            optimizer.step()
            self.assertIsNone(model._interval)
        self.assertGreater(float((model(x)-full.detach()).abs().max()), 0.)


if __name__ == "__main__":
    unittest.main()
