"""Counterexamples for prospective VERIFY paired selection qualification."""

from copy import deepcopy
import hashlib
import unittest

from .matched_qualification import analyze_matched


def sha(key):
    return hashlib.sha256(key.encode()).hexdigest()


def example(n=8, clusters=None):
    base, candidate = "fixed", "voi"
    manifest = {
        "schema": "hepta.verify.matched-qualification.v1",
        "source_sha256": sha("source"),
        "target_sha256": sha("fixed-horizon-policy"),
        "risk_model_sha256": sha("risk"),
        "checker_model_sha256": sha("checker"),
        "scheduler_sha256": sha("scheduler"),
        "evaluator_id": "external-readback",
        "evaluator_version_sha256": sha("evaluator"),
        "baseline": base,
        "candidate": candidate,
        "pairs": [{
            "pair_id": f"case{i}", "cluster_id": f"cluster{clusters[i] if clusters else i}",
            "first_arm": base if i % 2 else candidate,
            "environment_a": f"env{i}a", "environment_b": f"env{i}b",
        } for i in range(n)],
        "losses": {
            "accept": {"correct": 0.0, "error": 1.0},
            "reject": {"correct": 1.0, "error": 0.0},
            "interrupted": {"correct": 0.7, "error": 0.7},
            "unknown": {"correct": 0.6, "error": 0.6},
        },
        "criteria": {
            "max_error_increase_per_task": 0.0,
            "min_candidate_coverage": 0.5,
            "max_coverage_drop": 0.05,
            "min_terminal_error_reduction_per_task": 0.1,
            "min_mean_gain": 0.5,
            "max_one_sided_p": 0.05,
        },
        "freeze_ns": 100,
        "cost_unit": "frozen-utility",
    }
    rows = []
    for p in manifest["pairs"]:
        for arm, err in ((base, True), (candidate, False)):
            env = p["environment_a"] if arm == p["first_arm"] else p["environment_b"]
            rows.append({
                "pair_id": p["pair_id"], "arm": arm,
                "environment_id": env, "disposition": "accept",
                "terminal_error": err,
                "label_evidence_sha256": sha(p["pair_id"] + arm + "label"),
                "label_issued_ns": 120,
                "decision_issued_ns": 110,
                "evaluator_id": "external-readback",
                "label_attestation": "signed-receipt-stub-do-not-use-in-production",
                "cost_units": 0.1 if arm == candidate else 0,
                "cost_roster_sha256": sha(p["pair_id"] + arm + "roster"),
                "cost_receipt_sha256": sha(p["pair_id"] + arm + "cost"),
                "source_sha256": sha("source"),
            })
    return manifest, rows


class MatchedQualificationTests(unittest.TestCase):
    def analyze(self, manifest, rows, **kwargs):
        return analyze_matched(manifest, rows,
                               verify_label=lambda m, row: True,
                               verify_cost=lambda m, row: True, **kwargs)

    def test_positive_paired_signal_is_only_reviewable_not_promoted(self):
        m, rows = example()
        result = self.analyze(m, rows)
        self.assertAlmostEqual(result["paired_mean_loss_improvement"], 0.9)
        self.assertEqual(result["paired_group_signflip_one_sided_p"], 1 / 256)
        self.assertTrue(result["gates"]["externally_reviewable"])
        self.assertEqual(result["scientific_admission"], "HOLD")
        self.assertEqual(result["production_authority"], "NONE")
        self.assertFalse(result["independent_custody_established_by_this_code"])

    def test_no_terminal_error_reduction_never_qualifies(self):
        m, rows = example()
        for row in rows:
            if row["arm"] == "voi":
                row["terminal_error"] = True
        result = self.analyze(m, rows)
        self.assertFalse(result["gates"]["terminal_error_reduction"])
        self.assertFalse(result["gates"]["externally_reviewable"])

    def test_refuse_reject_everything_even_when_wrong_accepts_fall(self):
        m, rows = example()
        for r in rows:
            if r["arm"] == "voi":
                r["disposition"] = "reject"
                r["terminal_error"] = True
        result = self.analyze(m, rows)
        self.assertEqual(result["arms"]["voi"]["acceptance_coverage"], 0)
        self.assertIsNone(result["arms"]["voi"]["accepted_error_rate_bounds"])
        self.assertFalse(result["gates"]["coverage"])
        self.assertFalse(result["gates"]["externally_reviewable"])

    def test_missing_horizon_not_replaced_by_interrupted_disposition(self):
        m, rows = example()
        r = rows[1]
        r.update(disposition="interrupted", terminal_error=None,
                 label_evidence_sha256=None, label_issued_ns=None,
                 label_attestation=None, evaluator_id=None)
        result = self.analyze(m, rows)
        self.assertEqual(result["arms"]["voi"]["missing_terminal_labels"], 1)
        self.assertIsNone(result["paired_mean_loss_improvement"])
        self.assertIsNone(result["paired_group_signflip_one_sided_p"])
        self.assertFalse(result["gates"]["horizon_labels_complete"])

    def test_missing_cost_and_not_run_preserved_in_denominator(self):
        m, rows = example()
        rows[0].update(cost_units=None, cost_roster_sha256=None,
                       cost_receipt_sha256=None)
        result = self.analyze(m, rows)
        self.assertFalse(result["gates"]["physical_costs_complete_claim_verified"])
        self.assertIsNone(result["paired_mean_loss_improvement"])
        rows.pop()
        result = self.analyze(m, rows)
        self.assertFalse(result["gates"]["roster_complete"])
        self.assertEqual(result["arms"]["voi"]["unobserved"], 1)
        self.assertEqual(result["arms"]["voi"]["planned"], 8)
        self.assertIsNone(result["arms"]["voi"]["acceptance_coverage"])
        self.assertEqual(result["arms"]["voi"]["acceptance_coverage_bounds"], [7/8, 1])
        self.assertEqual(result["arms"]["voi"]["accepted_errors_per_planned_bounds"], [0, 1/8])

    def test_callback_missing_or_truthy_string_does_not_verify(self):
        m, rows = example()
        self.assertFalse(analyze_matched(m, rows)["gates"]["externally_reviewable"])
        result = analyze_matched(m, rows,
                verify_label=lambda *args: "True", verify_cost=lambda *args: True)
        self.assertFalse(result["gates"]["independent_labels_receipt_authenticated"])
        def raise_error(*args):
            raise RuntimeError("external unavailable")
        result = analyze_matched(m, rows, verify_label=raise_error,
                                 verify_cost=lambda *args: True)
        self.assertFalse(result["gates"]["externally_reviewable"])

    def test_multiple_cases_from_same_template_are_one_stat_group(self):
        m, rows = example(clusters=[0] * 8)
        result = self.analyze(m, rows)
        self.assertEqual(result["cluster_count"], 1)
        self.assertEqual(result["paired_group_signflip_one_sided_p"], 0.5)
        self.assertFalse(result["gates"]["paired_statistical_threshold"])

    def test_forged_or_late_records_fail_closed(self):
        m, rows = example()
        mutations = [
            (0, {"environment_id": "other"}),
            (0, {"source_sha256": sha("other")}),
            (0, {"label_issued_ns": 109}),
            (0, {"decision_issued_ns": 99}),
            (0, {"terminal_error": 1}),
            (0, {"cost_units": True}),
            (0, {"label_evidence_sha256": "missing"}),
            (0, {"disposition": "success"}),
        ]
        for index, patch in mutations:
            with self.subTest(patch=patch):
                broken = deepcopy(rows)
                broken[index].update(patch)
                with self.assertRaises(ValueError):
                    self.analyze(m, broken)
        with self.assertRaises(ValueError):
            self.analyze(m, rows + [deepcopy(rows[0])])
        broken = deepcopy(m)
        broken["pairs"][0]["environment_b"] = broken["pairs"][0]["environment_a"]
        with self.assertRaises(ValueError):
            self.analyze(broken, rows)

    def test_unknown_accepted_truth_has_explicit_worst_case(self):
        m, rows = example()
        # A missing terminal label cannot be silently converted into a clean accept.
        rows[1].update(terminal_error=None, label_evidence_sha256=None,
                       label_issued_ns=None, label_attestation=None,
                       evaluator_id=None)
        result = self.analyze(m, rows)
        self.assertEqual(result["arms"]["voi"]["accepted_error_rate_bounds"], [0.0, 1/8])
        self.assertEqual(result["arms"]["voi"]["accepted_errors_per_planned_bounds"], [0, 1/8])


if __name__ == "__main__":
    unittest.main()
