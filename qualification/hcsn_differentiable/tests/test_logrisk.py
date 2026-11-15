"""First-order FP64 log-risk against an independent 80-digit reference."""

import math
import unittest

import mpmath as mp
import torch

from qualification.hcsn_differentiable.operator import _first_hit, _first_hit_logprob


def reference(x, time, mu, sigma, discount=None):
    """Reflection formula evaluated without Torch or its numerical primitive."""
    x, time, mu, sigma = (mp.mpf(v) for v in (x, time, mu, sigma))
    root = (
        mu
        if discount is None
        else mp.sqrt(mu * mu + 2 * mp.mpf(discount) * sigma * sigma)
    )
    scale = sigma * mp.sqrt(time)

    def cdf(z):
        return mp.erfc(-z / mp.sqrt(2)) / 2

    if discount is None:
        mass = cdf((-x - root * time) / scale) + mp.exp(-2 * mu * x / sigma**2) * cdf(
            (-x + root * time) / scale
        )
    else:
        mass = mp.exp((root - mu) * x / sigma**2) * cdf(
            (-x - root * time) / scale
        ) + mp.exp(-(root + mu) * x / sigma**2) * cdf((-x + root * time) / scale)
    return mp.log(mass)


class LogRiskTests(unittest.TestCase):
    def test_log_probability_and_gradients_at_rare_and_boundary_states(self):
        fixtures = (
            (1.0, 1e-4, 0.2, 0.1),
            (1e-6, 0.1, -0.799, 0.10001),
            (0.15, 0.037, -0.12, 0.35),
            (0.15, 0.1, -1e-10, 0.35),
            (0.15, 0.1, 0.0, 0.35),
            (0.15, 0.1, 1e-10, 0.35),
            (3.0, 100.0, 0.799, 0.10001),
        )
        evidence = []
        with mp.workdps(80):
            for fixture in fixtures:
                for discount in (None, 0.001, 0.3):
                    raw = fixture if discount is None else (*fixture, discount)
                    values = [
                        torch.tensor(v, dtype=torch.float64, requires_grad=True)
                        for v in raw
                    ]
                    actual = _first_hit_logprob(*values)
                    expected = reference(*raw)
                    derivatives = torch.autograd.grad(actual, values)
                    errors = []
                    for index, derivative in enumerate(derivatives):
                        args = [mp.mpf(v) for v in raw]

                        def varied(value):
                            changed = list(args)
                            changed[index] = value
                            return reference(*changed)

                        exact = mp.diff(varied, args[index])
                        scaled_error = abs(float(derivative) - float(exact)) / max(
                            1.0, abs(float(exact))
                        )
                        self.assertLess(
                            scaled_error,
                            3e-10,
                            (fixture, discount, index, derivative, exact),
                        )
                        errors.append(scaled_error)
                    log_error = abs(float(actual.detach()) - float(expected))
                    self.assertLess(log_error, 3e-10 + 5e-13 * abs(float(expected)))
                    evidence.append(
                        {
                            "arguments": raw,
                            "log_probability": float(actual.detach()),
                            "reference_log_probability": float(expected),
                            "log_absolute_error": log_error,
                            "maximum_scaled_gradient_error": max(errors),
                        }
                    )
        self.numerical_evidence = {
            "reference_digits": 80,
            "fixtures": evidence,
            "scope": "sampled scalar first-hit log F/G; first-order AD only",
        }

    def test_underflow_does_not_erase_log_gradient(self):
        x = torch.tensor(1.0, dtype=torch.float64, requires_grad=True)
        time, mu, sigma = [x.new_tensor(v) for v in (1e-4, 0.2, 0.1)]
        probability = _first_hit(x, time, mu, sigma)
        log_probability = _first_hit_logprob(x, time, mu, sigma)
        self.assertEqual(float(probability.detach()), 0.0)
        self.assertTrue(bool(torch.isfinite(log_probability)))
        self.assertLess(
            float(log_probability.detach()), math.log(torch.finfo(torch.float64).tiny)
        )
        self.assertLess(float(torch.autograd.grad(log_probability, x)[0]), -1e5)

    def test_nonpositive_deadlines_have_zero_probability_and_gradient(self):
        x = torch.tensor(0.2, dtype=torch.float64, requires_grad=True)
        times = torch.tensor([-1.0, 0.0, 0.1], dtype=torch.float64)
        mu, sigma = x.new_tensor(-0.12), x.new_tensor(0.35)
        logs = _first_hit_logprob(x, times, mu, sigma)
        probabilities = _first_hit(x, times, mu, sigma)
        self.assertTrue(bool(torch.isneginf(logs[:2]).all()))
        torch.testing.assert_close(
            probabilities[:2], torch.zeros(2, dtype=torch.float64), atol=0, rtol=0
        )
        self.assertEqual(float(torch.autograd.grad(probabilities[:2].sum(), x)[0]), 0.0)


if __name__ == "__main__":
    unittest.main()
