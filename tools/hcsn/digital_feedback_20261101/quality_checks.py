"""Qualification must preserve missing data and individual resource failures."""
import copy
import unittest

from .quality import PRIMARY_CANDIDATES, cost_audit, quality_audit


class QualityChecks(unittest.TestCase):
    def test_quality_recomputes_margin_and_rejects_missing_metrics(self):
        thresholds = dict(belief_teacher_rmse_max=.1, selected_q_rmse_max=.1,
                          pairwise_ranking_error_max=.1, margin_absolute_error_mean_max=.1,
                          teacher_regret_mean_max=.05, coarse_seen_fraction_min=.95)
        metric = dict(belief_teacher_mse=.0025, selected_q_mse=.0025,
                      predicted_margin=.1, teacher_margin=.05, teacher_regret=.01,
                      pairwise_ranking_error=.05)
        audit = dict(counts=dict(episodes=1, decisions=1), actual_outcomes=dict(utility_mean=.4),
                     sparse_strata=[dict(key=[0, 3, False, False, 0, 0, 7], evaluation_decisions=1,
                                         training_counts=dict(behavior=1))],
                     decisions=[dict(stratum='[0,3,false,false,0,0,7]', exact_unseen=True, metrics=metric)])
        audits = {name: copy.deepcopy(audit) for name in PRIMARY_CANDIDATES}
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
