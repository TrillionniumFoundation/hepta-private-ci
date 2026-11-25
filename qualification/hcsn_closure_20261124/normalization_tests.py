"""Numerical contracts of the explicit conditional-Poisson variant."""

import unittest
import torch

from .fast_kernel import scripted_action
from .normalized_uniformization import normalized_action


class NormalizationTests(unittest.TestCase):
    def test_constant_terms_are_exactly_preserved_in_fp32(self):
        matrix = torch.zeros(3, 3, dtype=torch.float32)
        vectors = torch.tensor([[.125, .25, .625]], dtype=torch.float32)
        rate = torch.tensor(15., dtype=torch.float32)
        value = vectors
        for _ in range(512):
            value = normalized_action(matrix, value, rate, .25, False, 1, 30)
        self.assertTrue(torch.equal(value, vectors))
        original = scripted_action(matrix, vectors, rate, .25, False, 1, 30)
        self.assertFalse(torch.equal(original, vectors))

    def test_matches_conditional_mixture_not_posthoc_population_repair(self):
        matrix = torch.tensor([[-2., 2.], [3., -3.]], dtype=torch.float64,
                              requires_grad=True)
        vectors = torch.tensor([[.7, .3], [-.4, .2]], dtype=torch.float64)
        rate = torch.tensor(5., dtype=torch.float64)
        for column in (False, True):
            values = vectors.T if column else vectors
            transition = torch.eye(2, dtype=matrix.dtype)+matrix/rate
            term, weight = values, torch.exp(-rate*.25)
            total, cumulative = weight*term, weight
            for k in range(1, 4):
                term = transition@term if column else term@transition
                weight = weight*(rate*.25)/k
                total, cumulative = total+weight*term, cumulative+weight
            expected = total/cumulative
            actual = normalized_action(matrix, values, rate, .25, column, 1, 3)
            torch.testing.assert_close(actual, expected, atol=3e-16, rtol=3e-16)
            a = torch.autograd.grad(actual.square().sum(), matrix, retain_graph=True)[0]
            b = torch.autograd.grad(expected.square().sum(), matrix, retain_graph=True)[0]
            torch.testing.assert_close(a, b, atol=1e-15, rtol=1e-14)

    def test_augmented_reward_and_parameter_gradient_against_dense(self):
        theta = torch.tensor(.3, dtype=torch.float64, requires_grad=True)
        zero = theta*0
        matrix = torch.stack((torch.stack((-theta, theta, theta)),
                              torch.stack((theta*2, -theta*2, zero)),
                              torch.stack((zero, zero, zero))))
        vectors = torch.tensor([[.75, .25, 0.]], dtype=torch.float64)
        rate = torch.tensor(1., dtype=torch.float64)
        actual = normalized_action(matrix, vectors, rate, .7, False, 1, 20)
        expected = vectors@torch.matrix_exp(.7*matrix)
        torch.testing.assert_close(actual, expected, atol=1e-13, rtol=1e-13)
        a = torch.autograd.grad(actual.square().sum(), theta, retain_graph=True)[0]
        b = torch.autograd.grad(expected.square().sum(), theta)[0]
        torch.testing.assert_close(a, b, atol=1e-13, rtol=1e-13)


if __name__ == "__main__":
    unittest.main()
