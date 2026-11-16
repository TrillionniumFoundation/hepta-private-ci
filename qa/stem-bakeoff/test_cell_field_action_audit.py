"""Independent certificate and complete-checkpoint rejection tests."""

import copy
import itertools
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from cell_field_action_audit import checkpoint
from cell_field_action_control import plan_action
from cell_field_action_evaluate import ranking_report
from cell_field_action_math_audit import audit_plan, audit_ranking
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead
from test_cell_field_action_score_audit import fixture


def close(name, actual, expected):
    if not np.allclose(actual, expected, rtol=3e-11, atol=3e-11):
        raise ValueError("independent " + name + " differs")


class ActionAuditTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads(Path(__file__).with_name("cell_field_action_protocol.json").read_text())
        maps = np.zeros((9, 2, 2))
        for k in range(1, 9):
            maps[k] = np.array([[-0.02, 0.01], [0.01, 0.015]]) * k / 8
        self.model = {"loss_maps": maps, "reference_observations": np.tile([0.7, 0.6], (9, 1))}

    def proposal(self, objective="direct_soft", lookahead=8, old_anchor=0.7):
        result = plan_action(self.model, objective=objective, lookahead=lookahead, old_anchor=old_anchor)
        arrays = {key: value.copy() for key, value in result.items() if isinstance(value, np.ndarray)}
        arrays.update({"problem__" + key: np.asarray(value) for key, value in result["problem"].items()})
        return arrays, {"status": result["status"], "record": copy.deepcopy(result["record"])}, {
            "objective": objective, "lookahead": lookahead}

    def test_all_objectives_and_horizons_match_independent_certificates(self):
        for objective, horizon in itertools.product(self.plan["objectives"], self.plan["lookaheads"]):
            arrays, saved, info = self.proposal(objective, horizon)
            answer = audit_plan(arrays, saved, self.model, info, 0.7, self.plan, close)
            self.assertEqual(answer["kind"], "qualified")
            self.assertLessEqual(answer["gap"], 1e-9)

    def test_changed_objective_and_fabricated_optimality_gap_are_rejected(self):
        arrays, saved, info = self.proposal()
        arrays["problem__c"][0] += 0.01
        with self.assertRaisesRegex(ValueError, "problem_c"):
            audit_plan(arrays, saved, self.model, info, 0.7, self.plan, close)
        arrays, saved, info = self.proposal()
        arrays["u"][0] += 0.01
        with self.assertRaisesRegex(ValueError, "gradient|objective|stationarity"):
            audit_plan(arrays, saved, self.model, info, 0.7, self.plan, close)

    def test_infeasibility_requires_valid_nonnegative_separating_witness(self):
        self.model["loss_maps"][:, 1] = 0
        arrays, saved, info = self.proposal("direct_hard", old_anchor=0.5)
        result = audit_plan(arrays, saved, self.model, info, 0.5, self.plan, close)
        self.assertEqual(result["kind"], "tangent_infeasible")
        self.assertGreater(result["witness_margin"], 0.09)
        arrays["farkas_weights"][:] = 0
        with self.assertRaisesRegex(ValueError, "normalization"):
            audit_plan(arrays, saved, self.model, info, 0.5, self.plan, close)

    def test_ranking_audit_rejects_wrong_pair_order_and_retains_missing_candidates(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _, _, _ = fixture(Path(temp), missing_hard_seed=True)
            runs = json.loads((root / "runs.json").read_bytes())
            for i, record in enumerate(runs["records"]):
                for obs in ("loss2", "full"):
                    for objective in ("direct_soft_total", "tracking_soft_total"):
                        record["predicted_scores"][obs][objective] = i % 19
                        record["actual_scores"][objective] = -(i % 19)
            ranking = ranking_report(runs, self.plan)
            verified = audit_ranking(runs, self.plan, ranking, close)
            self.assertEqual(verified["completed_ranking_rows"], 72)
            ranking["records"][0]["pair_counts"]["concordant"] += 1
            with self.assertRaisesRegex(ValueError, "ranking or tie"):
                audit_ranking(runs, self.plan, ranking, close)

    def test_checkpoint_metadata_edit_cannot_preserve_complete_state_identity(self):
        rng = np.random.default_rng(49)
        features, labels = rng.normal(size=(12, 2)), np.tile(np.arange(4), 3)
        state = CellTrainingState(NumpyCellHead(2, 4, "gated", seed=7), bindings={"fixture": "only"},
            contexts={"train": dataset_digest(features, labels)}, active_context="train")
        state.advance(features, labels)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state.save(root / "checkpoint")
            vector, manifest, _ = checkpoint(root, "checkpoint")
            np.testing.assert_array_equal(vector, state.vector())
            manifest["step_count"] += 1
            (root / "checkpoint/manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "complete checkpoint digest"):
                checkpoint(root, "checkpoint")


if __name__ == "__main__":
    unittest.main()
