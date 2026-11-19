"""Tensor parity, autograd and long-sequence mass checks (requires PyTorch)."""

import unittest
import numpy as np
from qualification.hcsn.population import Population, PopulationConfig
try:
    import torch
    from qualification.hcsn.population_torch import (
        TorchPopulation, _log_interval, _positive_difference, killed_transition)
except ModuleNotFoundError as exc:
    if exc.name != "torch":
        raise
    torch = None


@unittest.skipIf(torch is None, "PyTorch is not installed")
class TensorPopulationTests(unittest.TestCase):
    def test_empty_and_infinite_intervals_have_finite_backward(self):
        for dtype in (torch.float32, torch.float64):
            shift = torch.tensor(.2, dtype=dtype, requires_grad=True)
            left = torch.tensor([-torch.inf, -torch.inf, -torch.inf, -2., -1., 0., 8., 40.], dtype=dtype)
            right = torch.tensor([-torch.inf, torch.inf, -1., torch.inf, -1., 1., 8.3, 40.1], dtype=dtype)
            probability = _log_interval(left + shift, right + shift).exp()
            self.assertTrue(torch.isfinite(probability).all())
            self.assertEqual(float(probability[0]), 0.)
            self.assertEqual(float(probability[1]), 1.)
            self.assertEqual(float(probability[4]), 0.)
            probability.sum().backward()
            self.assertTrue(torch.isfinite(shift.grad))
        shift = torch.tensor(.2, dtype=torch.float64, requires_grad=True)
        self.assertTrue(torch.autograd.gradcheck(
            lambda s: _log_interval(left + s, right + s).exp(), (shift,), atol=1e-6))

    def test_zero_probability_difference_has_finite_backward(self):
        for dtype in (torch.float32, torch.float64):
            a = torch.tensor([-torch.inf, -1., -3.], dtype=dtype, requires_grad=True)
            b = torch.tensor([-torch.inf, -torch.inf, -4.], dtype=dtype, requires_grad=True)
            value = _positive_difference(a, b)
            expected = torch.tensor([0., np.exp(-1.), np.exp(-3.)-np.exp(-4.)], dtype=dtype)
            torch.testing.assert_close(value, expected)
            value.sum().backward()
            self.assertTrue(torch.isfinite(a.grad).all())
            self.assertTrue(torch.isfinite(b.grad).all())

    def test_large_finite_drift_tails_conserve_mass_and_have_finite_gradients(self):
        for dtype in (torch.float32, torch.float64):
            centres = torch.tensor([.1, .3, .5], dtype=dtype)
            edges = torch.tensor([0., .2, .4, .6], dtype=dtype)
            drift = torch.tensor([-40., 0., 40.], dtype=dtype, requires_grad=True)
            matrix, hit, escaped = killed_transition(centres, edges, drift, .05, .1)
            torch.testing.assert_close(matrix.sum(-1)+hit+escaped, torch.ones(3, dtype=dtype),
                                       atol=2e-5, rtol=2e-5)
            (matrix.sum()+2*hit.sum()+3*escaped.sum()).backward()
            self.assertTrue(torch.isfinite(drift.grad).all())

    def test_fp64_numpy_parity(self):
        cfg = PopulationConfig(bins=16, sigma=.3, leak=.8, x_max=2.4,
                               rest_margin=.6, reset_margin=.6, dt=.05)
        ref = Population(cfg)
        module = TorchPopulation(cfg, dtype=torch.float64)
        a, b = ref.initial_state((2,)), module.initial_state((2,))
        for k in range(30):
            drive = np.array([.7, 1.8]) if k < 20 else np.array([0., 0.])
            left, right = ref.step(a, drive), module(b, torch.from_numpy(drive))
            a, b = left.state, right.state
            for name in ("active", "refractory", "recovery", "escaped"):
                np.testing.assert_allclose(getattr(b, name).detach().numpy(), getattr(a, name),
                                           atol=2e-12, rtol=3e-10)
            np.testing.assert_allclose(right.rate.detach().numpy(), left.rate, atol=2e-12)

    def test_drift_gradient_matches_finite_difference(self):
        cfg = PopulationConfig(bins=8, sigma=.3, leak=.8, x_max=1.6,
                               rest_margin=.4, reset_margin=.4, dt=.1)
        module = TorchPopulation(cfg, dtype=torch.float64)
        state = module.initial_state((2,))
        def output(drive):
            local = state
            rates = []
            for _ in range(6):
                out = module(local, drive)
                local = out.state
                rates.append(out.rate)
            return torch.stack(rates)
        drive = torch.tensor([1.0, 1.3], dtype=torch.float64, requires_grad=True)
        self.assertTrue(torch.autograd.gradcheck(output, (drive,), eps=1e-6, atol=2e-6, rtol=2e-4))

    def test_fp32_mass_and_bptt_are_finite(self):
        cfg = PopulationConfig(bins=16, dt=.04, sigma=.25)
        module = TorchPopulation(cfg)
        state = module.initial_state((2,))
        drive = torch.tensor([2., 3.5], requires_grad=True)
        objective = 0.
        for _ in range(80):
            step = module(state, drive)
            state = step.state
            objective = objective + step.rate.sum()
            self.assertTrue(torch.isfinite(state.active).all())
        self.assertTrue(torch.allclose(state.total_mass(), torch.ones(2), atol=5e-5, rtol=0))
        objective.backward()
        self.assertTrue(torch.isfinite(drive.grad).all())
        self.assertGreater(float(drive.grad.abs().max()), 0.)


if __name__ == "__main__":
    unittest.main()
