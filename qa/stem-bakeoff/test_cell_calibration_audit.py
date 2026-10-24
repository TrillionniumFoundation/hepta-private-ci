import unittest

import numpy as np

from cell_calibration_audit import audit_fit, objective_derivatives, reference_minimum
from cell_calibration_v2 import fit_calibrator


class CalibrationAuditTests(unittest.TestCase):
    def test_gradient_and_hessian_match_finite_differences(self):
        x = np.array([-2., -.3, .5, 1.7])
        y, w = np.array([0, 1, 0, 1]), np.array([1., .5, .5, 1.])
        theta, step = np.array([1.2, -.7]), 1e-5
        _, gradient, hessian = objective_derivatives(theta, x, y, w)
        numeric_gradient, numeric_hessian = np.empty(2), np.empty((2, 2))
        for i in range(2):
            delta = np.eye(2)[i]*step
            plus = objective_derivatives(theta+delta, x, y, w)
            minus = objective_derivatives(theta-delta, x, y, w)
            numeric_gradient[i] = (plus[0]-minus[0])/(2*step)
            numeric_hessian[:, i] = (plus[1]-minus[1])/(2*step)
        np.testing.assert_allclose(gradient, numeric_gradient, atol=2e-9, rtol=0)
        np.testing.assert_allclose(hessian, numeric_hessian, atol=2e-9, rtol=0)
        self.assertGreater(float(np.linalg.eigvalsh(hessian).min()), 0)

    def test_old_fit_matches_independent_interior_and_boundary_minima(self):
        for raw, labels in [([-2, -.4, .3, 1.8], [0, 1, 0, 1]),
                            ([2, 1, -1, -2], [0, 0, 1, 1]),
                            ([0, 0, 0, 0], [0, 0, 0, 1]),
                            ([-.02, -.01, .01, .02], [0, 0, 1, 1])]:
            z, y = np.column_stack((np.zeros(4), raw)), np.array(labels)
            fit = fit_calibrator(z, y)
            audit = audit_fit(z, y, np.ones(4), fit)
            self.assertTrue(audit["declared_converged"])
            self.assertLess(abs(audit["objective_gap_above_independent_reference"]), 1e-8)
            self.assertLess(audit["projected_gradient_per_group"], 1e-8)
            self.assertLess(audit["recorded_calibration_nll_absolute_error"], 1e-12)

    def test_small_score_scale_magnifies_unbounded_old_extrapolation(self):
        raw = np.array([-.02, -.01, .01, .02])
        y, w = np.array([0, 0, 1, 1]), np.ones(4)
        fit = fit_calibrator(np.column_stack((np.zeros(4), raw)), y)
        self.assertGreater(fit["inverse_temperature"], 100)
        self.assertLess(fit["alpha"], 32)
        self.assertTrue(fit["converged"])
        standardized = (raw-raw.mean())/raw.std()
        reference = reference_minimum(standardized, y, w)
        self.assertGreater(reference[0], 0)
        self.assertGreater(fit["alpha"]*(1-fit["center"])/fit["scale"]+fit["bias"], 100)


if __name__ == "__main__":
    unittest.main()
