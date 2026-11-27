"""P1 diagnostic: second-order log first-hit sensitivity against an independent 80-digit oracle.

This probes FP64 autograd beyond the existing first-order fixture. It does NOT
certify all train-visited posteriors, the full network, or C2 science benefit.
"""
import math
import unittest

import mpmath as mp
import torch

from qualification.hcsn_differentiable.operator import _first_hit_logprob
from qualification.hcsn_differentiable.tests.test_logrisk import reference


class SecondOrderLogRiskTests(unittest.TestCase):
    def test_sigma_curvature_and_mu_sigma_cross_across_drift_regimes(self):
        # (distance, elapsed, drift, volatility, discount)
        cases = (
            (0.15, 0.1, -0.12, 0.35, 0.3),
            (0.15, 0.1, 0.0, 0.35, 0.3),
            (0.15, 0.1, 0.12, 0.35, 0.3),
            (1.0, 1e-4, 0.2, 0.1, 0.3),
            (1e-4, 0.01, 0.2, 0.1, 0.3),
            (0.15, 0.1, -0.12, 0.35, None),
            (0.15, 0.1, 0.0, 0.35, None),
            (1.0, 1e-4, 0.2, 0.1, None),
        )
        with mp.workdps(80):
            for data in cases:
                with self.subTest(data=data):
                    variables = tuple(torch.tensor(v, dtype=torch.float64, requires_grad=True)
                                      for v in data if v is not None)
                    log_hit = _first_hit_logprob(*variables)
                    grads = torch.autograd.grad(log_hit, variables, create_graph=True)
                    sigma_curvature = torch.autograd.grad(grads[3], variables[3],
                                                          retain_graph=True)[0]
                    mu_sigma = torch.autograd.grad(grads[2], variables[3],
                                                   retain_graph=True)[0]
                    reference_data = tuple(mp.mpf(v) if v is not None else None for v in data)
                    true_sigma = mp.diff(
                        lambda s: reference(*reference_data[:3], s, reference_data[4]),
                        reference_data[3], 2)
                    true_cross = mp.diff(
                        lambda m, s: reference(reference_data[0], reference_data[1],
                                               m, s, reference_data[4]),
                        (reference_data[2], reference_data[3]), (1, 1))
                    for name, actual, exact in (
                        ('sigma-sigma', sigma_curvature, true_sigma),
                        ('mu-sigma', mu_sigma, true_cross),
                    ):
                        self.assertTrue(math.isfinite(float(actual)), name)
                        scaled = abs(float(actual) - float(exact)) / max(1., abs(float(exact)))
                        self.assertLess(scaled, 2e-7, (name, data, actual, exact, scaled))


if __name__ == "__main__":
    unittest.main()
