"""Explicit tests of the admitted projection and its derivative contract."""

import unittest
import torch

from qualification.hcsn_smallnet_20261124.model import ModelConfig
from .mass_projection import ProjectedUniformizedHCSN, project_joint


class ProjectionTests(unittest.TestCase):
    def test_refuses_large_defect_and_probability_violation(self):
        density = torch.tensor([[[.2, .3, .5], [.1, -.1, .2]]], dtype=torch.float64)
        hits = torch.tensor([[.3, .1]], dtype=torch.float64)
        scalar = torch.tensor([.2], dtype=torch.float64)
        with self.assertRaises(FloatingPointError):
            project_joint(density*(1+5e-6), hits, scalar, scalar, scalar)
        with self.assertRaises(FloatingPointError):
            project_joint(density, hits, scalar, scalar*2, scalar)

    def test_tangent_derivative_and_distinct_ambient_derivative(self):
        theta = torch.tensor(0., dtype=torch.float64, requires_grad=True)
        p = torch.stack((.2+theta, .3-theta, theta*0+.5))
        density = torch.stack((p, p*.3))[None]
        scalar = torch.tensor([.2], dtype=torch.float64)
        hits = torch.tensor([[.4, .1]], dtype=torch.float64)
        result, _ = project_joint(density, hits, scalar, scalar, scalar)
        tangent = torch.autograd.grad(result[0][0, 0, 0], theta)[0]
        self.assertEqual(float(tangent), 1.)
        independent = p.detach().clone().requires_grad_()
        density = torch.stack((independent, independent*.3))[None]
        result, _ = project_joint(density, hits, scalar, scalar, scalar)
        ambient = torch.autograd.grad(result[0][0, 0, 0], independent)[0]
        torch.testing.assert_close(ambient, torch.tensor([.8, -.2, -.2], dtype=torch.float64))

    def test_chunk_causality_gradients_and_raw_defect_accounting(self):
        torch.set_num_threads(1); torch.manual_seed(4711)
        model = ProjectedUniformizedHCSN(ModelConfig(neurons=8, message_mode="flow",
            precision="native32", backend="uniformized"), scripted=True)
        x = (torch.randn(12, 2, 6)*.2).requires_grad_()
        logits, _, final = model(x, return_features=True)
        self.assertEqual(model.last_diagnostics["projection_steps"], 12)
        self.assertLessEqual(model.last_diagnostics["raw_local_mass_defect_max"], 2e-6)
        self.assertGreater(model.last_diagnostics["probability_correction_l1_sum_of_step_maxima"], 0)
        first, _, middle = model(x[:5], return_features=True)
        last, _, resumed = model(x[5:], state=middle, return_features=True)
        torch.testing.assert_close(torch.cat((first, last)), logits, rtol=0, atol=0)
        torch.testing.assert_close(resumed.density, final.density, rtol=0, atol=0)
        changed = x.detach().clone(); changed[5:] += .7
        before = model(changed, return_features=True)[0][:5]
        torch.testing.assert_close(before, logits[:5], rtol=0, atol=0)
        logits.square().mean().backward()
        self.assertTrue(bool(torch.isfinite(x.grad).all()))
        self.assertGreater(float(x.grad.norm()), 0)


if __name__ == "__main__":
    unittest.main()
