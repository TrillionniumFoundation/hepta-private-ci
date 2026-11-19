"""V5 exact comparison family, stop semantics and non-softenable gates."""

import unittest

import numpy as np

from cell_field_evaluate_v5 import TASKS, HEADS, SEEDS, POLICIES, SPLITS, CANDIDATE, evaluate_probabilities, evaluation_protocol


class EvaluationV5Tests(unittest.TestCase):
    def fixture(self):
        probabilities, labels, components, costs = {}, {}, {}, {}
        for task in TASKS:
            labels[task] = {s: np.tile(np.arange(4), 8) for s in SPLITS}
            components[task] = {s: np.array([f"{task}/{s}/{i}" for i in range(32)]) for s in SPLITS}
            probabilities[task], costs[task] = {}, {}
            for head in HEADS:
                probabilities[task][head], costs[task][head] = {}, {}
                for seed in SEEDS:
                    entry, timing = {}, {}
                    for policy in (*POLICIES, "warmup_old"):
                        confidence = .7 if policy == CANDIDATE else .6
                        p = np.full((32, 4), (1-confidence)/3)
                        p[np.arange(32), labels[task]["old"]] = confidence
                        entry[policy] = p if policy == "warmup_old" else {s: p.copy() for s in SPLITS}
                        timing[policy] = {"status": "completed", "completed_steps": 32, "registered_steps": 32,
                                          "cpu_ns": 2 if policy == CANDIDATE else 1, "wall_ns": 3, "valid_record": True}
                    probabilities[task][head][seed], costs[task][head][seed] = entry, timing
        return probabilities, labels, components, costs

    def test_family_exactly_twelve_and_same_source_counts(self):
        p, y, c, times = self.fixture()
        result = evaluate_probabilities(p, y, c, evaluation_protocol(), times)
        self.assertTrue(result["all_registered_gates_met"])
        self.assertEqual(result["registered_policy_outputs"], 72)
        self.assertEqual(result["candidate_completed_fits"], 12)
        self.assertEqual(len(result["completion_gates"]), 36)
        self.assertEqual(len(result["primary_contrasts"]), 12)
        for row in result["primary_contrasts"]:
            self.assertEqual(row["source_components"], 32)
            self.assertAlmostEqual(row["difference"], np.log(.6/.7))

    def test_diagnostic_stop_scored_but_primary_stop_disqualifies(self):
        p, y, c, times = self.fixture()
        times["agnews"]["linear"][7]["adjoint_h8"].update(status="stopped", completed_steps=0)
        result = evaluate_probabilities(p, y, c, evaluation_protocol(), times)
        self.assertTrue(result["all_registered_gates_met"])
        self.assertTrue(any(r.get("execution_status") == "stopped" and r["status"] == "completed" for r in result["records"]))
        times["agnews"]["linear"][7]["loss2_h8"].update(status="stopped", completed_steps=31)
        result = evaluate_probabilities(p, y, c, evaluation_protocol(), times)
        self.assertTrue(result["census_complete"])
        self.assertFalse(result["required_completion_met"])
        self.assertFalse(result["all_registered_gates_met"])
        rows = [r for r in result["primary_contrasts"] if r["task"] == "agnews" and r["head"] == "linear"]
        self.assertTrue(all(r["status"] == "scored_but_incomplete_execution" and not r["criterion_met"] for r in rows))

    def test_any_actual_error_or_missing_output_closes_gate(self):
        p, y, c, times = self.fixture()
        times["agnews"]["linear"][7]["adjoint_h8"].update(status="execution_failed", valid_record=False)
        self.assertFalse(evaluate_probabilities(p, y, c, evaluation_protocol(), times)["all_registered_gates_met"])
        p, y, c, times = self.fixture()
        del p["dbpedia"]["gated"][29]["zero"]
        self.assertFalse(evaluate_probabilities(p, y, c, evaluation_protocol(), times)["census_complete"])

    def test_margin_and_cost_thresholds_cannot_be_relaxed(self):
        p, y, c, times = self.fixture()
        plan = evaluation_protocol()
        plan["improvement_margin"] = 0
        with self.assertRaises(ValueError):
            evaluate_probabilities(p, y, c, plan, times)
        for task in TASKS:
            for head in HEADS:
                for seed in SEEDS:
                    times[task][head][seed][CANDIDATE]["cpu_ns"] = 3.0001
        result = evaluate_probabilities(p, y, c, evaluation_protocol(), times)
        self.assertTrue(result["all_scientific_criteria_met"])
        self.assertFalse(result["all_cost_criteria_met"])


if __name__ == "__main__":
    unittest.main()
