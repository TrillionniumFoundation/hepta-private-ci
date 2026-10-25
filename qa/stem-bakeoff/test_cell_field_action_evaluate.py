"""Frozen diagnostic-family, paired-source and failure-census checks."""

import copy
import itertools
import json
from pathlib import Path
import unittest

import numpy as np

from cell_field_action_evaluate import (FINAL_ROLES, compare_scores, method_id,
                                       registered_methods, score_payload, validate_plan)


def protocol():
    return json.loads(Path(__file__).with_name("cell_field_action_protocol.json").read_text())


def score_fixture():
    plan = protocol()
    targets = {role: np.tile(np.arange(4), n) for role, n in zip(FINAL_ROLES, [1, 1, 2, 3])}
    methods = [method_id(*spec) for spec in registered_methods(plan)] + ["warmup"]
    scores = {}
    for seed, head, method, role in itertools.product(plan["seeds"], plan["head_modes"], methods, FINAL_ROLES):
        value = float(FINAL_ROLES.index(role)) if method == "loss2_h8_direct_soft" else 0.0
        scores[(seed, head, 16, method, role)] = {"nll": np.full(len(targets[role]), value),
                                                "accuracy": np.zeros(len(targets[role]))}
    return plan, scores, targets


class ActionEvaluationTests(unittest.TestCase):
    def test_registered_family_rejects_posthoc_threshold_change(self):
        plan = protocol()
        validate_plan(plan)
        changed = copy.deepcopy(plan)
        changed["primary_comparisons"][0]["upper_bound_rule"] = "at_most_zero"
        with self.assertRaisesRegex(ValueError, "primary diagnostic"):
            validate_plan(changed)

    def test_future_weights_months_equally_and_does_not_multiply_sources_by_seeds(self):
        plan, scores, targets = score_fixture()
        secondary, primary, decisions = compare_scores(scores, targets, plan)
        self.assertEqual((len(secondary), len(primary), len(decisions)), (96, 8, 2))
        row = primary[0]
        self.assertEqual(row["difference_left_minus_right"], 2.0)
        self.assertEqual(row["bonferroni_percentile_interval"], [2.0, 2.0])
        self.assertEqual(row["source_components"], 24)
        self.assertEqual(row["components_by_role"], {"future_june": 4, "future_july": 8, "future_august": 12})

    def test_missing_seed_makes_the_whole_pair_unavailable(self):
        plan, scores, targets = score_fixture()
        del scores[(29, "linear", 16, "loss2_h8_direct_soft", "future_july")]
        _, primary, decisions = compare_scores(scores, targets, plan)
        self.assertEqual(primary[0]["status"], "unavailable_registered_seed")
        self.assertNotIn("difference_left_minus_right", primary[0])
        self.assertEqual(primary[4]["status"], "completed")
        self.assertFalse(decisions[0]["all_registered_diagnostics_met"])

    def test_payload_preserves_infeasibility_and_path_mean_semantics(self):
        plan = protocol()
        roles = ("old_validation", "current_validation")
        sources = [{"source_id": f"source{i}", "role": roles[i // 4]} for i in range(8)]
        labels = {role: {"indices": list(range(4 * j, 4 * j + 4)), "labels": list(range(4)),
                         "source_ids": [f"source{i}" for i in range(4 * j, 4 * j + 4)]}
                  for j, role in enumerate(roles)}
        probabilities = np.tile(np.eye(4) * 0.6 + 0.1, (2, 1))
        records = [{"run_id": "zero", "seed": 7, "head": "linear", "anchor_offset": 0,
                    "method_id": "zero", "status": "completed", "warmup_index": 0, "initial_index": 0},
                   {"run_id": "hard", "seed": 7, "head": "linear", "anchor_offset": 0,
                    "method_id": "loss2_h8_direct_hard", "status": "tangent_infeasible", "warmup_index": 0, "initial_index": 0}]
        initial = {"seed": 7, "head": "linear", "status": "completed"}
        runs = {"records": records, "retention_indices": list(range(4)), "warmup_order": [initial],
                "initial_order": [{**initial, "anchor_offset": 0}]}
        arrays = {"warmup_probabilities": probabilities[None], "initial_probabilities": probabilities[None],
                  "terminal_probabilities": np.stack([probabilities, np.full_like(probabilities, np.nan)]),
                  "retention_probabilities": np.stack([np.tile(probabilities[:4], (9, 1, 1)), np.full((9, 4, 4), np.nan)])}
        context = (None, None, None, runs, plan, None, sources, arrays, None)
        result, _, _ = score_payload(context, roles, json.dumps({"schema": "hepta.cell-action-news.v3", "classes": 4, "roles": labels}).encode())
        self.assertEqual(len(result["records"]), 4)
        self.assertEqual(result["retention_paths"][0]["future_violation_steps"], [])
        self.assertEqual(result["retention_paths"][1]["status"], "tangent_infeasible")
        self.assertIsNone(result["retention_paths"][1]["metrics"])
        corrupted = copy.deepcopy(labels)
        corrupted["old_validation"]["indices"] = [1, 0, 2, 3]
        with self.assertRaisesRegex(ValueError, "heldout labels"):
            score_payload(context, roles, json.dumps({"schema": "hepta.cell-action-news.v3", "classes": 4, "roles": corrupted}).encode())


if __name__ == "__main__":
    unittest.main()
