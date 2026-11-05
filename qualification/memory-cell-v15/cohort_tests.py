"""Adversarial evidence controls, with synthetic finite tasks and stated costs."""

from copy import deepcopy
from dataclasses import replace
import unittest

from admission import COSTS, Case, MatchedEvaluator, Protocol, Run, digest
from admission_test_support import fixture_registration


class CohortTests(unittest.TestCase):
    def setUp(self):
        self.cases = [Case(str(i), str(i), "retained", "query", i, i) for i in range(256)]
        self.protocol = Protocol("cohort-fixture", True, 256, .05, 1, .25, 16, 1.,
                                 ("retained",), (), ())
        self.candidate = Run("new", "memory", "history", "executor", "budget", lambda _: True,
                             "encoder", "decoder", "tools")
        self.incumbent = replace(self.candidate, bundle="old", predict=lambda _: False)
        self.registration = fixture_registration(self.cases, self.protocol,
                                                 self.candidate, self.incumbent)

    def evaluate(self, registration, *, candidate=None, cases=None, mutate=None):
        evaluator = MatchedEvaluator(self.cases if cases is None else cases,
            lambda: (lambda choice, payload: payload if choice else None), self.protocol,
            registration=registration)
        if mutate is not None:
            mutate()
        def ledger(bundle):
            return {"bundle": bundle, "protocol": self.protocol.identity, "horizon_reads": 256,
                    "protocol_settings": digest(vars(self.protocol)),
                    "all_searches_and_failures_included": True, "resources": dict.fromkeys(COSTS, 0)}
        return evaluator.evaluate(candidate or self.candidate, self.incumbent,
                                  ledger("new"), ledger("old"),
                                  manifest={"bundle": "new", "memory": "memory"})

    def test_prospective_flag_alone_no_longer_authorizes_admission(self):
        result = self.evaluate(None)
        self.assertFalse(result["approved"])
        self.assertIn("missing_frozen_cohort_registration", result["reasons"])
        self.assertIsNone(result["qualified_clusters"])

    def test_registered_synthetic_control_executes_and_binds_registration(self):
        result = self.evaluate(self.registration)
        self.assertTrue(result["approved"], result["reasons"])
        self.assertEqual(result["qualified_clusters"], 256)
        self.assertEqual(result["cohort_registration"], digest(self.registration))

    def test_information_privilege_rejects_even_when_declared(self):
        for field in ("encoder", "decoder", "tool_permissions"):
            with self.subTest(field=field):
                candidate = replace(self.candidate, **{field: "privileged"})
                registered = fixture_registration(self.cases, self.protocol, candidate, self.incumbent)
                result = self.evaluate(registered, candidate=candidate)
                self.assertFalse(result["approved"])
                self.assertIn("unmatched_" + field, result["reasons"])

    def test_source_cluster_leakage_across_all_pre_final_phases_rejects(self):
        for phase in ("train", "calibration", "selection"):
            with self.subTest(phase=phase):
                registered = deepcopy(self.registration)
                registered["phases"][phase]["clusters"].append("0")
                result = self.evaluate(registered)
                self.assertFalse(result["approved"])
                self.assertIn("phase_cluster_leakage:final", result["reasons"])

    def test_observation_before_candidate_freeze_rejects(self):
        registered = deepcopy(self.registration)
        registered["frozen_at"] = 5
        result = self.evaluate(registered)
        self.assertFalse(result["approved"])
        self.assertIn("final_not_after_freeze", result["reasons"])

    def test_new_candidate_cannot_reuse_another_candidates_registration(self):
        registered = deepcopy(self.registration)
        registered["comparisons"] = [["different-candidate", "old"]]
        result = self.evaluate(registered)
        self.assertFalse(result["approved"])
        self.assertIn("unregistered_candidate_comparison", result["reasons"])

    def test_candidate_search_roster_cannot_exceed_frozen_error_budget(self):
        registered = deepcopy(self.registration)
        registered["comparisons"].append(["another-candidate", "old"])
        result = self.evaluate(registered)
        self.assertFalse(result["approved"])
        self.assertIn("invalid_frozen_comparison_roster", result["reasons"])

    def test_unplanned_monitoring_look_rejects(self):
        registered = deepcopy(self.registration)
        registered["look_index"] = 2
        result = self.evaluate(registered)
        self.assertFalse(result["approved"])
        self.assertIn("unregistered_monitoring_look", result["reasons"])

    def test_planned_monitoring_looks_share_the_error_budget(self):
        initial = self.evaluate(self.registration)
        self.protocol = replace(self.protocol, planned_looks=10)
        registered = fixture_registration(self.cases, self.protocol, self.candidate, self.incumbent)
        result = self.evaluate(registered)
        self.assertTrue(result["approved"], result["reasons"])
        self.assertAlmostEqual(result["per_bound_alpha"], initial["per_bound_alpha"] / 10)
        self.assertLess(result["paired_lower_bound"], initial["paired_lower_bound"])

    def test_ten_nodes_cannot_turn_one_source_task_into_ten_samples(self):
        registered = deepcopy(self.registration)
        for key in map(str, range(10)):
            registered["final_units"][key]["unit"] = "same-origin-task"
        result = self.evaluate(registered)
        self.assertFalse(result["approved"])
        self.assertIsNone(result["qualified_clusters"])
        self.assertIn("replicated_source_unit:same-origin-task", result["reasons"])

    def test_many_steps_of_one_rollout_still_count_as_one_cluster(self):
        cases = [replace(case, cluster="one-rollout") for case in self.cases]
        registered = fixture_registration(cases, self.protocol, self.candidate, self.incumbent)
        result = self.evaluate(registered, cases=cases)
        self.assertFalse(result["approved"])
        self.assertEqual(result["qualified_clusters"], 1)
        self.assertIn("insufficient_independent_clusters", result["reasons"])

    def test_nested_registration_mutation_cannot_relabel_the_frozen_sources(self):
        expected = digest(self.registration)
        result = self.evaluate(self.registration, mutate=lambda: self.registration["phases"].clear())
        self.assertTrue(result["approved"], result["reasons"])
        self.assertEqual(result["cohort_registration"], expected)

    def test_final_data_or_arm_identity_change_rejects(self):
        registered = deepcopy(self.registration)
        registered["data"] = "different-data"
        registered["arms"]["new"]["training_inputs"] = "hidden-extra-history"
        result = self.evaluate(registered)
        self.assertFalse(result["approved"])
        self.assertIn("cohort_identity_mismatch", result["reasons"])
        self.assertIn("unbound_arm_information:new", result["reasons"])

    def test_malformed_phase_and_comparison_are_rejected(self):
        registered = deepcopy(self.registration)
        registered["phases"]["final"] = None
        registered["comparisons"] = None
        result = self.evaluate(registered)
        self.assertFalse(result["approved"])
        self.assertIn("invalid_phase:final", result["reasons"])


if __name__ == "__main__":
    unittest.main()
