"""Handmade arrays and interval doubles only; no model, service or dataset."""

import copy
import json
import unittest

import numpy as np

from independent.core_claims import METRICS, SYSTEMS, make_claims, validation_summary


def fixture():
    plan = {"model_seeds": [11, 23], "runtime_batch_size": 2,
            "bootstrap_replicates": 7, "bootstrap_seed": 18, "maximum_greedy_drop": 0.02}
    sources = ["a", "a", "a", "b", "b"]
    rows, measures = [], {system: {} for system in SYSTEMS}
    for index, system in enumerate(SYSTEMS):
        for seed_index, seed in enumerate(plan["model_seeds"]):
            level = 0.2 + index * 0.1 + seed_index * 0.01
            arrays = {metric: [level + row * 0.001 for row in range(5)] for metric in METRICS}
            arrays["pixel_mse"] = [1 - value for value in arrays["pixel_mse"]]
            report = {"mode": "full", "per_row": arrays,
                      "means": {key: float(np.mean(value)) for key, value in arrays.items()},
                      "budget_violations": 0, "decoder_corruption_score_drop": 0.1}
            rows.append({"system": system, "seed": seed, "mode": "full",
                         "always_full": report, "selected": report,
                         "validation": {"full": dict(report["means"])}})
            measures[system][seed] = report
    return rows, plan, sources, measures


class Intervals:
    def __init__(self, first_lower=None):
        self.calls = []
        self.first_lower = first_lower

    def __call__(self, left, right, source_ids, **kwargs):
        mean = float(np.mean(np.asarray(left) - np.asarray(right)))
        lower = self.first_lower if not self.calls and self.first_lower is not None else mean - 0.005
        self.calls.append((np.array(left), np.array(right), list(source_ids), kwargs))
        return {"mean": mean, "ci95": [lower, max(mean + 0.005, lower)], **kwargs}


class CoreClaimTests(unittest.TestCase):
    def test_six_primary_conjunction_and_all_nine_descriptive_metrics(self):
        rows, plan, sources, _ = fixture()
        before = json.dumps(rows, sort_keys=True)
        result = make_claims(rows, plan, sources, Intervals())
        self.assertTrue(result["benefit_verified"])
        self.assertEqual(len(result["gates"]["primary_intervals"]), 6)
        self.assertEqual(set(result["comparisons"]),
                         {"additive_minus_anchor", "ndu_minus_additive", "ndu_minus_supervised"})
        for metrics in (*result["comparisons"].values(), *result["system_intervals"].values()):
            self.assertEqual(set(metrics), set(METRICS))
        self.assertEqual(json.dumps(rows, sort_keys=True), before)

    def test_one_zero_or_negative_primary_lower_bound_fails(self):
        rows, plan, sources, _ = fixture()
        for lower in (0.0, -0.01):
            with self.subTest(lower=lower):
                result = make_claims(rows, plan, sources, Intervals(lower))
                self.assertFalse(result["benefit_verified"])
                self.assertFalse(result["gates"]["core_conjunction"])
                self.assertEqual(sum(result["gates"]["primary_intervals"].values()), 5)

    def test_supervised_strength_only_changes_descriptive_comparison(self):
        rows, plan, sources, _ = fixture()
        weak = make_claims(rows, plan, sources, Intervals())
        for row in rows:
            if row["system"] == "supervised":
                for metric in METRICS:
                    row["always_full"]["per_row"][metric] = [9.0] * 5
                    row["always_full"]["means"][metric] = 9.0
        strong = make_claims(rows, plan, sources, Intervals())
        self.assertEqual(weak["gates"], strong["gates"])
        self.assertEqual(weak["benefit_verified"], strong["benefit_verified"])
        self.assertLess(strong["comparisons"]["ndu_minus_supervised"]["task_utility"]["mean"], 0)

    def test_only_cpu_metrics_use_batch_cohorts_and_absolute_intervals_use_zeros(self):
        rows, plan, sources, _ = fixture()
        interval = Intervals()
        make_claims(rows, plan, sources, interval)
        self.assertEqual(len(interval.calls), 63)
        cpu_calls = [call for call in interval.calls if call[3]["cluster_kind"] == "fixed_service_batch_cohort"]
        self.assertEqual(len(cpu_calls), 14)
        self.assertTrue(all(call[2] == ["cohort:0", "cohort:0", "cohort:1", "cohort:1", "cohort:2"] for call in cpu_calls))
        for left, right, ids, kwargs in interval.calls:
            self.assertEqual(left.shape, (2, 5))
            self.assertEqual(kwargs["seeds"], [11, 23])
            self.assertEqual((kwargs["replicates"], kwargs["bootstrap_seed"]), (7, 18))
            if kwargs["cluster_kind"] == "physical_source":
                self.assertEqual(ids, sources)
        self.assertTrue(all(np.all(call[1] == 0) for call in interval.calls[27:]))
        self.assertTrue(all(interval.calls[index][2] == sources for index in (5, 6, 14, 15, 23, 24)))

    def test_violations_count_full_once_despite_alias_and_corruption_checks_supervised(self):
        rows, plan, sources, _ = fixture()
        rows[0]["always_full"]["budget_violations"] = 2
        result = make_claims(rows, plan, sources, Intervals())
        self.assertEqual(result["gates"]["budget_violations"], 2)
        self.assertFalse(result["benefit_verified"])
        rows[0]["always_full"]["budget_violations"] = 0
        rows[0]["always_full"]["decoder_corruption_score_drop"] = 0
        result = make_claims(rows, plan, sources, Intervals())
        self.assertFalse(result["gates"]["decoder_corruption_reduces_score"])
        self.assertFalse(result["benefit_verified"])

    def test_greedy_retention_is_per_seed_and_does_not_compare_supervised(self):
        rows, plan, sources, _ = fixture()
        report = rows[4]["always_full"]  # additive seed 11 falls below anchor.
        report["per_row"]["greedy_joint_success"] = [0.0] * 5
        report["means"]["greedy_joint_success"] = 0.0
        result = make_claims(rows, plan, sources, Intervals())
        self.assertGreater(result["gates"]["maximum_greedy_drop"], 0.3)
        self.assertFalse(result["gates"]["greedy_retention"])
        self.assertFalse(result["benefit_verified"])

    def test_missing_duplicate_extra_identity_mode_and_unused_critic_rejected(self):
        rows, plan, sources, _ = fixture()
        variants = [rows[:-1], rows + [rows[0]]] + [copy.deepcopy(rows) for _ in range(4)]
        variants[2][0]["system"] = "ndu_control"
        variants[3][0]["mode"] = "continuation"
        variants[4][0]["controller_file"] = "unused.npz"
        variants[5][0]["controller_type"] = "unused-affine-critic"
        for invalid in variants:
            with self.subTest(invalid=variants.index(invalid)):
                with self.assertRaises(ValueError):
                    make_claims(invalid, plan, sources, Intervals())

    def test_bad_arrays_means_and_measure_modes_rejected(self):
        for defect in ("nan", "shape", "mean", "mode"):
            rows, plan, sources, _ = fixture()
            report = rows[0]["always_full"]
            if defect == "nan":
                report["per_row"]["task_utility"][0] = float("nan")
            elif defect == "shape":
                report["per_row"]["task_utility"].pop()
            elif defect == "mean":
                report["means"]["task_utility"] += 0.1
            else:
                report["mode"] = "continuation"
            with self.subTest(defect=defect), self.assertRaises(ValueError):
                make_claims(rows, plan, sources, Intervals())

    def test_validation_has_six_means_uses_raw_full_and_final_cpu_separately(self):
        rows, plan, _, measures = fixture()
        for index, system in enumerate(SYSTEMS):
            for seed in plan["model_seeds"]:
                measures[system][seed]["means"]["task_utility"] = -999.0
                measures[system][seed]["means"]["cpu_net_utility"] = index * 0.3
        result = validation_summary(rows, measures, plan)
        self.assertEqual(len(result["contrasts"]), 6)
        for name in ("additive-anchor", "ndu-additive"):
            self.assertAlmostEqual(result["contrasts"][name + ":task_utility"], 0.1)
            self.assertAlmostEqual(result["contrasts"][name + ":joint_success"], 0.1)
            self.assertAlmostEqual(result["contrasts"][name + ":cpu_net_utility"], 0.3)
        self.assertTrue(result["corruption"])
        self.assertAlmostEqual(result["maximum_greedy_drop"], -0.1)
        del measures["anchor"][11]
        with self.assertRaises(ValueError):
            validation_summary(rows, measures, plan)

    def test_validation_json_roundtrip_preserves_summary_without_mutating_keys(self):
        rows, plan, _, measures = fixture()
        expected = validation_summary(rows, measures, plan)
        loaded_rows, loaded_measures = json.loads(json.dumps(rows)), json.loads(json.dumps(measures))
        before = json.dumps(loaded_measures, sort_keys=True)
        self.assertEqual(validation_summary(loaded_rows, loaded_measures, plan), expected)
        self.assertEqual(json.dumps(loaded_measures, sort_keys=True), before)
        measures["anchor"]["11"] = measures["anchor"].pop(11)
        self.assertEqual(validation_summary(rows, measures, plan), expected)

    def test_validation_rejects_seed_aliases_missing_and_noncanonical_strings(self):
        for defect in ("alias", "missing", "noncanonical", "unexpected"):
            rows, plan, _, measures = fixture()
            if defect == "alias":
                measures["anchor"]["11"] = measures["anchor"][11]
            elif defect == "missing":
                del measures["anchor"][11]
            elif defect == "noncanonical":
                measures["anchor"]["011"] = measures["anchor"].pop(11)
            else:
                measures["anchor"]["99"] = measures["anchor"].pop(11)
            with self.subTest(defect=defect), self.assertRaises(ValueError):
                validation_summary(rows, measures, plan)

    def test_validation_sums_report_budgets_without_top_aggregate_and_rejects_bad_counts(self):
        rows, plan, _, measures = fixture()
        measures["anchor"][11]["budget_violations"] = 3
        measures["ndu"][23]["budget_violations"] = 2
        self.assertNotIn("budget_violations", measures)
        self.assertEqual(validation_summary(rows, measures, plan)["budget_violations"], 5)
        for invalid in (True, -1):
            measures["anchor"][11]["budget_violations"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validation_summary(rows, measures, plan)


if __name__ == "__main__":
    unittest.main()
