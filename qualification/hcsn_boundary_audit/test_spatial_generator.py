"""Independent constraints for a killed nodal spatial research primitive."""

from dataclasses import replace
import unittest

import numpy as np

from qualification.hcsn_boundary_audit.spatial_generator import (
    KilledSpatialGenerator,
    continuum_lower_hit,
)


class SpatialGeneratorTests(unittest.TestCase):
    def test_generator_local_moments_and_absorption(self):
        for drift in (-0.4, 0.0, 0.4):
            model = KilledSpatialGenerator(32, 2.0, drift, 0.6)
            generator = model.matrix()
            x = np.linspace(0, 2, 33)
            np.testing.assert_allclose(generator.sum(axis=1), 0, atol=2e-14)
            np.testing.assert_array_equal(generator[[0, -1]], np.zeros((2, 33)))
            for i in range(1, 32):
                self.assertAlmostEqual(generator[i] @ (x - x[i]), drift, places=13)
                self.assertAlmostEqual(
                    generator[i] @ (x - x[i]) ** 2, 0.6**2, places=13
                )

    def test_irregular_composition_mass_and_signed_content(self):
        rng = np.random.default_rng(74)
        for drift in (-0.4, 0.0, 0.4):
            model = KilledSpatialGenerator(24, 2.0, drift, 0.6)
            times = (0.001, 0.003, 0.02, 0.04, 0.08, 0.16)
            composed = np.eye(25)
            for dt in times:
                composed = composed @ model.transition(dt)
            direct = model.transition(sum(times))
            np.testing.assert_allclose(composed, direct, rtol=0, atol=3e-13)
            self.assertGreaterEqual(np.min(direct), -2e-14)
            np.testing.assert_allclose(direct.sum(axis=1), 1, rtol=0, atol=3e-13)
            probability = rng.dirichlet(np.ones(25))
            content = rng.normal(size=(4, 25))
            np.testing.assert_allclose(
                (content @ composed).sum(axis=1), content.sum(axis=1), atol=3e-13
            )
            self.assertAlmostEqual((probability @ composed).sum(), 1, places=12)

    def test_finite_domain_refinement_against_closed_form(self):
        for drift in (-0.4, 0.0, 0.4):
            for discount in (0.01, 0.3, 2.0):
                errors = []
                for n in (16, 32, 64, 128):
                    model = KilledSpatialGenerator(n, 2.0, drift, 0.6)
                    reference = continuum_lower_hit(
                        np.linspace(0, 2, n + 1), 2.0, drift, 0.6, discount
                    )
                    errors.append(
                        float(
                            np.max(
                                np.abs(model.discounted_lower_hit(discount) - reference)
                            )
                        )
                    )
                for coarse, fine in zip(errors, errors[1:]):
                    self.assertLess(fine, 0.3 * coarse)
                self.assertLess(errors[-1], 2e-4)

    def test_implicit_derivatives_against_two_fd_steps(self):
        for drift in (-0.4, 0.0, 0.4):
            model, discount = KilledSpatialGenerator(48, 2.0, drift, 0.6), 0.3
            derivatives = model.lower_hit_partials(discount)
            for name, actual in derivatives.items():
                for step in (1e-4, 5e-5):
                    if name == "discount":
                        plus = model.discounted_lower_hit(discount + step)
                        minus = model.discounted_lower_hit(discount - step)
                    else:
                        center = getattr(model, name)
                        plus = replace(
                            model, **{name: center + step}
                        ).discounted_lower_hit(discount)
                        minus = replace(
                            model, **{name: center - step}
                        ).discounted_lower_hit(discount)
                    np.testing.assert_allclose(
                        actual, (plus - minus) / (2 * step), rtol=5e-6, atol=5e-8
                    )

    def test_zero_drift_continuum_sensitivity(self):
        # At mu=0, kappa has zero mu derivative; dphi/dmu=-x*phi/sigma^2.
        model, discount = KilledSpatialGenerator(256, 2.0, 0.0, 0.6), 0.3
        x = np.linspace(0, 2, 257)
        exact = -x / 0.6**2 * continuum_lower_hit(x, 2, 0, 0.6, discount)
        np.testing.assert_allclose(
            model.lower_hit_partials(discount)["mu"], exact, atol=5e-5, rtol=0
        )

    def test_upper_exit_is_not_returning_tail(self):
        model = KilledSpatialGenerator(32, 2.0, 0.4, 0.6)
        finite = model.discounted_lower_hit(0.3)
        kappa = np.sqrt(0.4**2 + 2 * 0.3 * 0.6**2)
        halfline = np.exp(-(0.4 + kappa) * np.linspace(0, 2, 33) / 0.6**2)
        self.assertEqual(finite[-1], 0)
        self.assertGreater(halfline[-1], 0)
        self.assertGreater(np.max(halfline - finite), 1e-3)

    def test_invalid_inputs_fail_closed_and_zero_time_identity(self):
        for kwargs in (
            {"intervals": True},
            {"intervals": 513},
            {"mu": float("nan")},
            {"sigma": 0},
            {"endpoint": float("inf")},
            {"mu": 100},
        ):
            parameters = dict(intervals=16, endpoint=2.0, mu=0.4, sigma=0.6)
            parameters.update(kwargs)
            with self.assertRaises(ValueError):
                KilledSpatialGenerator(**parameters)
        model = KilledSpatialGenerator(16, 2.0, 0.4, 0.6)
        np.testing.assert_array_equal(model.transition(0), np.eye(17))
        for invalid in (-1, True, float("nan"), float("inf"), 3):
            with self.assertRaises(ValueError):
                model.transition(invalid)
        for invalid in (0, -1, True, float("nan"), 1e308):
            with self.assertRaises(ValueError):
                model.discounted_lower_hit(invalid)
            with self.assertRaises(ValueError):
                continuum_lower_hit([0, 1, 2], 2.0, 0.0, 0.6, invalid)
        with self.assertRaises(ValueError):
            KilledSpatialGenerator(16, 2.0, 2.0, 0.5).lower_hit_partials(0.3)


if __name__ == "__main__":
    unittest.main()
