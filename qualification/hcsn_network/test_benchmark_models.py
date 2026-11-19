"""Non-data controls for the shared benchmark and its delay approximation."""

import unittest

import numpy as np
from scipy.integrate import solve_ivp
import torch

from .benchmark_models import ARMS, make_model
from .phase_approximation import phase_transition
from .task_physics import task_physics


class ModelTests(unittest.TestCase):
    def test_all_models_batch_forward_backward_and_state_accounting(self):
        x = torch.linspace(-1, 1, 8*10*2, dtype=torch.float64).reshape(8, 10, 2)
        for arm in ARMS:
            with self.subTest(arm=arm):
                torch.manual_seed(101)
                model = make_model(arm)
                if arm.startswith("flow"):
                    model.capture_state = True
                logits = model(x)
                self.assertEqual(logits.shape, (8, 10))
                logits.square().mean().backward()
                self.assertTrue(all(p.grad is None or bool(torch.isfinite(p.grad).all())
                                    for p in model.parameters()))
                if arm.startswith("flow"):
                    self.assertLess(max(float(t.detach().abs().max())
                                        for t in model.last_state.balances()), 2e-11)
                    self.assertGreater(model.last_state_bytes, 0)

    def test_erlang_full_generator_against_independent_ode(self):
        theta = torch.tensor([-.2,.55,.3,1.2,.8,.25,.15], dtype=torch.float64)
        p = task_physics(theta).physics
        transition, integral, generator = phase_transition(p, .5, 4)
        initial = np.r_[p.reset.numpy(), np.zeros(5)]
        q, h = generator.numpy(), np.r_[p.lower.numpy(), np.zeros(5)]
        def rhs(_, y):
            return np.r_[y[:-1] @ q, y[:-1] @ h]
        reference = solve_ivp(rhs, [0,.5], np.r_[initial,0], method="DOP853", rtol=2e-12, atol=2e-13)
        self.assertTrue(reference.success)
        np.testing.assert_allclose(initial @ transition.numpy(), reference.y[:-1,-1],
                                   rtol=2e-10, atol=2e-12)
        self.assertLess(abs(initial @ integral.numpy()-reference.y[-1,-1]), 2e-12)
        self.assertLess(float(generator.sum(1).abs().max()), 2e-14)

    def test_actual_classifier_boundary_gradient(self):
        for arm in ("flow", "flow_erlang4"):
            model = make_model(arm)
            x = torch.linspace(-1,1,2*10*2,dtype=torch.float64).reshape(2,10,2)
            output = model(x).square().sum()
            derivative = torch.autograd.grad(output, model.raw_cost)[0]
            values = []
            for shift in [-1e-5,1e-5]:
                with torch.no_grad():
                    model.raw_cost.fill_(shift)
                    values.append(model(x).square().sum().item())
            numerical = (values[1]-values[0])/2e-5
            self.assertLess(abs(float(derivative)-numerical), 2e-7)


if __name__ == "__main__":
    unittest.main()
