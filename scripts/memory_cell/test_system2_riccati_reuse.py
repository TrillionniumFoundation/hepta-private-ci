"""Shared-preparation numerics, not learned Cell or production qualification."""

from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import torch

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "codex-rs/hepta-ndu/research")
)
from riccati_lq import Problem, deterministic_cost, hamiltonian
from riccati_reuse import BACKENDS, apply, prepare, seal


def problem(noise=0.0):
    t, n, m = 3, 2, 1
    return Problem(
        0.8 * torch.eye(n, dtype=torch.float64).repeat(t, 1, 1),
        torch.ones(t, n, m, dtype=torch.float64),
        torch.eye(n, dtype=torch.float64).repeat(t, 1, 1),
        torch.eye(m, dtype=torch.float64).repeat(t, 1, 1),
        2 * torch.eye(n, dtype=torch.float64),
        torch.full((t, n, 1), noise, dtype=torch.float64),
    )


class SharedRiccatiTests(unittest.TestCase):
    def test_multiple_rhs_equals_individual_solves_with_one_factorization(self):
        p = problem()
        initials = torch.tensor(
            [[1.0, 2.0, -3.0], [2.0, 0.0, 1.0]], dtype=torch.float64
        )
        with patch("riccati_lq.torch.linalg.solve", wraps=torch.linalg.solve) as solver:
            x, u, _ = hamiltonian(p, initials)
            self.assertEqual(solver.call_count, 1)
        for i in range(initials.shape[1]):
            xx, uu, _ = hamiltonian(p, initials[:, i])
            torch.testing.assert_close(x[:, :, i], xx, atol=1e-11, rtol=0)
            torch.testing.assert_close(u[:, :, i], uu, atol=1e-11, rtol=0)

    def test_batch_backends_match_full_paths_and_actual_cost(self):
        p = problem()
        initials = torch.tensor(
            [[1.0, 2.0], [-1.0, 0.0], [0.0, 0.0]], dtype=torch.float64
        )
        outputs = [apply(p, prepare(p, key)[0], initials) for key in BACKENDS]
        for a, b in zip(*outputs, strict=True):
            torch.testing.assert_close(a, b, atol=1e-11, rtol=0)
        x, u, values = outputs[0]
        for i in range(len(initials)):
            self.assertAlmostEqual(deterministic_cost(p, x[i], u[i]), float(values[i]))

    def test_cached_application_never_reenters_a_solver(self):
        p = problem()
        for key in BACKENDS:
            cache, _ = prepare(p, key)
            with (
                patch(
                    "riccati_reuse.riccati", side_effect=AssertionError("recomputed")
                ),
                patch(
                    "riccati_reuse.hamiltonian",
                    side_effect=AssertionError("recomputed"),
                ),
            ):
                apply(p, cache, torch.ones(16, 2, dtype=torch.float64))

    def test_changed_coefficients_or_cache_are_rejected(self):
        p = problem()
        for key in BACKENDS:
            cache, _ = prepare(p, key)
            with self.assertRaises(ValueError):
                apply(
                    replace(p, G=p.G + torch.eye(2, dtype=torch.float64)),
                    cache,
                    torch.ones(1, 2, dtype=torch.float64),
                )
            cache["p0"][0, 0] += 1
            with self.assertRaises(ValueError):
                apply(p, cache, torch.ones(1, 2, dtype=torch.float64))

    def test_identical_content_copies_can_share_but_profiles_cannot(self):
        p = problem()
        copy = replace(p, A=p.A.clone(), B=p.B.clone())
        cache, _ = prepare(p, "riccati")
        x = torch.ones(1, 2, dtype=torch.float64)
        self.assertTrue(torch.equal(apply(p, cache, x)[0], apply(copy, cache, x)[0]))
        with self.assertRaises(ValueError):
            apply(replace(p, S=p.S + 0.1), cache, x)

    def test_noise_offset_preserved_and_dense_noise_rejected(self):
        p = problem(0.2)
        cache, _ = prepare(p, "riccati")
        _, _, values = apply(p, cache, torch.zeros(1, 2, dtype=torch.float64))
        self.assertGreater(float(values[0]), 0.0)
        with self.assertRaises(ValueError):
            prepare(p, "dense_map")

    def test_batches_do_not_change_controller_storage_or_content(self):
        p = problem()
        for key in BACKENDS:
            cache, receipt = prepare(p, key)
            before = seal(cache)
            for count in (1, 16, 256):
                apply(p, cache, torch.ones(count, 2, dtype=torch.float64))
                self.assertEqual(before, seal(cache))
                self.assertEqual(
                    receipt["tensor_payload_bytes"],
                    sum(
                        v.numel() * v.element_size()
                        for v in cache.values()
                        if isinstance(v, torch.Tensor)
                    ),
                )

    def test_invalid_initial_batch_and_unknown_backend_rejected(self):
        p = problem()
        cache, _ = prepare(p, "riccati")
        for x in (
            torch.ones(2),
            torch.ones(0, 2),
            torch.ones(257, 2),
            torch.ones(2, 3),
            torch.full((1, 2), float("nan")),
            torch.ones(1, 2, requires_grad=True),
        ):
            with self.assertRaises(ValueError):
                apply(p, cache, x)
        with self.assertRaises(ValueError):
            prepare(p, "unregistered")
        with self.assertRaises(ValueError):
            hamiltonian(p, torch.ones(2, 257, dtype=torch.float64))


if __name__ == "__main__":
    unittest.main()
