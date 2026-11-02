"""Gradient, count-law and causal boundaries of the new historical candidate."""

import unittest
import numpy as np
import torch

from experiments.hcsn_v9_followup_20261101.refit_ablation.renewal_numpy import Physics, renewal_counts
from .models import Model, count_bank
from .history import HistoryModel


class AVChecks(unittest.TestCase):
    def test_independent_count_law_and_support(self):
        rng = np.random.default_rng(10183)
        parameters = rng.normal(size=(32, 5))
        dt = rng.uniform(0, 1, (32, 1))
        dt[0] = 0
        actual = count_bank(torch.tensor(parameters), torch.tensor(dt)).detach().numpy()
        for i, row in enumerate(parameters):
            z = 1 / (1 + np.exp(-row))
            physics = Physics(-(.2 + .8*z[1]), .2 + .45*z[2], .4 + .6*z[3], .16 + .12*z[4])
            expected, _ = renewal_counts(.15 + 1.2*z[0], dt[i, 0], physics, cap=10)
            np.testing.assert_allclose(actual[i], expected, atol=2e-13, rtol=0)
        np.testing.assert_array_equal(actual[0], np.r_[1., np.zeros(9)])

    def test_mean_preservation_and_single_support(self):
        p = torch.tensor([[.1, -.3, .4, -.5, .2]], dtype=torch.float64)
        dt = torch.ones((1, 1), dtype=torch.float64)
        full, mean, single = [count_bank(p, dt, mode) for mode in ("renewal", "mean", "single")]
        n = torch.arange(10, dtype=torch.float64)
        self.assertLess(float(((full - mean) @ n).abs().max()), 1e-12)
        self.assertEqual(float(single[:, 2:].sum()), 0.)
        self.assertEqual(float(single[0, 0]), float(full[0, 0]))

    def test_count_gradient_independent_finite_difference(self):
        p = torch.tensor([[.1, -.3, .4, -.5, .2]], dtype=torch.float64, requires_grad=True)
        dt = torch.ones((1, 1), dtype=torch.float64)
        weights = torch.arange(10, dtype=torch.float64).sin()
        score = (count_bank(p, dt) * weights).sum()
        score.backward()
        for k in range(5):
            plus, minus = p.detach().clone(), p.detach().clone()
            plus[0, k] += 1e-5
            minus[0, k] -= 1e-5
            finite = ((count_bank(plus, dt) - count_bank(minus, dt)) * weights).sum() / 2e-5
            self.assertAlmostEqual(float(finite), float(p.grad[0, k]), places=7)

    def test_prefix_and_readout_causality(self):
        torch.manual_seed(10189)
        x = torch.randn((2, 6, 41), dtype=torch.float64)
        x[:, :, -1] = torch.tensor([1., 0., 1., 0., 1., 0.])
        for family in ("direct", "gru", "ssm", "renewal", "mean", "single", "history"):
            model = HistoryModel() if family == "history" else Model(family, np.zeros(41), np.ones(41))
            before = model(x)
            for t in range(6):
                changed = x.clone()
                changed[:, t+1:] = 123.
                torch.testing.assert_close(before[:, t], model(changed)[:, t], atol=0, rtol=0)
            if family != "history":
                state = torch.randn((2, 32), dtype=torch.float64)
                changed = x[:, 0].clone()
                changed[:, -1] = 999.
                torch.testing.assert_close(model.predict(x[:, 0], state), model.predict(changed, state), atol=0, rtol=0)

    def test_joint_gradients_and_zero_time_assimilation(self):
        torch.manual_seed(10193)
        model = Model("renewal", np.zeros(41), np.ones(41))
        x = torch.randn((2, 6, 41), dtype=torch.float64)
        x[:, :, -1] = torch.tensor([1., 0., 1., 0., 1., 0.])
        model(x).square().mean().backward()
        for prefix in ("physics", "drive", "gain", "angle", "reader"):
            self.assertGreater(sum(float(p.grad.abs().sum()) for n, p in model.named_parameters() if n.startswith(prefix)), 0.)
        state = torch.randn((2, 32), dtype=torch.float64)
        a, b = x[:, 1].clone(), x[:, 1].clone()
        b[:, 0] += 1
        self.assertFalse(torch.equal(model.step(a, state), model.step(b, state)))


if __name__ == "__main__":
    torch.set_num_threads(1)
    unittest.main()
