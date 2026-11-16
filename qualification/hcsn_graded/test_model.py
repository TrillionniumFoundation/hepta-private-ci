"""New-candidate geometry, actual DDE and short-gap mechanism controls."""

import math
import unittest

import numpy as np
from scipy.linalg import expm

from qualification.hcsn_boundary_audit.spatial_generator import continuum_lower_hit
from qualification.hcsn_joint_dde.reference import renewal_events
from qualification.hcsn_joint_dde.basis import basis_values
from .model import GradedJointModel
from .spatial import GradedSpatialGenerator


class TestGradedJointModel(unittest.TestCase):
    def test_nonuniform_generator_matches_drift_and_variance_and_has_conservative_rows(
        self,
    ):
        spatial = GradedSpatialGenerator(128, 8.0, -0.12, 0.35)
        nodes, (down, up) = spatial.nodes, spatial.rates
        left, right = np.diff(nodes)[:-1], np.diff(nodes)[1:]
        np.testing.assert_allclose(
            up * right - down * left, spatial.mu, atol=2e-12, rtol=0
        )
        np.testing.assert_allclose(
            up * right**2 + down * left**2, spatial.sigma**2, atol=2e-15, rtol=0
        )
        np.testing.assert_allclose(spatial.matrix().sum(1), 0, atol=3e-11, rtol=0)
        self.assertGreaterEqual(min(down.min(), up.min()), 0)
        self.assertLess(nodes[1], 0.001)

    def test_actual_node_reset_preserves_reset_position(self):
        model = GradedJointModel(
            GradedSpatialGenerator(128, 8.0, -0.12, 0.35), 0.32, 0.2, 0.15
        )
        _, _, _, reset = model.ingredients()
        self.assertAlmostEqual(reset.sum(), 1.0, places=15)
        self.assertAlmostEqual(
            float(reset @ model.spatial.nodes[1:-1]), 0.32, places=15
        )
        self.assertEqual(np.count_nonzero(reset), 2)

    def test_graded_discounted_transform_refines_against_continuous_finite_domain(self):
        errors = []
        for count in (128, 256, 512):
            spatial = GradedSpatialGenerator(count, 8.0, -0.12, 0.35)
            reference = continuum_lower_hit(spatial.nodes, 8.0, -0.12, 0.35, 0.15)
            errors.append(
                float(max(abs(spatial.discounted_lower_hit(0.15) - reference)))
            )
        self.assertTrue(all(b < a / 3 for a, b in zip(errors, errors[1:])))
        self.assertLess(errors[-1], 2e-5)

    def test_actual_graded_dde_matches_independent_serial_ctmc_and_signed_content(self):
        model = GradedJointModel(
            GradedSpatialGenerator(64, 8.0, -0.12, 0.35), 0.32, 0.2, 0.15
        )
        active = np.zeros(65)
        active[np.searchsorted(model.spatial.nodes, 0.3)] = 1
        content = np.c_[2 * active, -3 * active]
        row = model.solve(
            [0.0, 0.001, 0.017, 0.16, 0.3],
            active,
            content,
            rtol=2e-11,
            atol=2e-13,
            max_step=0.01,
        )["rows"][-1]
        transient, lower, upper, reset = model.ingredients()
        reference = renewal_events(
            transient,
            lower,
            upper,
            active[1:-1],
            reset,
            horizon=0.3,
            delay=0.2,
            discount=0.15,
        )
        self.assertAlmostEqual(
            row["events"][0], reference["expected_events"], delta=2e-9
        )
        self.assertAlmostEqual(
            row["discounted_events"][0], reference["discounted_events"], delta=2e-9
        )
        self.assertLess(abs(row["mass_residual"]), 2e-10)
        np.testing.assert_allclose(
            row["active"][:, 1], 2 * row["active"][:, 0], atol=3e-12, rtol=0
        )
        np.testing.assert_allclose(
            row["active"][:, 2], -3 * row["active"][:, 0], atol=3e-12, rtol=0
        )

    def test_graded_dynamic_continuation_uses_same_actual_flow(self):
        model = GradedJointModel(
            GradedSpatialGenerator(128, 8.0, -0.12, 0.35), 0.32, 0.2, 0.15
        )
        active = np.zeros(129)
        active[np.searchsorted(model.spatial.nodes, 0.3)] = 1.0
        row = model.solve(
            [0.0, 0.013, 0.19, 0.3],
            active,
            active[:, None],
            rtol=1e-12,
            atol=1e-14,
            max_step=0.005,
        )["rows"][-1]
        values, reset_value = model.perpetual()
        terminal = row["active"][:, 0] @ values[1:-1] + row["upper"][0] * 0.4 / 0.15
        terminal += row["discounted_remaining_phase"][0] * reset_value
        observed = (
            0.4 * row["discounted_active_time"][0]
            + row["discounted_events"][0]
            + math.exp(-0.15 * 0.3) * terminal
        )
        self.assertAlmostEqual(observed, float(active @ values), delta=5e-9)

    def test_zero_stretch_reduces_to_uniform_grid_rates_without_reusing_admission(self):
        spatial = GradedSpatialGenerator(32, 2.0, -0.12, 0.35, stretch=0.0)
        h = 2.0 / 32
        down, up = spatial.rates
        np.testing.assert_allclose(
            down, 0.35**2 / (2 * h**2) + 0.12 / (2 * h), atol=3e-13, rtol=0
        )
        np.testing.assert_allclose(
            up, 0.35**2 / (2 * h**2) - 0.12 / (2 * h), atol=3e-13, rtol=0
        )
        np.testing.assert_allclose(
            expm(0.003 * spatial.matrix()).sum(1), 1, atol=2e-15, rtol=0
        )

    def test_invalid_graded_rates_reset_and_geometry_fail_closed(self):
        with self.assertRaises(ValueError):
            GradedSpatialGenerator(16, 8.0, -2.0, 0.05)
        with self.assertRaises(ValueError):
            GradedSpatialGenerator(128, 8.0, -0.12, 0.35, stretch=float("nan"))
        spatial = GradedSpatialGenerator(128, 8.0, -0.12, 0.35)
        with self.assertRaises(ValueError):
            GradedJointModel(spatial, spatial.nodes[1] / 2, 0.2, 0.15)
        with self.assertRaisesRegex(ValueError, "exact uniform"):
            basis_values(GradedJointModel(spatial, 0.32, 0.2, 0.15))


if __name__ == "__main__":
    unittest.main(verbosity=2)
