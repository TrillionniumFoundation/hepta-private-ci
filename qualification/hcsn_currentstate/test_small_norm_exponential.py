"""Stored high-precision matrices and analytic value/gradient/Hessian controls."""

from pathlib import Path
import unittest

import numpy as np
import torch

from .differentiable import Work


HERE = Path(__file__).resolve().parent


class SmallNormExponentialTests(unittest.TestCase):
    def test_preserved_problem_matrices_against_mp80(self):
        path = HERE / "small_norm_exponential_20261119/diagnostic/attempt001/MATRICES.npz"
        with np.load(path, allow_pickle=False) as saved:
            old_error = new_error = 0.
            work = Work()
            for index in range(11):
                matrix = torch.from_numpy(saved[f"matrix_{index}_input"])
                reference = torch.from_numpy(saved[f"matrix_{index}_mp80_rounded"])
                result = work.exponential(matrix)
                new_error = max(new_error, float((result-reference).abs().max()))
                old_error = max(old_error, float(np.max(np.abs(
                    saved[f"matrix_{index}_torch"]-saved[f"matrix_{index}_mp80_rounded"]))))
            self.assertGreater(old_error, 1e-11)
            self.assertLessEqual(new_error, 3e-16)
            self.assertEqual((work.exponentials, work.small_norm_exponentials,
                              work.native_exponentials), (11, 4, 7))

    def test_horner_and_native_boundary_with_two_derivatives(self):
        for value in (.0999/3, .1/3, .1001/3):
            with self.subTest(value=value):
                theta = torch.tensor(value, dtype=torch.float64, requires_grad=True)
                matrix = theta*theta.new_tensor([[-1., 1.], [0., -2.]])
                work = Work()
                actual = work.exponential(matrix)
                first, second = torch.exp(-theta), torch.exp(-2*theta)
                expected = torch.stack((torch.stack((first, first-second)),
                                        torch.stack((theta*0., second))))
                torch.testing.assert_close(actual, expected, atol=3e-16, rtol=2e-15)
                weights = theta.new_tensor([[.3, -.7], [.2, .9]])
                observed_gradient, = torch.autograd.grad((actual*weights).sum(), (theta,), create_graph=True)
                exact_gradient, = torch.autograd.grad((expected*weights).sum(), (theta,), create_graph=True)
                observed_hessian, = torch.autograd.grad(observed_gradient, (theta,))
                exact_hessian, = torch.autograd.grad(exact_gradient, (theta,))
                torch.testing.assert_close(observed_gradient, exact_gradient, atol=3e-15, rtol=3e-15)
                torch.testing.assert_close(observed_hessian, exact_hessian, atol=3e-14, rtol=3e-14)
                self.assertEqual(work.exponentials, 1)
                self.assertEqual(work.small_norm_exponentials, int(float(matrix.detach().abs().sum(0).max()) <= .1))

    def test_fp32_retains_native_path(self):
        matrix = torch.tensor([[-.017, .017], [0., 0.]], dtype=torch.float32)
        work = Work()
        torch.testing.assert_close(work.exponential(matrix), torch.matrix_exp(matrix), atol=0, rtol=0)
        self.assertEqual((work.small_norm_exponentials, work.native_exponentials), (0, 1))


if __name__ == "__main__":
    torch.set_num_threads(1)
    unittest.main()
