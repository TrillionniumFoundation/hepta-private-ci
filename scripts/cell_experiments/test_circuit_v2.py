"""Synthetic mechanics tests; their rows are not research observations."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from cell_experiments.circuit_v2 import PathCircuit, evaluate, fit_arm
from cell_experiments.circuit_study_v2 import (
    confirm_selection,
    freeze_selection,
    source_growth_plan,
)
from cell_experiments.composition_core import ARMS, digest


PLAN = {
    "width": 3,
    "hidden": 2,
    "classes": 2,
    "cells": 4,
    "updates": 48,
    "rate": 0.03,
    "seed": 1729,
    "feature_binding_digest": "a" * 64,
}


def rows(panel):
    return [
        {
            "task_id": f"{panel}-{index}",
            "source_id": f"{panel}-source-{index}",
            "project_id": f"project-{panel}",
            "lineage_id": f"{panel}-lineage-{index}",
            "family_id": f"family-{panel}",
            "observation_digest": digest([panel, index]),
            "features": [1.0, index / 3, -0.4],
            "target": index % 2,
        }
        for index in range(4)
    ]


class CircuitTests(unittest.TestCase):
    def test_gradient_matches_finite_difference_on_selected_path(self):
        model = PathCircuit(3, 2, 2, 4, "learned_sparse", 19)
        model.path = (1, 3)
        features = [0.7, -0.2, 0.4]
        _, gradients = model.loss_gradient(features, 1)
        self.assertFalse(
            any(
                name.startswith("cell_0") or name.startswith("cell_2")
                for name in gradients
            )
        )
        for name, gradient in gradients.items():
            for index in np.ndindex(gradient.shape):
                original = model.parameters[name][index]
                model.parameters[name][index] = original + 1e-6
                plus = model.loss_gradient(features, 1)[0]
                model.parameters[name][index] = original - 1e-6
                minus = model.loss_gradient(features, 1)[0]
                model.parameters[name][index] = original
                self.assertAlmostEqual(
                    float(gradient[index]), (plus - minus) / 2e-6, places=7
                )
        self.assertEqual(
            sum(value.size for value in gradients.values()),
            model.cost()["active_parameters_per_example"],
        )
        self.assertEqual(model.cost(training=True)["matrix_dot_mac"], 30)
        self.assertEqual(model.cost(training=True)["outer_product_multiplications"], 18)
        self.assertEqual(model.cost(training=True)["model_mac_equivalent"], 48)

    def test_actual_useful_training_kernels_match_without_router_padding(self):
        results = {arm: fit_arm(rows("A"), PLAN, arm) for arm in ARMS}
        reference = results["single"][1]
        for arm, (model, receipt) in results.items():
            self.assertEqual(receipt["kernel_totals"], reference["kernel_totals"])
            self.assertEqual(model.cost()["active_parameters_per_example"], 26)
            self.assertEqual(len(receipt["history"]), PLAN["updates"])
            self.assertNotEqual(
                receipt["model_digest"], receipt["initial_model_digest"]
            )
        self.assertEqual(
            evaluate(results["single"][0], rows("B"))["rows"],
            evaluate(results["fixed"][0], rows("B"))["rows"],
        )
        self.assertEqual(results["learned_sparse"][1]["visited_cells"], [0, 1, 2, 3])
        self.assertEqual(
            sum(results["learned_sparse"][1]["path_counts"]), PLAN["updates"]
        )
        self.assertGreater(
            results["learned_sparse"][1]["control_overhead"]["sqrt_evaluations"], 0
        )
        self.assertNotEqual(
            results["single"][0].cost()["resident_parameters"],
            results["fixed"][0].cost()["resident_parameters"],
        )

    def test_cell_and_intercell_edge_ablation_changes_activation_flow(self):
        model = PathCircuit(3, 2, 2, 4, "fixed", 1)
        for name, parameter in model.parameters.items():
            parameter[:] = 0 if name.endswith("_b") else 0.5
        model.parameters["output_w"][:, 1] = -0.3
        features = [1.0, 2.0, 3.0]
        logits = model.forward(features)[0]
        self.assertGreater(float(np.linalg.norm(logits)), 0)
        for cell in model.path:
            np.testing.assert_array_equal(
                model.forward(features, drop_cell=cell)[0], [0.0, 0.0]
            )
        for edge in range(3):
            np.testing.assert_array_equal(
                model.forward(features, drop_edge=edge)[0], [0.0, 0.0]
            )
        np.testing.assert_array_equal(model.forward(features, drop_cell=3)[0], logits)

    def test_roundtrip_preserves_graph_weights_and_rejects_changed_bytes(self):
        model, _ = fit_arm(rows("A"), PLAN, "learned_sparse")
        record = json.loads(json.dumps(model.record()))
        restored = PathCircuit.restore(record, digest(record))
        self.assertEqual(restored.record(), model.record())
        self.assertEqual(
            evaluate(restored, rows("B"))["rows"], evaluate(model, rows("B"))["rows"]
        )
        record["parameters"]["input_w"][0][0] += 0.01
        with self.assertRaisesRegex(ValueError, "bytes differ"):
            PathCircuit.restore(record, digest(model.record()))


class StudyTests(unittest.TestCase):
    def test_b_is_frozen_before_c_and_ablations_do_not_reselect(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "study"
            freeze = freeze_selection(rows("A"), rows("B"), PLAN, directory)
            raw = (directory / "FROZEN_SELECTION.json").read_bytes()
            self.assertFalse((directory / "C_STARTED.json").exists())
            c_rows = rows("C")
            for row in c_rows:
                row["target"] = 1 - row["target"]
            report = confirm_selection(c_rows, directory, freeze["frozen_digest"])
            self.assertEqual(report["selected_arm"], freeze["frozen"]["selected_arm"])
            self.assertEqual((directory / "FROZEN_SELECTION.json").read_bytes(), raw)
            self.assertFalse(report["selection_changed_after_c"])
            self.assertEqual(report["unique_c_task_count"], 4)
            self.assertEqual(report["total_c_panel_accesses"], 34)
            self.assertEqual(
                sum(
                    len(value["ablations"]["cells"]) + len(value["ablations"]["edges"])
                    for value in report["arms"].values()
                ),
                26,
            )
            self.assertTrue(
                all(
                    value["parameter_roundtrip_predictions_equal"]
                    for value in report["arms"].values()
                )
            )
            with self.assertRaises(FileExistsError):
                confirm_selection(c_rows, directory, freeze["frozen_digest"])

    def test_mutated_frozen_checkpoint_is_rejected_before_c_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "study"
            freeze = freeze_selection(rows("A"), rows("B"), PLAN, directory)
            path = directory / "single" / "MODEL.json"
            model = json.loads(path.read_text())
            model["parameters"]["input_b"][0] += 1
            path.write_text(json.dumps(model))
            with self.assertRaisesRegex(ValueError, "artifact differs"):
                confirm_selection(rows("C"), directory, freeze["frozen_digest"])
            self.assertFalse((directory / "C_STARTED.json").exists())

    def test_cross_panel_lineage_and_relabelled_observations_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            a_rows, b_rows = rows("A"), rows("B")
            b_rows[0]["lineage_id"] = a_rows[0]["lineage_id"]
            with self.assertRaisesRegex(ValueError, "cross-panel lineage"):
                freeze_selection(a_rows, b_rows, PLAN, Path(temporary) / "bad")
            self.assertFalse((Path(temporary) / "bad").exists())

    def test_e5_replay_and_alias_projects_do_not_create_source_groups(self):
        original = rows("A")
        replay = copy.deepcopy(original)
        for index, row in enumerate(replay):
            row["task_id"] += "-branch"
            row["project_id"] = f"claimed-new-project-{index}"
        plan = source_growth_plan(original + replay)
        self.assertEqual(plan["available_groups"], 1)
        self.assertEqual(
            sum(setting["status"] == "BLOCKED" for setting in plan["settings"]), 6
        )
        ready = [
            setting for setting in plan["settings"] if setting["status"] != "BLOCKED"
        ]
        self.assertEqual([setting["updates"] for setting in ready], [224, 224])
        self.assertEqual([setting["unique_lineages"] for setting in ready], [4, 4])
        self.assertEqual([setting["unique_observations"] for setting in ready], [4, 4])
        self.assertEqual(
            [setting["provenance_disjoint_task_clusters"] for setting in ready], [4, 4]
        )
        self.assertEqual(plan["verified_users"], 0)
        self.assertEqual(
            source_growth_plan(original, unit_field="source_id")["available_groups"], 4
        )


if __name__ == "__main__":
    unittest.main()
