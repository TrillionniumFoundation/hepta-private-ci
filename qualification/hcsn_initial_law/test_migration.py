from fractions import Fraction as F
import unittest

import numpy as np

from .migration import MigrationBasis, migrate


class TestMigration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.basis = MigrationBasis(4, 4, 1, F(1, 5), 4, 8, 32)
        cls.lift = cls.basis.lift()

    def test_no_lower_atom_exact_total_content_and_reported_boundary_bias(self):
        p = [F(1, 9)] * 9
        content = [(2 * x, -3 * x) for x in p]
        result = migrate(self.basis, p, content, lift=self.lift)
        self.assertEqual(result.active[0], 0)
        self.assertEqual(result.report["exact_input_mass"], "1")
        self.assertEqual(result.report["exact_output_mass"], "1")
        self.assertEqual(result.report["exact_output_content"], ["2", "-3"])
        bias = self.basis.spacing**2 / 2  # first old cell has width one
        self.assertEqual(
            F(result.report["basis_diagnostics"][0]["lower_mean_shift"]), bias
        )
        for row in self.lift.weights:
            self.assertEqual(sum(row), 1)
            self.assertEqual(row[0], 0)
            self.assertGreaterEqual(min(row), 0)

    def test_uniform_interior_mean_preserved_exactly(self):
        h = self.basis.spacing
        for cell, weights in enumerate(self.lift.weights[1:4], start=1):
            self.assertEqual(
                sum(j * h * w for j, w in enumerate(weights)), F(2 * cell + 1, 2)
            )

    def test_tail_not_discarded_and_upper_overshoot_is_explicit(self):
        p = [F(0)] * 9
        p[4] = 1
        result = migrate(self.basis, p, [(x, -x) for x in p], lift=self.lift)
        self.assertEqual(sum(result.active), 1)
        self.assertEqual(result.report["source_tail_mass"], 1)
        self.assertGreater(result.report["upper_escape_mass"], np.exp(-4))
        tail = self.lift.diagnostics[-1]
        self.assertAlmostEqual(
            tail["upper_overshoot_probability"], np.exp(-4), places=15
        )
        # Hat rounding preserves x before the upper boundary; only overshoot
        # clamping changes the mean of this tail (its origin is interior).
        self.assertAlmostEqual(tail["mapped_mean"], 5 - np.exp(-4), places=14)

    def test_phase_support_and_signed_content_preserved_without_rebinning(self):
        p = [F(0)] * 9
        p[-1] = F(2, 3)
        result = migrate(self.basis, p, [(F(0), -2 * x) for x in p], lift=self.lift)
        (packet,) = result.phase
        self.assertEqual(
            (packet.start, packet.end, packet.mass, packet.content),
            (F(3, 20), F(1, 5), F(2, 3), (F(0), F(-4, 3))),
        )
        self.assertEqual(sum(result.active), 0)

    def test_fractional_small_old_grid_has_no_immediate_hit(self):
        # Entire first source cell can lie below target h; a nonnegative map
        # to strictly interior nodes cannot preserve that cell's smaller mean.
        basis = MigrationBasis(F(1, 10), 2, 2, F(1, 5), 2, 1, 4)
        lift = basis.lift()
        self.assertEqual(lift.weights[0][1], 1)
        self.assertGreater(lift.diagnostics[0]["lower_mean_shift"], 0)
        self.assertEqual(sum(lift.weights[-1]), 1)
        self.assertGreater(lift.diagnostics[-1]["lower_mean_shift"], 0)

    def test_no_implicit_normalization_and_final_conversion_residual_disclosed(self):
        p = [F(0)] * 9
        p[0] = F(5, 4)
        result = migrate(self.basis, p, [(x,) for x in p], lift=self.lift)
        self.assertEqual(sum(result.active), F(5, 4))
        self.assertEqual(result.report["exact_output_mass"], "5/4")
        active, content, phase = result.solve_inputs()
        self.assertEqual((active.shape, content.shape, phase), ((33,), (33, 1), ()))
        self.assertLess(
            abs(result.report["fp64_active_mass_conversion_residual"]), 2e-15
        )

    def test_rejects_changed_basis_nonfinite_negative_and_bad_content(self):
        p = [F(1, 9)] * 9
        content = [(x,) for x in p]
        other = MigrationBasis(3, 4, 1, F(1, 5), 4, 8, 32)
        with self.assertRaises(ValueError):
            migrate(other, p, content, lift=self.lift)
        for bad in (float("nan"), float("inf"), True, F(-1)):
            damaged = p.copy()
            damaged[0] = bad
            with self.assertRaises(ValueError):
                migrate(self.basis, damaged, content, lift=self.lift)
        zero = p.copy()
        zero[-1] = 0
        with self.assertRaises(ValueError):
            migrate(self.basis, zero, content, lift=self.lift)

    def test_graded_actual_nodes_exact_totals_mean_and_boundary_shift(self):
        for n in (256, 512):
            nodes = tuple(8 * np.expm1(6 * np.arange(n + 1) / n) / np.expm1(6))
            basis = MigrationBasis(4.8, 16, 1, F(1, 5), 8, 8, n, actual_nodes=nodes)
            lift = basis.lift()
            h0 = basis.actual_nodes[1]
            self.assertEqual(lift.weights[0][0], 0)
            # first source cell width is .3; only [0,h0] is folded upward.
            expected_bias = h0**2 / (2 * F(3, 10))
            self.assertEqual(
                sum(x * w for x, w in zip(basis.actual_nodes, lift.weights[0])),
                F(3, 20) + expected_bias,
            )
            for cell in (1, 7, 15):
                expected_mean = F(3, 10) * (F(cell) + F(1, 2))
                self.assertEqual(
                    sum(x * w for x, w in zip(basis.actual_nodes, lift.weights[cell])),
                    expected_mean,
                )
            p = [F(j + 1, 325) for j in range(25)]
            result = migrate(basis, p, [(2 * x, -3 * x) for x in p], lift=lift)
            self.assertEqual(result.report["exact_input_mass"], "1")
            self.assertEqual(result.report["exact_output_mass"], "1")
            self.assertEqual(result.report["exact_output_content"], ["2", "-3"])
            self.assertEqual(len(result.active), n + 1)
            self.assertLess(
                abs(result.report["fp64_active_mass_conversion_residual"]), 3e-15
            )
            self.assertGreater(result.report["upper_escape_mass"], 0)

    def test_actual_nodes_are_validated_and_bound_in_cache(self):
        uniform = tuple(j * F(1, 4) for j in range(33))
        changed = list(uniform)
        changed[1] = F(1, 8)
        other = MigrationBasis(4, 4, 1, F(1, 5), 4, 8, 32, actual_nodes=tuple(changed))
        p = [F(1, 9)] * 9
        with self.assertRaises(ValueError):
            migrate(other, p, [(x,) for x in p], lift=self.lift)
        for nodes in ((0, 1, 1, 3, 8), (0, 1, 2, 3, 7), (0, 1, float("nan"), 3, 8)):
            with self.assertRaises(ValueError):
                MigrationBasis(4, 4, 1, F(1, 5), 4, 8, 4, actual_nodes=nodes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
