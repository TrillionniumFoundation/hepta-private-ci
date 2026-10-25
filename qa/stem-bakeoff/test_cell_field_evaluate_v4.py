"""Independent family arithmetic, clustering, missing-data and seal checks."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from cell_field_evaluate_v4 import (
    TASKS, HEADS, SEEDS, POLICIES, SPLITS, CANDIDATE, bootstrap_upper,
    evaluate_probabilities, evaluation_protocol, predictor_metrics, verify_pre_label_seal,
)


class EvaluationV4Tests(unittest.TestCase):
    def fixture(self):
        labels, components, probabilities, costs = {}, {}, {}, {}
        for task in TASKS:
            labels[task] = {split: np.tile(np.arange(4), 8) for split in SPLITS}
            components[task] = {split: np.array([f"{task}/{split}/{i}" for i in range(32)])
                                for split in SPLITS}
            probabilities[task], costs[task] = {}, {}
            for head in HEADS:
                probabilities[task][head], costs[task][head] = {}, {}
                for seed in SEEDS:
                    entry, timing = {}, {}
                    for policy in (*POLICIES, "warmup_old"):
                        confidence = 0.7 if policy == CANDIDATE else 0.6
                        value = np.full((32, 4), (1-confidence)/3)
                        value[np.arange(32), np.tile(np.arange(4), 8)] = confidence
                        entry[policy] = value if policy == "warmup_old" else {s: value.copy() for s in SPLITS}
                        timing[policy] = {"status": "completed", "cpu_ns": 2 if policy == CANDIDATE else 1,
                                          "wall_ns": 3}
                    probabilities[task][head][seed], costs[task][head][seed] = entry, timing
        return probabilities, labels, components, costs

    def test_closed_family_has_exactly_twelve_one_sided_tests(self):
        p, y, c, costs = self.fixture()
        result = evaluate_probabilities(p, y, c, evaluation_protocol(), costs)
        self.assertEqual(len(result["primary_contrasts"]), 12)
        self.assertEqual(result["primary_criteria_met"], 12)
        self.assertTrue(result["all_registered_gates_met"])
        self.assertFalse(result["production_authority"])
        expected = np.log(0.6/0.7)
        for row in result["primary_contrasts"]:
            self.assertAlmostEqual(row["difference"], expected)
            self.assertAlmostEqual(row["upper_bound"], expected)
            self.assertAlmostEqual(row["one_sided_quantile"], 1-0.05/12)
            self.assertEqual(row["source_rows"], 32)  # never three seed copies

    def test_seed_average_precedes_cluster_bootstrap(self):
        p, y, c, costs = self.fixture()
        for task in TASKS:
            for head in HEADS:
                for seed, probability in zip(SEEDS, (0.5, 0.8, 0.7)):
                    for split in SPLITS:
                        values = p[task][head][seed][CANDIDATE][split]
                        values[:] = (1-probability)/3
                        values[np.arange(32), y[task][split]] = probability
        result = evaluate_probabilities(p, y, c, evaluation_protocol(), costs)
        expected = np.mean(np.log(0.6/np.array([0.5, 0.8, 0.7])))
        for row in result["primary_contrasts"]:
            self.assertAlmostEqual(row["difference"], expected)
            self.assertEqual(len(row["paired_seed_mean_differences"]), 3)
            self.assertEqual(row["source_components"], 32)

    def test_repeated_rows_do_not_become_independent_components(self):
        labels = np.repeat(np.arange(4), 2)
        ids = np.array([f"c{i}" for i in range(8)])
        delta = np.array([-1, 2, -2, 1, 0, 4, -3, 1], dtype=float)
        once = bootstrap_upper(delta, labels, ids)
        repeated = bootstrap_upper(np.repeat(delta, 3), np.repeat(labels, 3), np.repeat(ids, 3))
        self.assertEqual(once["source_components"], repeated["source_components"])
        self.assertAlmostEqual(once["upper_bound"], repeated["upper_bound"])
        self.assertAlmostEqual(once["difference"], repeated["difference"])

    def test_missing_secondary_policy_or_cost_closes_gate(self):
        p, y, c, costs = self.fixture()
        del p["uci"]["linear"][7]["q4_h8"]
        result = evaluate_probabilities(p, y, c, evaluation_protocol(), costs)
        self.assertEqual(result["primary_criteria_met"], 12)
        self.assertFalse(result["census_complete"])
        self.assertFalse(result["all_registered_gates_met"])
        p, y, c, costs = self.fixture()
        result = evaluate_probabilities(p, y, c, evaluation_protocol())
        self.assertFalse(result["all_cost_criteria_met"])
        self.assertTrue(all(row["status"] == "unavailable" for row in result["cost_contrasts"]))
        del costs["uci"]["linear"][7]["q4_h8"]
        result = evaluate_probabilities(p, y, c, evaluation_protocol(), costs)
        self.assertTrue(result["all_scientific_criteria_met"])
        self.assertFalse(result["cost_census_complete"])
        self.assertFalse(result["all_registered_gates_met"])

    def test_retention_and_improvement_have_different_boundaries(self):
        p, y, c, costs = self.fixture()
        for task, task_rows in p.items():
            for head_rows in task_rows.values():
                for entry in head_rows.values():
                    entry[CANDIDATE]["old"] = entry["warmup_old"].copy()
                    entry[CANDIDATE]["future"] = entry["loss2_h8"]["future"].copy()
        result = evaluate_probabilities(p, y, c, evaluation_protocol(), costs)
        self.assertFalse(result["all_scientific_criteria_met"])
        for row in result["primary_contrasts"]:
            self.assertEqual(row["criterion_met"], row["split"] == "old")
        plan = evaluation_protocol()
        plan["family_size"] = 1
        with self.assertRaises(ValueError):
            evaluate_probabilities(p, y, c, plan, costs)

    def test_seal_rejects_modified_or_uninventoried_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/"run"
            root.mkdir()
            protocol = Path(directory)/"protocol.json"
            protocol.write_text(json.dumps(evaluation_protocol()))
            output = root/"prediction.bin"
            output.write_bytes(b"frozen probabilities")
            sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            seal = {"files": {output.name: {"sha256": sha(output), "bytes": output.stat().st_size}},
                    "protocol_sha256": sha(protocol), "final_labels_opened": False}
            (root/"pre_evaluation_seal.json").write_text(json.dumps(seal))
            self.assertEqual(verify_pre_label_seal(root, protocol), seal)
            output.write_bytes(b"changed probabilities")
            with self.assertRaises(ValueError):
                verify_pre_label_seal(root, protocol)
            output.write_bytes(b"frozen probabilities")
            (root/"extra.bin").write_bytes(b"new output")
            with self.assertRaises(ValueError):
                verify_pre_label_seal(root, protocol)

    def test_predictor_exact_and_reversed_rank_are_visible(self):
        real = np.zeros((3, 3, 2))
        real[:, -1, 0] = [0, 1, 2]
        predicted = np.stack((real, real[::-1]))
        result = predictor_metrics(real, predicted, np.zeros((3, 1)), 0.02,
                                   np.zeros(2), 0.1, ["exact", "reverse"])
        self.assertEqual(result[0]["loss_rmse"], 0)
        self.assertEqual(result[0]["top1_regret"], 0)
        self.assertEqual(result[1]["spearman"], -1)
        self.assertGreater(result[1]["top1_regret"], 0)


if __name__ == "__main__":
    unittest.main()
