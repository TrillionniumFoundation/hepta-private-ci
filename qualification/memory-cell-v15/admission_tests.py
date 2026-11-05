"""Admission contract tests use synthetic executors, not language quality data."""

from dataclasses import replace
import unittest

from admission import COSTS, Case, MatchedEvaluator, Protocol, Run, budget_digest, digest
from admission_test_support import fixture_cost_protocol, fixture_ledger, fixture_registration


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.cases = tuple(Case(str(i), str(i), "old" if i < 2000 else "new",
                                "old" if i < 2000 else "new", i, i)
                           for i in range(4000))
        self.protocol = fixture_cost_protocol(Protocol("frozen-fixture-v1", True, 1000, .05, 1, .1, 30, 1.,
                                 ("old", "new"), (("train_cpu_s", 1.),),
                                 (("peak_rss_bytes", 1000000),)))
        self.candidate = Run("new", "input", "training", "executor", budget_digest(self.protocol), lambda _: "copy", "encoder-v1", "decoder-v1", "tools-v1")
        self.incumbent = Run("old", "input", "training", "executor", budget_digest(self.protocol),
                             lambda q: "copy" if q == "old" else "miss", "encoder-v1", "decoder-v1", "tools-v1")

    def ledger(self, bundle):
        evaluator = MatchedEvaluator(self.cases, lambda: (lambda op, payload: payload), self.protocol,
            registration=fixture_registration(self.cases, self.protocol, self.candidate, self.incumbent))
        return fixture_ledger(evaluator, replace(self.candidate, bundle=bundle))

    def evaluate(self, **changes):
        protocol = changes.get("protocol", self.protocol)
        cases = changes.get("cases", self.cases)
        candidate = changes.get("candidate", replace(self.candidate, budget=budget_digest(protocol)))
        incumbent = changes.get("incumbent", replace(self.incumbent, budget=budget_digest(protocol)))
        registration = fixture_registration(cases, protocol, candidate, incumbent)
        evaluator = MatchedEvaluator(cases,
                                     lambda: (lambda op, payload: payload if op == "copy" else None),
                                     protocol, registration=registration)
        return evaluator.evaluate(candidate, incumbent,
                                  changes.get("candidate_cost", fixture_ledger(evaluator, candidate)),
                                  changes.get("incumbent_cost", fixture_ledger(evaluator, incumbent)),
                                  manifest=changes.get("manifest", {
                                      "bundle": "new", "memory": "input"}))

    def test_positive_synthetic_fixture_executes_both_arms(self):
        report = self.evaluate()
        self.assertTrue(report["approved"], report["reasons"])
        self.assertEqual(report["requests_per_arm"], 4000)
        self.assertEqual(report["paired_mean"], .5)
        self.assertTrue(report["quality_qualified"])
        self.assertTrue(report["resource_qualified"])
        self.assertTrue(report["economic_qualified"])

    def test_historical_holdout_does_not_authorize_new_growth(self):
        report = self.evaluate(protocol=replace(self.protocol, prospective=False))
        self.assertFalse(report["approved"])
        self.assertIn("retrospective_evidence_cannot_authorize_growth", report["reasons"])

    def test_unknown_energy_rejects_even_with_zero_energy_price(self):
        ledger = self.ledger("new")
        ledger["resources"]["energy_joules"] = None
        report = self.evaluate(candidate_cost=ledger)
        self.assertFalse(report["approved"])
        self.assertIsNone(report["extra_cost_per_read"])

    def test_all_failed_search_cost_can_reverse_admission(self):
        ledger = self.ledger("new")
        ledger["resources"]["train_cpu_s"] = 1000
        report = self.evaluate(candidate_cost=ledger)
        self.assertIn("positive_full_cost_net_value_not_established", report["reasons"])

    def test_repeated_seeds_are_not_independent_queries(self):
        cases = tuple(replace(c, cluster=c.stratum) for c in self.cases)
        report = self.evaluate(cases=cases)
        self.assertFalse(report["approved"])
        self.assertEqual(report["clusters"], 2)

    def test_regression_on_old_stratum_cannot_hide_behind_average_gain(self):
        candidate = replace(self.candidate, predict=lambda q: "copy" if q == "new" else "miss")
        report = self.evaluate(candidate=candidate)
        self.assertIn("retention_not_established:old", report["reasons"])

    def test_manifest_and_same_information_are_enforced(self):
        report = self.evaluate(candidate=replace(self.candidate, memory="privileged-answer"),
                               manifest={"bundle": "different", "memory": "input"})
        self.assertIn("candidate_manifest_mismatch", report["reasons"])
        self.assertIn("unmatched_memory", report["reasons"])

    def test_bad_cost_values_and_rebound_receipts_reject(self):
        for value in (float("nan"), float("inf")):
            ledger = self.ledger("new")
            ledger["resources"]["energy_joules"] = value
            with self.assertRaises(ValueError):
                self.evaluate(candidate_cost=ledger)
        for value in (-1, True):
            with self.subTest(value=value):
                ledger = self.ledger("different")
                ledger["resources"]["energy_joules"] = value
                report = self.evaluate(candidate_cost=ledger)
                self.assertFalse(report["approved"])
                self.assertIn("candidate_unbound_cost_receipt", report["reasons"])

    def test_errors_and_deadlines_stay_in_denominator(self):
        def fail(_):
            raise RuntimeError("fixture failure")
        report = self.evaluate(candidate=replace(self.candidate, predict=fail))
        self.assertEqual(len(report["traces"]["candidate"]), 4000)
        self.assertTrue(all(x["error"] == "RuntimeError" for x in report["traces"]["candidate"]))
        self.assertFalse(report["approved"])
        report = self.evaluate(protocol=replace(self.protocol, deadline_seconds=1e-12))
        self.assertFalse(report["approved"])
        self.assertEqual(len(report["traces"]["candidate"]), 4000)

    def test_common_resource_cap_is_applied_to_candidate(self):
        ledger = self.ledger("new")
        ledger["resources"]["peak_rss_bytes"] = dict(self.protocol.limits)["peak_rss_bytes"] + 1
        self.assertIn("candidate_budget_exceeded:peak_rss_bytes",
                      self.evaluate(candidate_cost=ledger)["reasons"])

    def test_duplicate_queries_and_double_pricing_reject(self):
        with self.assertRaises(ValueError):
            self.evaluate(cases=self.cases + self.cases[:1])
        with self.assertRaises(ValueError):
            self.evaluate(protocol=replace(self.protocol, prices=(("billed_usd", 1.), ("train_cpu_s", 1.))))

    def test_empty_cost_model_or_caps_cannot_authorize_quality_gain(self):
        for change, expected in (({"prices": ()}, "empty_cost_model"),
                                 ({"limits": ()}, "missing_common_resource_caps")):
            with self.subTest(change=change):
                report = self.evaluate(protocol=replace(self.protocol, **change))
                self.assertTrue(report["quality_qualified"], report["reasons"])
                self.assertFalse(report["approved"])
                self.assertFalse(report["economic_qualified"])
                self.assertIn(expected, report["reasons"])

    def test_every_unpriced_resource_needs_a_frozen_reason(self):
        protocol = replace(self.protocol, zero_cost_reasons=tuple(
            row for row in self.protocol.zero_cost_reasons if row[0] != "energy_joules"))
        report = self.evaluate(protocol=protocol)
        self.assertTrue(report["quality_qualified"])
        self.assertTrue(report["resource_qualified"])
        self.assertFalse(report["economic_qualified"])
        self.assertIn("missing_cost_treatment:energy_joules", report["reasons"])
        self.assertIsNone(report["extra_cost_per_read"])

    def test_same_budget_label_is_not_a_resource_budget(self):
        report = self.evaluate(candidate=replace(self.candidate, budget="same-name"),
                               incumbent=replace(self.incumbent, budget="same-name"))
        self.assertTrue(report["quality_qualified"])
        self.assertFalse(report["resource_qualified"])
        self.assertIn("candidate_budget_identity_mismatch", report["reasons"])
        self.assertIn("incumbent_budget_identity_mismatch", report["reasons"])

    def test_ledger_cannot_move_between_data_workload_cohort_or_information(self):
        for field in ("data", "workload", "cohort_registration", "memory", "training_inputs",
                      "executor", "budget", "encoder", "decoder", "tool_permissions"):
            with self.subTest(field=field):
                ledger = self.ledger("new")
                ledger[field] = "different"
                report = self.evaluate(candidate_cost=ledger)
                self.assertTrue(report["quality_qualified"])
                self.assertFalse(report["resource_qualified"])
                self.assertFalse(report["approved"])
                self.assertIn("candidate_cost_identity_mismatch:" + field, report["reasons"])

    def test_missing_workload_is_not_a_frozen_workload(self):
        report = self.evaluate(protocol=replace(self.protocol, workload_digest=""))
        self.assertFalse(report["approved"])
        self.assertIn("missing_or_invalid_workload_identity", report["reasons"])

    def test_bill_model_can_avoid_double_counting_resources(self):
        protocol = replace(self.protocol, cost_model="bill", prices=(("billed_usd", 1.0),),
                           zero_cost_reasons=tuple((name, "Included in this synthetic bill")
                                                   for name in COSTS if name != "billed_usd"))
        report = self.evaluate(protocol=protocol)
        self.assertTrue(report["approved"], report["reasons"])
        with self.assertRaises(ValueError):
            self.evaluate(protocol=replace(protocol, prices=(("billed_usd", 1.0), ("serve_cpu_s", 1.0))))

    def test_zero_worker_cost_cannot_replace_actual_process_measurement(self):
        ledger = self.ledger("new")
        ledger["resources"].update(serve_cpu_s=0.0, peak_rss_bytes=0)
        report = self.evaluate(candidate_cost=ledger)
        self.assertFalse(report["resource_qualified"])
        self.assertIn("candidate_cost_understates_worker:serve_cpu_s", report["reasons"])
        self.assertIn("candidate_cost_understates_worker:peak_rss_bytes", report["reasons"])

    def test_nonfinite_cost_arithmetic_is_a_refusal_with_finite_evidence(self):
        protocol = replace(self.protocol, prices=(("train_cpu_s", 1e308),))
        candidate, incumbent = replace(self.candidate, budget=budget_digest(protocol)), replace(
            self.incumbent, budget=budget_digest(protocol))
        evaluator = MatchedEvaluator(self.cases, lambda: (lambda op, payload: payload), protocol,
            registration=fixture_registration(self.cases, protocol, candidate, incumbent))
        left, right = fixture_ledger(evaluator, candidate), fixture_ledger(evaluator, incumbent)
        right["resources"]["train_cpu_s"] = 1e308
        report = evaluator.evaluate(candidate, incumbent, left, right,
                                    manifest={"bundle": "new", "memory": "input"})
        self.assertFalse(report["approved"])
        self.assertIsNone(report["extra_cost_per_read"])
        self.assertIn("nonfinite_cost_arithmetic", report["reasons"])
        self.assertEqual(len(report["evidence"]), 64)


if __name__ == "__main__":
    unittest.main()
