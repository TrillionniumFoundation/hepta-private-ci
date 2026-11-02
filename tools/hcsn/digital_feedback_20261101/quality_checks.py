"""Qualification must preserve missing data and individual resource failures."""
import copy
import unittest

from .quality import PRIMARY_CANDIDATES, cost_audit, quality_audit


def quality_fixture(predictions=(.9,), labels=(1,)):
    thresholds = dict(belief_teacher_rmse_max=.1, selected_q_rmse_max=.1,
                      pairwise_ranking_error_max=.1, margin_absolute_error_mean_max=.1,
                      teacher_regret_mean_max=.05, coarse_seen_fraction_min=.95,
                      actual_label_brier_max=.25, actual_label_ece_max=.10)
    decisions = []
    for prediction, label in zip(predictions, labels):
        metric = dict(belief_teacher_mse=.0025, selected_q_mse=.0025,
                      predicted_margin=.1, teacher_margin=.05, teacher_regret=.01,
                      pairwise_ranking_error=.05, belief_prediction=prediction,
                      actual_label_brier=(prediction - label) ** 2)
        decisions.append(dict(stratum='[0,3,false,false,0,0,7]', exact_unseen=True, metrics=metric))
    bins = []
    for index in range(10):
        rows = [(p, y) for p, y in zip(predictions, labels) if min(int(p * 10), 9) == index]
        prediction = sum(p for p, _ in rows) / len(rows) if rows else None
        target = sum(y for _, y in rows) / len(rows) if rows else None
        bins.append(dict(lower=index / 10, upper=(index + 1) / 10, count=len(rows),
                         mean_prediction=prediction, mean_target=target,
                         absolute_gap=abs(prediction - target) if rows else None))
    calibration = dict(kind="actual label", count=len(decisions), bins=bins,
                       ece=sum(row["count"] * row["absolute_gap"] for row in bins if row["count"]) / len(decisions))
    audit = dict(counts=dict(episodes=len(decisions), decisions=len(decisions)),
                 actual_outcomes=dict(utility_mean=.4), actual_label_calibration=calibration,
                 sparse_strata=[dict(key=[0, 3, False, False, 0, 0, 7],
                                     evaluation_decisions=len(decisions), training_counts=dict(behavior=1))],
                 decisions=decisions)
    return thresholds, {name: copy.deepcopy(audit) for name in PRIMARY_CANDIDATES}


class QualityChecks(unittest.TestCase):
    def test_quality_recomputes_margin_and_rejects_missing_metrics(self):
        thresholds, audits = quality_fixture()
        result = quality_audit(audits, thresholds)
        self.assertTrue(result["all_required_pass"])
        values = result["candidates"][PRIMARY_CANDIDATES[0]]["metrics"]
        self.assertEqual(values["coarse_seen_fraction"], 1.)
        self.assertEqual(values["exact_seen_fraction"], 0.)
        self.assertEqual(values["margin_absolute_error_mean"], .05)
        audits[PRIMARY_CANDIDATES[0]]["decisions"][0]["metrics"].pop("selected_q_mse")
        result = quality_audit(audits, thresholds)
        self.assertFalse(result["all_required_pass"])
        self.assertIsNone(result["candidates"][PRIMARY_CANDIDATES[0]]["overall"])

    def test_actual_calibration_is_separate_and_both_gates_are_required(self):
        thresholds, audits = quality_fixture((.4,) * 10, (0,) * 5 + (1,) * 5)
        result = quality_audit(audits, thresholds)
        candidate = result["candidates"][PRIMARY_CANDIDATES[0]]
        self.assertTrue(candidate["gates"]["belief_teacher_rmse"])
        self.assertAlmostEqual(candidate["metrics"]["actual_label_brier"], .26)
        self.assertFalse(candidate["gates"]["actual_label_brier"])
        self.assertTrue(candidate["gates"]["actual_label_ece"])
        self.assertFalse(candidate["overall"])
        self.assertEqual(candidate["actual_label_calibration"], audits[PRIMARY_CANDIDATES[0]]["actual_label_calibration"])
        thresholds, audits = quality_fixture((.65,), (1,))
        candidate = quality_audit(audits, thresholds)["candidates"][PRIMARY_CANDIDATES[0]]
        self.assertTrue(candidate["gates"]["belief_teacher_rmse"])
        self.assertTrue(candidate["gates"]["actual_label_brier"])
        self.assertFalse(candidate["gates"]["actual_label_ece"])
        self.assertFalse(candidate["overall"])

    def test_actual_calibration_missing_or_inconsistent_never_becomes_zero(self):
        thresholds, base = quality_fixture()
        name = PRIMARY_CANDIDATES[0]
        for fault in ("missing_brier", "missing_calibration", "wrong_count", "bin_count", "wrong_ece", "teacher_kind"):
            audits = copy.deepcopy(base)
            audit = audits[name]
            if fault == "missing_brier":
                audit["decisions"][0]["metrics"].pop("actual_label_brier")
            elif fault == "missing_calibration":
                audit.pop("actual_label_calibration")
            elif fault == "wrong_count":
                audit["actual_label_calibration"]["count"] = 0
            elif fault == "bin_count":
                audit["actual_label_calibration"]["bins"][9]["count"] = 0
            elif fault == "wrong_ece":
                audit["actual_label_calibration"]["ece"] = 0.
            else:
                audit["actual_label_calibration"]["kind"] = "fitted-law teacher soft target"
            with self.subTest(fault=fault):
                result = quality_audit(audits, thresholds)
                self.assertFalse(result["all_required_pass"])
                self.assertEqual(result["candidates"][name]["status"], "incomplete")
                self.assertIsNone(result["candidates"][name]["overall"])
        thresholds.pop("actual_label_ece_max")
        with self.assertRaises(ValueError):
            quality_audit(base, thresholds)

    def test_undefined_ranking_uses_the_teacher_numerical_tie_tolerance(self):
        thresholds, audits = quality_fixture((.9, .9), (1, 1))
        name = PRIMARY_CANDIDATES[0]
        metric = audits[name]["decisions"][0]["metrics"]
        metric.update(pairwise_ranking_error=None, teacher_margin=1e-14, teacher_regret=1e-14)
        candidate = quality_audit(audits, thresholds)["candidates"][name]
        self.assertEqual(candidate["status"], "complete")
        self.assertEqual(candidate["metrics"]["ranking_undefined_decisions"], 1)
        self.assertEqual(candidate["metrics"]["ranking_evaluable_decisions"], 1)
        self.assertTrue(candidate["overall"])
        for coordinate in ("teacher_margin", "teacher_regret"):
            altered = copy.deepcopy(audits)
            altered[name]["decisions"][0]["metrics"][coordinate] = 2e-12
            with self.subTest(coordinate=coordinate):
                candidate = quality_audit(altered, thresholds)["candidates"][name]
                self.assertEqual(candidate["status"], "incomplete")
                self.assertIsNone(candidate["overall"])
                self.assertIn("undefined rank inconsistent", candidate["reasons"][0])

    def test_every_cpu_arm_and_registered_completeness_matter(self):
        def receipt(fit, candidate, seconds):
            return dict(fit=fit, spec=dict(id=candidate), candidate_cpu_seconds=seconds,
                        training_cpu_budget=8., cpu_tolerance_seconds=.16,
                        optimizer_updates=20, training_valid=True)
        rows = [receipt(1, "a", 7.9), receipt(1, "b", 8.1),
                receipt(2, "a", 8.), receipt(2, "b", 8.01)]
        self.assertTrue(cost_audit(rows, [1, 2], ["a", "b"])["all_actual_cpu_matching"])
        self.assertFalse(cost_audit(rows)["all_actual_cpu_matching"])
        self.assertFalse(cost_audit(rows[:-1], [1, 2], ["a", "b"])["all_actual_cpu_matching"])
        rows[-1]["candidate_cpu_seconds"] = 8.2
        self.assertFalse(cost_audit(rows, [1, 2], ["a", "b"])["all_actual_cpu_matching"])
        rows[-1]["cpu_tolerance_seconds"] = 1.
        result = cost_audit(rows, [1, 2], ["a", "b"])
        self.assertIsNone(result["arms"][-1]["gate"])


if __name__ == "__main__":
    unittest.main()
