"""Synthetic statistical checks: all provenance remains explicitly unverified."""

from copy import deepcopy
import unittest

from .assessment import assess_panel
from .generation import BASELINES, digest


def fixture(seeds=(0,), mode="positive"):
    rows, expected, groups = [], [], {}
    for group in range(100):
        for seed in seeds:
            case = (f"task-{group}", f"sample-{seed}", seed, "test")
            expected.append(case)
            groups[case] = f"group-{group}"
            for baseline in BASELINES:
                success = baseline in ("ndu", "ndu_planning")
                if mode == "negative":
                    success = not success
                elif mode == "zero":
                    success = True
                elif mode == "cluster":
                    success = success if seed == 0 else not success
                rows.append({"task_id": case[0], "sample_id": case[1], "seed": seed, "split": "test",
                             "group_id": groups[case], "baseline": baseline, "status": "HOLD",
                             "evidence_kind": "real", "evaluator_evidence_kind": "real",
                             "execution_provenance": "DECLARED_UNVERIFIED", "evaluator_provenance": "DECLARED_UNVERIFIED",
                             "controller_metering_provenance": "CALLER_REPORTED", "reasons": ["provenance_unverified"],
                             **{key: digest(key) for key in ("manifest_sha256", "objective_sha256", "dataset_sha256", "evaluator_sha256")},
                             "budget_compute": 10.0, "budget_seconds": 10.0, "total_compute": 3.0, "total_seconds": 2.0,
                             "receipts": [{"usage_known": True, "controller_seconds": 0.1}], "critic_success_probability": 0.7,
                             "outcome": {"joint_success": success, "weakest_quality": 0.8,
                                         "quality": {"text": 0.8, "image": 0.8}, "contradictions": 0, "missing_modalities": []}})
    return rows, expected, groups


class PairedAssessmentTests(unittest.TestCase):
    def assess(self, rows, cases, groups, **kwargs):
        return assess_panel(rows, cases, expected_groups=groups, bootstrap_resamples=200, **kwargs)

    def test_analytic_paired_gain_does_not_waive_provenance_or_other_gates(self):
        result = self.assess(*fixture(), include_planning=True)
        self.assertEqual(result["status"], "HOLD")
        self.assertIn("provenance_unverified", result["reasons"])
        for report in result["comparisons"][:3]:
            self.assertEqual(report["delta"]["joint_success"], 1.0)
            self.assertEqual(report["ci95"]["joint_success"], [1.0, 1.0])
            self.assertEqual(report["complete_paired_groups"], 100)
            self.assertEqual(report["numerical_decision"], "POSITIVE_PAIRED_DIFFERENCE")
        self.assertEqual(result["comparisons"][-1]["numerical_decision"], "NO_DEMONSTRATED_GAIN")
        self.assertIn("missing_qualification:retention", result["reasons"])
        self.assertEqual(result, self.assess(*fixture(), include_planning=True))

    def test_cluster_seeds_are_averaged_together_before_resampling(self):
        result = self.assess(*fixture(seeds=(0, 1), mode="cluster"))
        for report in result["comparisons"]:
            self.assertEqual(report["ci95"]["joint_success"], [0.0, 0.0])
            self.assertEqual(report["complete_paired_cases"], 200)
        self.assertEqual(result["estimator_status"], "PERFORMED")
        self.assertIn("correlated_cases_require_clustered_estimator", result["resolved_panel_reasons"])
        self.assertIn("correlated_cases_require_clustered_estimator", result["panel"]["reasons"])

    def test_missing_case_excludes_whole_group_but_preserves_denominator(self):
        rows, cases, groups = fixture(seeds=(0, 1))
        rows = [r for r in rows if not (r["group_id"] == "group-0" and r["seed"] == 1 and r["baseline"] == "fixed")]
        result = self.assess(rows, cases, groups)
        fixed = result["comparisons"][0]
        self.assertEqual((fixed["complete_paired_groups"], fixed["complete_paired_cases"]), (99, 198))
        self.assertEqual(fixed["expected_test_cases"], 200)
        self.assertEqual(result["panel"]["baselines"]["fixed"]["test"]["n_missing_outcomes"], 1)
        self.assertIn("incomplete_paired_group_coverage:ndu:fixed", result["reasons"])
        with self.assertRaises(ValueError):
            self.assess(rows + [deepcopy(rows[0])], cases, groups)
        with self.assertRaises(ValueError):
            self.assess(rows, cases, {cases[0]: "group-0"})

    def test_identity_mismatch_unknown_cost_and_nonpositive_gain_stay_closed(self):
        for mode in ("negative", "zero"):
            result = self.assess(*fixture(mode=mode))
            self.assertTrue(all(r["numerical_decision"] == "NO_DEMONSTRATED_GAIN" for r in result["comparisons"]))
        rows, cases, groups = fixture()
        rows[0]["manifest_sha256"] = digest("substituted")
        rows[1]["receipts"][0]["usage_known"] = False
        result = self.assess(rows, cases, groups)
        self.assertIn("unmatched_case_bindings", result["reasons"])
        self.assertIn("unknown_cost_or_missing_usage_receipts", result["reasons"])
        self.assertEqual(result["comparisons"][0]["complete_paired_groups"], 99)
        self.assertEqual(result["status"], "HOLD")


if __name__ == "__main__":
    unittest.main()
