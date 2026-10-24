import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from cell_action_cohort import ActionCohort
from cell_action_prepare import prepare_action_curve, verify_action_prepared


IDENTITY = "a"*64
BINDINGS = {"dataset_sha256": "b"*64, "feature_report_sha256": "c"*64, "proposal_plan_sha256": "d"*64}
FIXTURE_PROTOCOL = {"budgets": [8], "seeds": [7], "l2_grid": [.1, 1.], "checkpoints": [1, 2], "rank": 2}


def fixture(role, groups=12):
    rng = np.random.default_rng({"train": 1, "tuning": 2, "calibration": 3, "holdout": 4}[role])
    rows, labels = [], []
    for group in range(groups):
        for action in range(1+group % 3):
            rows.append(dict(source_id=f"{role}-{group}-{action}", group_id=f"{role}-{group}",
                             text=f"{role} complete predictor of source {group} supplied action {action}"))
            labels.append(group % 2)
    labels = np.array(labels)
    x = rng.normal(size=(len(rows), 4))
    x[:, 0] += 3*(labels*2-1)
    return ActionCohort(x.astype(np.float32), labels, tuple(rows), role)


def prepare(root, **changes):
    args = dict(feature_identity=IDENTITY, output_dir=root, task_id="action_usefulness",
                family_id="prospective_execution", input_bindings=BINDINGS, protocol=FIXTURE_PROTOCOL)
    args.update(changes)
    return prepare_action_curve(fixture("train"), fixture("tuning", 8), fixture("calibration", 6), **args)


class ActionPreparationTests(unittest.TestCase):
    def test_explicit_roles_balanced_independent_draws_costs_and_calibrator_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/"prepared"
            frozen = prepare(root)
            self.assertEqual(verify_action_prepared(root), frozen)
            plan, run = frozen["plan"], frozen["runs"][0]
            self.assertFalse(plan["holdout_supplied_to_preparation"])
            self.assertEqual(plan["labelled_pools"]["train"]["groups"], 12)
            self.assertGreater(plan["labelled_pools"]["train"]["rows"], 12)
            self.assertEqual((run["training_rows"], len(set(run["training_group_ids"]))), (8, 8))
            self.assertEqual(run["training_class_counts"], [4, 4])
            self.assertEqual(len(run["search_paths"]), 6)
            self.assertEqual(run["all_search_optimizer_steps"], sum(p["optimizer_steps"] for p in run["search_paths"]))
            self.assertEqual(len(run["arms"]), 8)
            for mode in ("linear", "gated", "residual"):
                arm = run["arms"][mode]
                self.assertEqual(arm["training"]["effective_training_prior"], [.5, .5])
                self.assertEqual(arm["calibration"]["calibration_groups"], 6)
                self.assertEqual(arm["calibration"]["bindings"]["predictor_sha256"], arm["tensor_sha256"])
                self.assertEqual(arm["calibration"]["bindings"]["calibration_context_sha256"], plan["cohorts"]["calibration"])
                self.assertEqual(arm["training"]["optimizer_state_bytes"], 2*arm["training"]["parameter_bytes"])
            self.assertEqual(frozen["unavailable"][0]["budget"], 128)

    def test_calibration_labels_cannot_select_weights_hyperparameters_or_selector(self):
        train, tune, cal = fixture("train"), fixture("tuning", 8), fixture("calibration", 6)
        changed = ActionCohort(cal.features, 1-cal.labels, cal.rows, "calibration")
        with tempfile.TemporaryDirectory() as directory:
            records = [prepare_action_curve(train, tune, cohort, feature_identity=IDENTITY,
                output_dir=Path(directory)/str(index), task_id="t", family_id="f", input_bindings=BINDINGS,
                protocol=FIXTURE_PROTOCOL) for index, cohort in enumerate((cal, changed))]
            a, b = [record["runs"][0] for record in records]
            self.assertEqual(a["training_source_ids"], b["training_source_ids"])
            self.assertEqual(a["selected_arm"], b["selected_arm"])
            for mode in ("linear", "gated", "residual"):
                self.assertEqual(a["arms"][mode]["tensor_sha256"], b["arms"][mode]["tensor_sha256"])
                self.assertEqual(a["arms"][mode]["l2"], b["arms"][mode]["l2"])
                self.assertNotEqual(a["arms"][mode]["calibration"]["fit_input_sha256"],
                                    b["arms"][mode]["calibration"]["fit_input_sha256"])

    def test_unavailable_budget_never_duplicates_group(self):
        with tempfile.TemporaryDirectory() as directory:
            frozen = prepare_action_curve(fixture("train", 6), fixture("tuning", 4), fixture("calibration", 4),
                feature_identity=IDENTITY, output_dir=Path(directory)/"prepared", task_id="t", family_id="f",
                input_bindings=BINDINGS, protocol=FIXTURE_PROTOCOL)
            self.assertEqual(frozen["runs"], [])
            self.assertEqual({r["budget"] for r in frozen["unavailable"]}, {8, 128})
            self.assertEqual(next(r for r in frozen["unavailable"] if r["budget"] == 8)["selected_unique_groups"], 6)

    def test_overlap_invalid_pins_and_changed_preparation_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            train, tune, cal = fixture("train"), fixture("tuning", 8), fixture("calibration", 6)
            rows = list(tune.rows)
            rows[0] = dict(rows[0], group_id=train.rows[0]["group_id"])
            overlap = ActionCohort(tune.features, tune.labels, tuple(rows), "tuning")
            with self.assertRaises(ValueError):
                prepare_action_curve(train, overlap, cal, feature_identity=IDENTITY, output_dir=root/"overlap",
                    task_id="t", family_id="f", input_bindings=BINDINGS, protocol=FIXTURE_PROTOCOL)
            self.assertFalse((root/"overlap").exists())
            with self.assertRaises(ValueError):
                prepare(root/"bad-pin", feature_identity="unbound")
            frozen = prepare(root/"good")
            (root/"good"/"extra.json").write_text("{}")
            with self.assertRaises(ValueError):
                verify_action_prepared(root/"good")
            (root/"good"/"extra.json").unlink()
            frozen["runs"][0]["selected_arm"] = "changed"
            (root/"good"/"frozen.json").write_text(json.dumps(frozen))
            with self.assertRaises(ValueError):
                verify_action_prepared(root/"good")


if __name__ == "__main__":
    unittest.main()
