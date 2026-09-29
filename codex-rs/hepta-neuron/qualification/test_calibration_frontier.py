"""Empirical threshold-solver regressions, not independent OOD/model evidence."""
import copy
import unittest

import numpy as np

from decision_cell_calibration import CLASSES, joint_support_calibration


def panel(confidence, ood, inside, correct):
    """Construct probability fixtures with independent postcondition mistakes."""
    confidence, ood = np.asarray(confidence), np.asarray(ood)
    inside, correct = np.asarray(inside, dtype=bool), np.asarray(correct, dtype=bool)
    labels = {name: np.zeros(len(ood), dtype=np.int64) for name in CLASSES}
    labels["ood"] = (~inside).astype(np.int64)
    probabilities = {name: np.eye(classes)[labels[name]] for name, classes in CLASSES.items()}
    probabilities["action"][:, 0] = confidence
    probabilities["action"][:, 1] = 1 - confidence
    probabilities["ood"] = np.stack((1 - ood, ood), axis=1)
    labels["postcondition"][~correct] = 1
    return probabilities, labels


def exhaustive(probabilities, labels):
    """Independent brute-force oracle over every representable support set."""
    confidence = probabilities["action"].max(axis=1)
    ood = probabilities["ood"][:, 1]
    inside = labels["ood"] == 0
    correct = inside.copy()
    for head in ("action", "target", "disposition", "postcondition"):
        matches = probabilities[head].argmax(axis=1) == labels[head]
        if head == "target":
            matches |= labels[head] == -1
        correct &= matches
    best, result = None, (1.0, 0.0)
    for lower in sorted({0.0, 1.0, *confidence.tolist()}):
        for upper in sorted({0.0, 1.0, *ood.tolist()}):
            ood_pass = ood < upper
            if int((ood_pass & ~inside).sum()) * 20 > int((~inside).sum()):
                continue
            accepted = (confidence >= lower) & ood_pass
            count = int(accepted.sum())
            in_count = int((accepted & inside).sum())
            errors = int((accepted & ~correct).sum())
            if not in_count or errors * 20 > count:
                continue
            key = (in_count, -errors / count, lower, -upper)
            if best is None or key > best:
                best, result = key, (lower, upper)
    return result


class CalibrationFrontierTests(unittest.TestCase):
    def test_sequential_ood_optimum_does_not_force_false_all_reject(self):
        probabilities, labels = panel(
            np.ones(8), [.05] * 5 + [.3, 1., 1.], [True] * 6 + [False] * 2,
            [True] * 5 + [False, True, True])
        result = joint_support_calibration(probabilities, labels)
        self.assertTrue(result["calibration_support_feasible"])
        self.assertEqual(result["calibration_supported_rows"], 5)
        self.assertEqual(result["minimum_confidence"], 1.0)
        self.assertEqual(result["maximum_ood_probability"], .3)
        self.assertEqual(result["calibration_supported_joint_error"], 0.0)
        self.assertEqual(result["calibration_ood_false_acceptance"], 0.0)

    def test_versioned_policy_never_relabels_v1(self):
        p, y = panel([1., 1.], [0., 1.], [True, False], [True, True])
        self.assertEqual(joint_support_calibration(p, y)["calibration_profile"],
                         "hepta.decision-cell-joint-support-calibration.v2")

    def test_matches_exhaustive_frontier_on_seeded_tied_and_untied_panels(self):
        rng = np.random.default_rng(20260929)
        for case in range(512):
            count = int(rng.integers(2, 25))
            confidence = rng.choice([.6, .75, .9, 1.], count)
            ood = rng.choice([0., .05, .2, .3, .7, 1.], count)
            if case % 2:
                confidence = rng.uniform(.51, 1., count)
                ood = rng.uniform(0., 1., count)
            inside = rng.random(count) < .75
            inside[0], inside[-1] = True, False
            p, y = panel(confidence, ood, inside, rng.random(count) < .85)
            with self.subTest(case=case):
                result = joint_support_calibration(p, y)
                self.assertEqual((result["minimum_confidence"], result["maximum_ood_probability"]),
                                 exhaustive(p, y))

    def test_confidence_ties_cannot_cherry_pick_correct_rows(self):
        p, y = panel([1., 1., 1.], [0., 0., 1.], [True, True, False], [True, False, True])
        result = joint_support_calibration(p, y)
        self.assertFalse(result["calibration_support_feasible"])
        self.assertEqual(result["maximum_ood_probability"], 0.)
        self.assertIsNone(result["calibration_supported_joint_error"])

    def test_strict_ood_ties_cannot_cherry_pick_in_domain_rows(self):
        p, y = panel([1., 1.], [0., 0.], [True, False], [True, True])
        self.assertEqual(joint_support_calibration(p, y)["calibration_supported_rows"], 0)

    def test_marginal_ood_cap_is_not_relaxed_by_confidence_rejection(self):
        p, y = panel([1.] * 20 + [.6], [.1] * 20 + [0.], [True] * 20 + [False], [True] * 21)
        result = joint_support_calibration(p, y)
        self.assertFalse(result["calibration_support_feasible"])
        self.assertEqual(result["calibration_ood_false_acceptance"], 0.)

    def test_accepted_ood_is_still_an_error(self):
        p, y = panel([1.] * 60, [0.] * 41 + [1.] * 19,
                     [True] * 40 + [False] * 20, [True] * 60)
        result = joint_support_calibration(p, y)
        self.assertEqual(result["calibration_supported_rows"], 41)
        self.assertEqual(result["calibration_supported_joint_errors"], 1)
        self.assertAlmostEqual(result["calibration_supported_joint_error"], 1 / 41)
        self.assertEqual(result["calibration_ood_false_acceptance"], .05)

    def test_both_populations_remain_mandatory(self):
        for inside in ([True, True], [False, False]):
            p, y = panel([1., 1.], [0., 1.], inside, [True, True])
            with self.assertRaises(ValueError):
                joint_support_calibration(p, y)

    def test_row_permutation_and_input_ownership(self):
        p, y = panel([1., .8, .7, 1., .9], [0., .1, .2, .3, 1.],
                     [True] * 4 + [False], [True, True, True, False, True])
        before = copy.deepcopy((p, y))
        expected = joint_support_calibration(p, y)
        for order in ([4, 3, 2, 1, 0], [2, 0, 4, 1, 3]):
            result = joint_support_calibration({k: v[order] for k, v in p.items()},
                                               {k: v[order] for k, v in y.items()})
            self.assertEqual(result, expected)
        for group, old in zip((p, y), before):
            for head in group:
                np.testing.assert_array_equal(group[head], old[head])

    def test_inapplicable_target_still_has_no_target_error(self):
        p, y = panel([1., 1.], [0., 1.], [True, False], [True, True])
        y["target"][:] = -1
        self.assertEqual(joint_support_calibration(p, y)["calibration_supported_rows"], 1)

    def test_bounded_maximum_panel(self):
        n = 4096
        p, y = panel(np.linspace(.6, 1., n), np.linspace(0., 1., n),
                     [True] * (n // 2) + [False] * (n // 2), [True] * n)
        result = joint_support_calibration(p, y)
        self.assertEqual(result["calibration_supported_rows"], n // 2)
        self.assertEqual(result["calibration_supported_joint_errors"], 0)

    def test_malformed_head_and_nonfinite_values_remain_rejected(self):
        for value in (np.nan, np.inf, -1., 2.):
            p, y = panel([1., 1.], [0., 1.], [True, False], [True, True])
            p["action"][0, 0] = value
            with self.assertRaises(ValueError):
                joint_support_calibration(p, y)


if __name__ == "__main__":
    unittest.main()
