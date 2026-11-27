"""Score identity, missing-census, failed-slot and sealed-label boundary checks."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from cell_field_action_control import score_common
from cell_field_action_io import save_arrays, write_json
from cell_field_features import file_hash
from cell_field_fixed_actions import fixed_library
from cell_field_io_v4 import seal_run
from cell_field_summary_v4 import _fixed, prediction_metrics, pressure_pairs, verify_seal


class SummaryV4Tests(unittest.TestCase):
    def fixture(self, root):
        models = ["loss2", "q4", "history4", "structured4", "full"]
        plan = {"h": .02, "effort_price": .1, "current_shift": .03, "direct_coefficient": .03,
                "feasibility_tolerance": 1e-9, "models": models, "fixed_library": {"amplitudes": [.125, .5, 1.]}}
        library = fixed_library(36)
        actions = np.array([u for _, u in library])
        baseline = np.tile([1., .9], (9, 1))
        real = np.zeros((49, 9, 2))
        real[:, :, 0] = actions[:, :1] * np.arange(9)[None, :] * .001
        predicted = np.array([-real, real*.5, real*.75, real*.9, real])
        save_arrays(root/"reference.npz", {"reference_observations": baseline})
        save_arrays(root/"frozen_predictions.npz", {"actions": actions, "predictions": predicted})
        save_arrays(root/"actual_trajectories.npz", {"real_delta": real, "observations": real+baseline})
        write_json(root/"frozen_plan.json", {"models": models, "actions": [k for k, _ in library],
            "old_anchor": 1., "preparation": {}, "initial_state_sha256": "fixture",
            "frozen_predictions_sha256": file_hash(root/"frozen_predictions.npz")})
        rows = []
        for i, (name, u) in enumerate(library):
            sequence = np.zeros((8, 36))
            sequence[0] = u
            score = lambda value: score_common(value, sequence, baseline, 1.)
            rows.append({"action_id": name, "u": list(u), "status": "completed", "cpu_ns": 17, "wall_ns": 20,
                         "scores": score(real[i]), "predicted_scores": {m: score(predicted[j, i]) for j, m in enumerate(models)}})
        write_json(root/"branches.json", rows)
        return plan, rows

    def test_exact_full_and_same_norm_ranks_and_missing_census(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, rows = self.fixture(root)
            result = _fixed(root, {"status": "completed"}, plan, 36)
            full = [r for r in result["metrics"] if r["model"] == "full"]
            self.assertEqual(len(full), 4)
            for row in full:
                self.assertEqual(row["loss_rmse"], 0)
                self.assertEqual(row["direct_soft_rank"]["predicted_top_actual_regret"], 0)
                self.assertEqual(row["direct_soft_rank"]["kendall_tau_b"], 1)
            write_json(root/"branches.json", rows[:-1])
            with self.assertRaisesRegex(ValueError, "census"):
                _fixed(root, {"status": "completed"}, plan, 36)

    def test_failed_slot_stays_in_census_and_closes_affected_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, rows = self.fixture(root)
            rows[-1].update(status="execution_failed", scores=None)
            write_json(root/"branches.json", rows)
            result = _fixed(root, {"status": "incomplete"}, plan, 36)
            self.assertEqual(result["registered"], 49)
            self.assertEqual(result["completed"], 48)
            affected = [m for m in result["metrics"] if m["amplitude"] in ("all", 1.)]
            self.assertTrue(all(m["status"] == "unavailable" for m in affected))
            self.assertEqual(result["branch_resources"]["cpu_ns"]["measured"], 49)

    def test_report_stage_failure_does_not_discard_completed_raw_census(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, _ = self.fixture(root)
            result = _fixed(root, {"status": "unavailable", "error": {"type": "ReportFailure"}}, plan, 36)
            self.assertEqual(result["completed"], 49)
            self.assertEqual(result["stage_error"]["type"], "ReportFailure")

    def test_tied_prediction_uses_frozen_order_and_preserves_regret(self):
        actual = np.zeros((3, 2, 2))
        predicted = actual.copy()
        actual[:, 0] = 1000  # Initial point is excluded from loss error.
        scores = [{"direct_soft_total": n, "direct_current": n} for n in (2., 1., 0.)]
        forecasts = [{"direct_soft_total": 0., "direct_current": 0.}]*3
        result = prediction_metrics(["b", "a", "c"], predicted, actual, scores, forecasts, actual, [True]*3)
        self.assertEqual(result["loss_rmse"], 0)
        rank = result["direct_soft_rank"]
        self.assertEqual(rank["pair_counts"]["predicted_only_tie"], 3)
        self.assertIsNone(rank["kendall_tau_b"])
        self.assertEqual(rank["predicted_top_actual_regret"], 2)

    def test_same_hard_soft_action_does_not_hide_actual_violation(self):
        score = dict(zip(("direct_soft_total", "direct_current", "forgetting", "effort",
                          "maximum_future_old_excess", "terminal_old_excess"), (1., .5, .4, .1, .2, .1)))
        score["future_retention_within_tolerance"] = False
        rows = [{"candidate_id": "full:b1:"+objective, "objective": objective, "model": "full", "budget_multiplier": 1.,
                 "status": "planned", "execution_status": "completed", "actual_scores": score}
                for objective in ("direct_soft", "direct_hard")]
        pairs = pressure_pairs(rows, {r["candidate_id"]: np.ones((8, 36)) for r in rows}, .02)
        self.assertTrue(pairs[0]["identical_action"])
        self.assertFalse(pairs[0]["hard_actual_feasible"])

    def test_seal_checks_both_label_flags_and_all_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root, protocol = Path(directory)/"run", Path(directory)/"protocol.json"
            write_json(protocol, {"test": True})
            write_json(root/"protocol.json", {"test": True})
            seal = seal_run(root, protocol)
            verify_seal(root, protocol)
            seal["validation_labels_opened"] = True
            write_json(root/"pre_evaluation_seal.json", seal)
            with self.assertRaises(ValueError):
                verify_seal(root, protocol)
            seal["validation_labels_opened"] = False
            write_json(root/"pre_evaluation_seal.json", seal)
            (root/"protocol.json").write_text(json.dumps({"test": False}))
            with self.assertRaises(ValueError):
                verify_seal(root, protocol)


if __name__ == "__main__":
    unittest.main()
