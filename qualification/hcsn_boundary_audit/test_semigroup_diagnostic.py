"""P1 diagnostic: a fixed-grid projected Q(t) is not an exact semigroup.

Evidence-only sentinel on the 2026-11-12 frozen operator, not an acceptance
criterion for a numerical repair. A conservative row-stochastic matrix can
have Q(t) @ Q(t) != Q(2t) because of repeated within-cell reprojection.
The test uses synthetic fixed physics, not a trained model or original C2.
"""

import unittest

import torch

from qualification.hcsn_differentiable.contract import GridSpec
from qualification.hcsn_differentiable.operator import DifferentiableDistributionOperator


GRID = GridSpec(active_cells=16, endpoint=4.8, phase_cells=8, refractory=0.2,
                tail_rate=1.0, quadrature_order=16, initial_log_std=0.08)
PHYSICS = {"log_boundary": 0.0, "sigma": 0.35,
           "absolute_reset": 1.7332530178673953, "discount": 0.08}
DRIFTS = (-0.4, 0.0, 0.4)
GAPS = (0.001, 0.02)
EXACT_SEMIGROUP_TOLERANCE = 1e-8


def semigroup_diagnostic(mu, dt):
    """Compare the two valid, equal-duration paths on the same 25-state basis."""
    op = DifferentiableDistributionOperator(GRID)
    params = {name: torch.tensor(value, dtype=torch.float64)
              for name, value in dict(PHYSICS, mu=mu).items()}
    with torch.no_grad():
        qdt = op(dt=dt, **params).matrix
        qdouble = op(dt=2 * dt, **params).matrix
        composed = qdt @ qdt
        total_variation = 0.5 * (composed - qdouble).abs().sum(-1)
        return {
            "mu": mu,
            "dt": dt,
            "max_total_variation": float(total_variation.max()),
            "mean_active_source_total_variation": float(
                total_variation[:GRID.active_count].mean()),
            "source_cell5_total_variation": float(total_variation[5]),
            "composed_mass_error": float((composed.sum(-1) - 1).abs().max()),
            "matrices_finite": bool(torch.isfinite(composed).all()),
        }


class TestProjectedSemigroupDiagnostic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_existing_nonsemigroup_discrepancy_not_hidden_by_mass(self):
        # This deliberately pins the observed failure of exact semigroup
        # consistency. When the representation is repaired, replace this
        # historical sentinel with a *new* bounded-consistency qualification.
        for drift in DRIFTS:
            for dt in GAPS:
                with self.subTest(mu=drift, dt=dt):
                    row = semigroup_diagnostic(drift, dt)
                    self.assertTrue(row["matrices_finite"])
                    self.assertLess(row["composed_mass_error"], 1e-11)
                    self.assertGreater(row["max_total_variation"],
                                       EXACT_SEMIGROUP_TOLERANCE)

    def test_original_zero_drift_short_gap_identity(self):
        row = semigroup_diagnostic(0.0, 0.001)
        self.assertAlmostEqual(row["max_total_variation"],
                               0.023689623092389506, delta=1e-7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
