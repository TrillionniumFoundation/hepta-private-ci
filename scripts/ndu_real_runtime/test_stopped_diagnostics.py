"""Pure registration and finite predictive-score boundary checks."""

import unittest

from .stopped_diagnostics import (
    REGISTRATION_SCHEMA,
    validate_registration,
    weighted_crps,
)


def registration():
    return {
        "schema": REGISTRATION_SCHEMA,
        "fit_source_groups": ["fit"],
        "calibration_source_groups": ["c1", "c2"],
        "diagnostic_source_groups": ["d1", "d2"],
        "core": "ordinary",
        "memory_mode": "reset",
        "seed": 19,
        "neighbor_groups": 2,
        "particles": 2,
        "risk_settings": [0.0, 2.0],
        "feature_scales": [1.0] * 40,
        "behavior_was_unfitted_collector": False,
    }


class DiagnosticBoundaryTests(unittest.TestCase):
    def test_group_overlap_duplicate_and_unknown_registration_fields_fail(self):
        for change in (
            {"calibration_source_groups": ["fit", "c2"]},
            {"diagnostic_source_groups": ["c1", "d2"]},
            {"diagnostic_source_groups": ["d1", "d1"]},
            {"test_source_groups": ["secret"]},
        ):
            with self.assertRaises(ValueError):
                validate_registration({**registration(), **change})
        with self.assertRaisesRegex(ValueError, "unfitted"):
            validate_registration({**registration(), "fit_source_groups": []})

    def test_frozen_risk_and_numeric_settings_are_checked(self):
        for change in (
            {"risk_settings": [True]},
            {"risk_settings": [0.0, 0.0]},
            {"particles": 1},
            {"feature_scales": [0.0] * 40},
            {"max_distance": float("nan")},
        ):
            with self.assertRaises(ValueError):
                validate_registration({**registration(), **change})

    def test_weighted_crps_matches_cdf_integrals_and_point_absolute_error(self):
        self.assertEqual(weighted_crps([2.0], [1.0], 3.0), 1.0)
        self.assertEqual(weighted_crps([0.0, 1.0], [0.5, 0.5], 0.5), 0.25)
        # Integral of F^2 below y and (1-F)^2 above y for this two-point law.
        self.assertAlmostEqual(weighted_crps([0.0, 1.0], [0.75, 0.25], 0.5), 0.3125)
        self.assertEqual(weighted_crps([0.0, 0.0, 1.0], [0.25, 0.5, 0.25], 0.5), 0.3125)
        for probabilities in ([0.2, 0.2], [-1.0, 2.0], [float("nan"), 1.0]):
            with self.assertRaises(ValueError):
                weighted_crps([0.0, 1.0], probabilities, 0.5)


if __name__ == "__main__":
    unittest.main()
