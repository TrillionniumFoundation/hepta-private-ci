import copy
import unittest
from unittest.mock import patch

import numpy as np

from cell_calibration_bounded import (ALPHAS, apply_bounded_calibrator,
    fit_bounded_calibrator, validate_bounded_calibrator)


BINDINGS = {"feature_identity": "1"*64, "predictor_sha256": "2"*64,
            "calibration_context_sha256": "3"*64}


def rows(groups):
    return [{"source_id": f"s-{i}", "group_id": str(group)} for i, group in enumerate(groups)]


class BoundedCalibrationTests(unittest.TestCase):
    def fit(self, margins, labels, groups=None, **kwargs):
        return fit_bounded_calibrator(np.asarray(margins), np.asarray(labels, dtype=int),
            rows(range(len(labels)) if groups is None else groups),
            effective_training_prior=kwargs.pop("effective_training_prior", [.5, .5]),
            bindings=BINDINGS, **kwargs)

    def apply(self, margins, fit):
        return apply_bounded_calibrator(margins, fit, expected_bindings=BINDINGS)

    def test_four_group_separation_cannot_produce_extreme_extrapolation(self):
        fit = self.fit([-2, -1, 1, 2], [0, 0, 1, 1])
        self.assertEqual(fit["alpha"], 1)
        p = self.apply([-1e308, -100, 0, 100, 1e308], fit)
        self.assertTrue(np.isfinite(p).all())
        np.testing.assert_allclose(p.sum(axis=1), 1, atol=0, rtol=0)
        self.assertGreaterEqual(float(p.min()), .4)
        self.assertLessEqual(float(p.max()), .6)
        excess = -np.log(p) + np.log(.5)
        self.assertLessEqual(float(excess.max()), np.log1p(4/16)+1e-15)

    def test_imbalanced_prior_has_uniform_relative_loss_bound(self):
        fit = self.fit([-3, 1, 2, 3], [0, 1, 1, 1])
        p = self.apply([-1e308, 1e308], fit)
        q = np.array([1-fit["prior_positive"], fit["prior_positive"]])
        self.assertTrue(np.all(p >= (1-fit["mixture_weight"])*q-1e-15))
        self.assertLessEqual(float((-np.log(p)+np.log(q)).max()),
                             fit["maximum_nll_excess_over_prior_per_row"]+1e-15)
        self.assertGreaterEqual(float(p.min()), 2/15-1e-15)
        self.assertLessEqual(float(p.max()), 13/15+1e-15)

    def test_no_evidence_and_anti_evidence_select_exact_prior(self):
        for margins in ([0, 0, 0, 0], [2, 1, -1, -2]):
            fit = self.fit(margins, [0, 0, 1, 1])
            self.assertEqual(fit["alpha"], 0)
            np.testing.assert_array_equal(self.apply([-100, 0, 100], fit), np.full((3, 2), .5))
        fit = self.fit([0, 0, 0, 0], [0, 0, 0, 1])
        np.testing.assert_allclose(fit["prior"], [2/3, 1/3], atol=1e-15, rtol=0)
        np.testing.assert_array_equal(self.apply([100], fit), [fit["prior"]])

    def test_effective_training_prior_has_exact_no_evidence_meaning(self):
        prior = [.25, .75]
        margin = np.log(prior[1]/prior[0])
        fit = self.fit([margin]*4, [0, 0, 0, 1], effective_training_prior=prior)
        self.assertEqual(fit["alpha"], 0)
        self.assertEqual(fit["effective_training_prior"], prior)
        np.testing.assert_allclose(fit["prior"], [2/3, 1/3], atol=1e-15, rtol=0)
        np.testing.assert_array_equal(self.apply([margin], fit), [fit["prior"]])

    def test_action_replication_does_not_increase_group_evidence(self):
        margins, labels = np.array([-2., -1, 1, 2]), np.array([0, 0, 1, 1])
        original = self.fit(margins, labels)
        repeated = self.fit(np.repeat(margins, 7), np.repeat(labels, 7), np.repeat(np.arange(4), 7))
        self.assertEqual(repeated["calibration_groups"], 4)
        self.assertEqual(repeated["calibration_rows"], 28)
        for key in ("alpha", "prior_positive", "mixture_weight", "group_weighted_class_mass"):
            self.assertEqual(original[key], repeated[key])
        np.testing.assert_array_equal(self.apply(margins, original), self.apply(margins, repeated))

    def test_complement_mode_is_bitwise_order_equivariant(self):
        fit = self.fit([-3, -1, 1, 3], [0, 0, 1, 1], mode="complement_symmetric")
        margin = np.array([-1e308, -9., -1., -1e-12, 0., 1e-12, 1., 9., 1e308])
        np.testing.assert_array_equal(self.apply(-margin, fit), self.apply(margin, fit)[:, ::-1])
        self.assertEqual(fit["prior_positive"], .5)
        with self.assertRaisesRegex(ValueError, "symmetry"):
            self.fit([-1, 1], [0, 1], mode="complement_symmetric", effective_training_prior=[.2, .8])

    def test_grid_selection_matches_direct_calibration_objectives(self):
        margins, labels = np.array([-7., -2, -.2, .3, 1, 8]), np.array([0, 1, 0, 1, 1, 0])
        fit = self.fit(margins, labels)
        candidates = []
        for alpha in ALPHAS:
            state = {**fit, "alpha": alpha}
            p = self.apply(margins, state)
            candidates.append(float(-np.log(p[np.arange(len(labels)), labels]).mean()))
        expected = next(a for a, score in zip(ALPHAS, candidates) if score <= min(candidates)+1e-12)
        self.assertEqual(fit["alpha"], expected)
        self.assertLessEqual(fit["weighted_calibration_nll"], fit["prior_only_calibration_nll"]+1e-12)

    def test_tolerance_is_relative_to_global_minimum_not_last_accepted_candidate(self):
        losses = dict(zip(ALPHAS, [1., 1.-.8e-12, 1.-1.2e-12, 2., 2., 2.]))
        def close_losses(margins, alpha, *args):
            correct = np.exp(-losses[alpha])
            return np.tile([correct, 1-correct], (len(margins), 1))
        with patch("cell_calibration_bounded._predict", side_effect=close_losses):
            fitted = self.fit([0., 0.], [0, 0])
        self.assertEqual(fitted["alpha"], 1/16)
        self.assertGreater(fitted["weighted_calibration_nll"], fitted["minimum_candidate_calibration_nll"])

    def test_holdout_overlap_nonfinite_and_tampered_bindings_reject(self):
        with self.assertRaisesRegex(ValueError, "role"):
            self.fit([-1, 1], [0, 1], fit_role="holdout")
        with self.assertRaisesRegex(ValueError, "overlap"):
            self.fit([-1, 1], [0, 1], forbidden_groups=["1"])
        with self.assertRaisesRegex(ValueError, "finite"):
            self.fit([np.nan, 1], [0, 1])
        fit = self.fit([-1, 1], [0, 1])
        for key, value in [("alpha", 32), ("mixture_weight", 1), ("prior_positive", .999)]:
            broken = copy.deepcopy(fit)
            broken[key] = value
            with self.assertRaises(ValueError):
                self.apply([0], broken)
        with self.assertRaisesRegex(ValueError, "binding"):
            validate_bounded_calibrator(fit, expected_bindings={**BINDINGS, "predictor_sha256": "4"*64})


if __name__ == "__main__":
    unittest.main()
