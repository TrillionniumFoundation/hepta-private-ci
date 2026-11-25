"""Direction, causal feedback, BP and full-state controls for dual forces."""

from dataclasses import replace
import unittest

import torch

from qualification.hcsn_smallnet_20261124.model import ModelConfig
from .dual_force import DualForceHCSN, DualState
from .models import SignedHCSN


class DualForceTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(76215)
        self.config = ModelConfig(message_mode="flow", backend="uniformized", precision="mixed")

    def test_zero_forces_reproduce_original_population_and_logits(self):
        original = SignedHCSN(self.config)
        dual = DualForceHCSN(self.config)
        dual.load_state_dict({**dual.state_dict(), **original.state_dict()})
        x = torch.randn(9, 2, 6)*.2
        left = original(x, return_features=True)
        right = dual(x, return_features=True)
        for a, b in zip(left[:2], right[:2]):
            torch.testing.assert_close(a, b, atol=0, rtol=0)
        for field in ("density", "boundary", "drift", "cost", "message"):
            torch.testing.assert_close(getattr(left[2], field), getattr(right[2], field), atol=0, rtol=0)

    def test_restoration_sign_and_reference_distribution(self):
        model = DualForceHCSN(self.config, call_gain=.5, panic_gain=.5)
        for margin, sign in ((.4, 1), (.7, 0), (1.3, -1)):
            state = model.initial_state(2, initial_margin=torch.full((2, 8), margin, dtype=torch.float64))
            restoring, panic = model.forces(state)
            if sign:
                self.assertTrue(bool((sign*restoring > 0).all()))
            else:
                torch.testing.assert_close(restoring, torch.zeros_like(restoring), atol=1e-15, rtol=0)
            torch.testing.assert_close(panic, torch.zeros_like(panic), atol=0, rtol=0)
        risk = torch.full_like(state.previous_risk, .4)
        _, panic = model.forces(DualState(state.population, risk))
        torch.testing.assert_close(panic, torch.full_like(panic, -.2), atol=0, rtol=0)

    def test_cell_integral_and_distribution_not_mean_closure(self):
        model = DualForceHCSN(self.config, call_gain=.5)
        point = model.initial_state(1, initial_margin=torch.full((1, 8), .7, dtype=torch.float64))
        low = model.initial_state(1, initial_margin=torch.full((1, 8), .35, dtype=torch.float64))
        high = model.initial_state(1, initial_margin=torch.full((1, 8), 1.05, dtype=torch.float64))
        density = (low.density+high.density)/2
        mixture = DualState(replace(point.population, density=density), point.previous_risk)
        # Equal mean margins, different distributional call-gradient moments.
        _, centers = model._geometry(point.drift)
        torch.testing.assert_close((point.density[..., 0, :6]*centers).sum(-1),
                                   (mixture.density[..., 0, :6]*centers).sum(-1), atol=1e-15, rtol=0)
        self.assertGreater(float((model.forces(point)[0]-model.forces(mixture)[0]).abs().max()), 1e-4)

    def test_feedback_changes_actual_law_and_obeys_causality(self):
        model = DualForceHCSN(self.config, call_gain=.5, panic_gain=.5)
        initial = model.initial_state(2)
        altered = DualState(initial.population, torch.full_like(initial.previous_risk, .5))
        x = torch.randn(7, 2, 6)*.2
        _, _, a = model(x[:1], return_features=True, state=initial)
        _, _, b = model(x[:1], return_features=True, state=altered)
        self.assertGreater(float((a.drift-b.drift).abs().max()), 1e-4)
        self.assertGreater(float((a.boundary-b.boundary).abs().max()), 1e-4)
        self.assertGreater(float((a.density-b.density).abs().max()), 1e-6)
        changed = x.clone()
        changed[4:] += .5
        torch.testing.assert_close(model(x)[:4], model(changed)[:4], atol=0, rtol=0)

    def test_full_state_chunking_gradient_and_long_conservation(self):
        model = DualForceHCSN(self.config, call_gain=.5, panic_gain=.5)
        x = (torch.randn(12, 2, 6)*.2).requires_grad_()
        full, _, state = model(x, return_features=True)
        a, _, prefix = model(x[:3], return_features=True)
        b, _, resumed = model(x[3:], return_features=True, state=prefix)
        torch.testing.assert_close(torch.cat((a, b)), full, atol=0, rtol=0)
        torch.testing.assert_close(resumed.previous_risk, state.previous_risk, atol=0, rtol=0)
        full.square().mean().backward()
        self.assertTrue(bool(torch.isfinite(x.grad).all()))
        self.assertGreater(float(x.grad.abs().sum()), 0.)
        parameter = model.input_drive.weight
        automatic = float(parameter.grad[0, 0])
        epsilon = .002
        with torch.no_grad():
            original = float(parameter[0, 0])
            parameter[0, 0] = original+epsilon
            plus = float(model(x.detach()).square().mean())
            parameter[0, 0] = original-epsilon
            minus = float(model(x.detach()).square().mean())
            parameter[0, 0] = original
            model(torch.randn(128, 1, 6)*.2)
        self.assertAlmostEqual(automatic, (plus-minus)/(2*epsilon), delta=3e-4)
        self.assertLess(model.last_diagnostics["mass_error"], 2e-9)


if __name__ == "__main__":
    unittest.main()
