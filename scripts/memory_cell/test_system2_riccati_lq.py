"""Exact LQ special cases, not generic NDU or language-task qualification."""

from dataclasses import replace
import itertools
from pathlib import Path
import sys
import unittest

import torch

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "codex-rs/hepta-ndu/research")
)
from finite_tree_bsde import Profile, recursive_utility, solve_path
from riccati_lq import Problem, deterministic_cost, hamiltonian, riccati, trajectory


def scalar(t=4, noise=0.0):
    return Problem(
        *(torch.full((t, 1, 1), x, dtype=torch.float64) for x in (1.0, 1.0, 1.0, 1.0)),
        torch.ones(1, 1, dtype=torch.float64),
        torch.full((t, 1, 1), noise, dtype=torch.float64),
    )


class RiccatiTests(unittest.TestCase):
    def test_scalar_hamiltonian_and_value_agree(self):
        for t in (1, 4, 12):
            problem = scalar(t)
            initial = torch.tensor([1.3], dtype=torch.float64)
            p, k, c, _ = riccati(problem)
            x, u = trajectory(problem, initial, k)
            xx, uu, _ = hamiltonian(problem, initial)
            torch.testing.assert_close(x, xx, atol=1e-11, rtol=0)
            torch.testing.assert_close(u, uu, atol=1e-11, rtol=0)
            self.assertAlmostEqual(
                deterministic_cost(problem, x, u),
                0.5 * float(initial @ p[0] @ initial) + c[0],
            )

    def test_time_varying_multidimensional_problem(self):
        rng = torch.Generator().manual_seed(4)
        t, n, m = 5, 3, 2
        problem = Problem(
            0.2 * torch.randn(t, n, n, generator=rng, dtype=torch.float64),
            torch.randn(t, n, m, generator=rng, dtype=torch.float64),
            torch.eye(n, dtype=torch.float64).repeat(t, 1, 1),
            torch.eye(m, dtype=torch.float64).repeat(t, 1, 1),
            torch.eye(n, dtype=torch.float64),
            torch.zeros(t, n, 1, dtype=torch.float64),
        )
        initial = torch.tensor([1.0, -2.0, 3.0], dtype=torch.float64)
        _, k, _, _ = riccati(problem)
        x, u = trajectory(problem, initial, k)
        xx, uu, _ = hamiltonian(problem, initial)
        torch.testing.assert_close(x, xx, atol=1e-10, rtol=0)
        torch.testing.assert_close(u, uu, atol=1e-10, rtol=0)

    def test_same_gains_reused_for_different_initial_states(self):
        problem = scalar()
        _, gains, _, _ = riccati(problem)
        for value in (-3.0, 0.0, 2.0):
            x = torch.tensor([value], dtype=torch.float64)
            self.assertTrue(
                torch.allclose(
                    trajectory(problem, x, gains)[1], hamiltonian(problem, x)[1]
                )
            )

    def test_additive_noise_exact_finite_scenario_expectation(self):
        problem = scalar(4, 0.2)
        initial = torch.tensor([1.3], dtype=torch.float64)
        p, k, c, _ = riccati(problem)
        outcomes = []
        for signs in itertools.product((-1, 1), repeat=4):
            x, loss = initial.clone(), 0.0
            for j, sign in enumerate(signs):
                u = -k[j] @ x
                loss += 0.5 * float(x @ problem.Q[j] @ x + u @ problem.R[j] @ u)
                x = problem.A[j] @ x + problem.B[j] @ u + problem.S[j, :, 0] * sign
            outcomes.append(loss + 0.5 * float(x @ problem.G @ x))
        self.assertAlmostEqual(
            sum(outcomes) / 16, 0.5 * float(initial @ p[0] @ initial) + c[0], places=11
        )
        zero = replace(problem, S=torch.zeros_like(problem.S))
        self.assertTrue(all(torch.equal(a, b) for a, b in zip(k, riccati(zero)[1])))
        self.assertGreater(c[0], 0)
        with self.assertRaises(ValueError):
            hamiltonian(problem, initial)

    def test_bad_profiles_rejected(self):
        p = scalar()
        for bad in (
            replace(p, R=-p.R),
            replace(p, Q=-p.Q),
            replace(p, A=p.A.float()),
            replace(p, B=p.B[:-1]),
            replace(p, G=p.G * float("nan")),
        ):
            with self.assertRaises(ValueError):
                riccati(bad)

    def test_existing_coupled_fbsde_matches_affine_riccati_boundary(self):
        profile = Profile(
            horizon=0.3,
            sigma=0.05,
            coupling=0.05,
            rho=0,
            risk=0,
            cost=0,
            iterations=64,
            tolerance=1e-7,
        )
        initial = torch.tensor([0.2], dtype=torch.float64)
        out = solve_path(
            torch.zeros(3, 1, dtype=torch.float64),
            initial,
            lambda h, a: h,
            lambda h: h[0] + 0.5,
            profile,
            lambda *_: None,
        )
        p, b = 1.0, 0.5
        for _ in range(3):
            den = 1 - 0.05 * 0.1 * p
            p, b = p / den, b / den
        self.assertTrue(out.converged)
        self.assertAlmostEqual(out.value, p * 0.2 + b, places=6)

    def test_discount_recursion_cannot_change_equal_length_ranking(self):
        endpoints = [0.2, 0.6, 0.8]
        values = [
            recursive_utility([-0.02 * 0.1 / 1.01] * 3, [1 / 1.01] * 3, x)[0]
            for x in endpoints
        ]
        self.assertEqual(
            sorted(range(3), key=values.__getitem__),
            sorted(range(3), key=endpoints.__getitem__),
        )
        flat = [
            recursive_utility([-0.02 * 0.1 / 1.01] * d, [1 / 1.01] * d, 0.5)[0]
            for d in (1, 2, 3)
        ]
        self.assertGreater(0.5, flat[0])
        self.assertGreater(flat[0], flat[1])
        self.assertGreater(flat[1], flat[2])


if __name__ == "__main__":
    unittest.main()
