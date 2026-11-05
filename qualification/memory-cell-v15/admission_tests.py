"""Admission contract tests use synthetic executors, not language quality data."""

from dataclasses import replace
import unittest

from admission import COSTS, Case, MatchedEvaluator, Protocol, Run, digest
from admission_test_support import fixture_registration


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.cases = tuple(Case(str(i), str(i), "old" if i < 2000 else "new",
                                "old" if i < 2000 else "new", i, i)
                           for i in range(4000))
        self.protocol = Protocol("frozen-fixture-v1", True, 1000, .05, 1, .1, 30, 1.,
                                 ("old", "new"), (("train_cpu_s", 1.),),
                                 (("peak_rss_bytes", 1000000),))
        self.candidate = Run("new", "input", "training", "executor", "budget", lambda _: "copy", "encoder-v1", "decoder-v1", "tools-v1")
        self.incumbent = Run("old", "input", "training", "executor", "budget",
                             lambda q: "copy" if q == "old" else "miss", "encoder-v1", "decoder-v1", "tools-v1")

    def ledger(self, bundle):
        return {"bundle": bundle, "protocol": self.protocol.identity, "horizon_reads": 1000,
                "protocol_settings": digest(vars(self.protocol)),
                "all_searches_and_failures_included": True,
                "resources": dict.fromkeys(COSTS, 0.)}

    def evaluate(self, **changes):
        protocol = changes.get("protocol", self.protocol)
        cases = changes.get("cases", self.cases)
        candidate = changes.get("candidate", self.candidate)
        registration = fixture_registration(cases, protocol, candidate, self.incumbent)
        evaluator = MatchedEvaluator(cases,
                                     lambda: (lambda op, payload: payload if op == "copy" else None),
                                     protocol, registration=registration)
        return evaluator.evaluate(changes.get("candidate", self.candidate), self.incumbent,
                                  changes.get("candidate_cost", self.ledger("new")),
                                  self.ledger("old"), manifest=changes.get("manifest", {
                                      "bundle": "new", "memory": "input"}))

    def test_positive_synthetic_fixture_executes_both_arms(self):
        report = self.evaluate()
        self.assertTrue(report["approved"], report["reasons"])
        self.assertEqual(report["requests_per_arm"], 4000)
        self.assertEqual(report["paired_mean"], .5)

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
        ledger["resources"]["peak_rss_bytes"] = 1000001
        self.assertIn("candidate_budget_exceeded:peak_rss_bytes",
                      self.evaluate(candidate_cost=ledger)["reasons"])

    def test_duplicate_queries_and_double_pricing_reject(self):
        with self.assertRaises(ValueError):
            self.evaluate(cases=self.cases + self.cases[:1])
        with self.assertRaises(ValueError):
            self.evaluate(protocol=replace(self.protocol, prices=(("billed_usd", 1.), ("train_cpu_s", 1.))))


if __name__ == "__main__":
    unittest.main()
