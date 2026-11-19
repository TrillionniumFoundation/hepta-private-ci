"""Executable graded migration: finite/renewal references and rejection tests."""

import unittest
from fractions import Fraction
import numpy as np

from qualification.hcsn_boundary_audit.spatial_generator import KilledSpatialGenerator
from .graded import GradedSpatialGenerator, ShortGapKernel
from .graded_migration import migrate, migration_weights
from .model import JointModel
from .short_gap_reference import basis
from .test_model import serial_reference


class TestGradedMigration(unittest.TestCase):
    def test_uniform_limit_preserves_actual_model_and_perpetual(self):
        old = JointModel(KilledSpatialGenerator(32, 2.0, -0.12, 0.35), 0.51, 0.2, 0.15)
        new = JointModel(
            GradedSpatialGenerator(32, 2.0, -0.12, 0.35, 0.0), 0.51, 0.2, 0.15
        )
        np.testing.assert_allclose(
            old.spatial.matrix(), new.spatial.matrix(), atol=3e-13
        )
        for a, b in zip(old.ingredients(), new.ingredients()):
            np.testing.assert_allclose(a, b, atol=3e-13)
        np.testing.assert_allclose(old.perpetual()[0], new.perpetual()[0], atol=2e-12)

    def test_migration_preserves_probability_and_nonproportional_signed_content(self):
        model = JointModel(
            GradedSpatialGenerator(128, 8.0, -0.12, 0.35), 0.62, 0.2, 0.15
        )
        weights, diagnostics = migration_weights(model.spatial.nodes)
        p = np.arange(1, 26, dtype=float)
        p *= 2 / p.sum()
        marks = np.column_stack(
            (p * np.linspace(-3, 2, 25), p * np.linspace(4, -2, 25))
        )
        active, content, phase, receipt = migrate(model, p, marks, weights)
        self.assertEqual(receipt["lower_atom"], 0.0)
        self.assertLess(abs(receipt["mass_residual"]), 5e-15)
        self.assertEqual(
            (phase[0].start, phase[-1].end),
            (0, Fraction(1, 5)),
        )
        self.assertGreater(diagnostics["lower_mass_transferred"][0], 0)
        row = model.solve(
            [0.0, 0.003, 0.08, 0.21],
            active,
            content,
            phase,
            rtol=1e-11,
            atol=1e-13,
            max_step=0.01,
        )["rows"][-1]
        self.assertLess(abs(row["mass_residual"]), 2e-10)
        np.testing.assert_allclose(row["content_residual"], 0.0, atol=3e-10)

    def test_spectral_short_step_matches_actual_dde_with_phase_and_signed_marks(self):
        model = JointModel(
            GradedSpatialGenerator(128, 8.0, -0.12, 0.35), 0.62, 0.2, 0.15
        )
        weights, _ = migration_weights(model.spatial.nodes)
        p = np.arange(25, 0, -1, dtype=float)
        p /= p.sum()
        active, marks, phase, _ = migrate(model, p, np.c_[2 * p, -3 * p], weights)
        kernel = ShortGapKernel(model.spatial, model.discount)
        times = [0.001, 0.003, 0.02, 0.04, 0.08, 0.16]
        rows = model.solve(
            times, active, marks, phase, rtol=1e-11, atol=1e-13, max_step=0.005
        )["rows"]
        for row, t in zip(rows, times):
            actual = np.array(
                [
                    row[x][0]
                    for x in ("events", "discounted_events", "discounted_active_time")
                ]
            )
            np.testing.assert_allclose(
                actual, p @ kernel.basis(model, weights, t), atol=2e-9, rtol=0
            )
            for field in (
                "active",
                "upper",
                "refractory",
                "events",
                "discounted_events",
            ):
                np.testing.assert_allclose(
                    row[field][..., 1], 2 * row[field][..., 0], atol=2e-11
                )
                np.testing.assert_allclose(
                    row[field][..., 2], -3 * row[field][..., 0], atol=2e-11
                )

    def test_boundary_short_time_refinement_against_continuum(self):
        errors = []
        for n in (128, 256, 512):
            model = JointModel(
                GradedSpatialGenerator(n, 8.0, -0.12, 0.35), 0.62, 0.2, 0.15
            )
            weights, _ = migration_weights(model.spatial.nodes)
            kernel = ShortGapKernel(model.spatial, 0.15)
            actual = kernel.basis(model, weights, 0.001)[0]
            reference = basis(model, 0.001)[0]
            errors.append(abs(actual[0] - reference[0]))
        self.assertLess(errors[1], errors[0] / 3)
        self.assertLess(errors[2], errors[1] / 3)
        self.assertLess(errors[-1], 3e-5)

    def test_delayed_renewal_matches_serial_ctmc_after_multiple_resets(self):
        model = JointModel(
            GradedSpatialGenerator(32, 2.0, -0.12, 0.35), 0.51, 0.2, 0.15
        )
        p = np.zeros(33)
        p[8] = 1.0
        row = model.solve(
            [0.17, 0.41, 0.7],
            p,
            np.c_[2 * p, -3 * p],
            rtol=1e-11,
            atol=1e-13,
            max_step=0.005,
        )["rows"][-1]
        actual = np.array(
            [
                row[x][0]
                for x in (
                    "events",
                    "discounted_events",
                    "refractory",
                    "discounted_active_time",
                )
            ]
        )
        np.testing.assert_allclose(
            actual, serial_reference(model, 0.7, p), atol=4e-9, rtol=0
        )

    def test_rejects_invalid_mesh_law_and_unsupported_uniform_gradient(self):
        for args in [
            (True, 8.0, -0.12, 0.35),
            (64, 8.0, -0.12, 0.05),
            (64, 8.0, -0.12, 0.35, 7.0),
        ]:
            with self.assertRaises(ValueError):
                GradedSpatialGenerator(*args)
        model = JointModel(
            GradedSpatialGenerator(64, 8.0, -0.12, 0.35), 0.62, 0.2, 0.15
        )
        with self.assertRaises(NotImplementedError):
            model.spatial.lower_hit_partials(0.15)
        with self.assertRaises(TypeError):
            _ = model.spatial.spacing
        weights, _ = migration_weights(model.spatial.nodes)
        p = np.full(25, 1 / 25)
        with self.assertRaises(ValueError):
            migrate(model, -p, np.c_[p], weights)
        broken = weights.copy()
        broken[0, 0] = 0.01
        with self.assertRaises(ValueError):
            migrate(model, p, np.c_[p], broken)
        with self.assertRaises(ValueError):
            ShortGapKernel(model.spatial, 0.15).basis(model, weights, 0.201)
